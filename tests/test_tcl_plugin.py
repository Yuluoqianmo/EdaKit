"""Capture 侧 TCL 插件的语法与逻辑测试。

没有 Capture 也能验：只要本机有 `tclsh`，就可以把插件的 Capture 相关命令
（`XMATIC_*` / `PlacePart` / `RegisterAction` / `after`）打桩，然后**真的** source 一遍
`edakit.tcl`，喂它一个队列请求，检查它写回的响应。

这样能提前发现：TCL 语法错、键缺失把轮询打挂、队列/响应的字段名对不上、
累积库合并的调用顺序错 —— 这些都是上机后最难查的那类问题。
"""

import shutil
import subprocess
from pathlib import Path

import pytest

TCLSH = shutil.which("tclsh") or shutil.which("tclsh8.6")
TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "edakit" / "install" / "templates"

pytestmark = pytest.mark.skipif(TCLSH is None, reason="本机没有 tclsh，跳过 TCL 检查")

PLUGIN = TEMPLATES / "edakit.tcl"
INIT = TEMPLATES / "edakitInit.tcl"
PROBE = TEMPLATES / "probe.tcl"


def test_cef_dock_reuse_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    driver = tmp_path / "cef.tcl"
    driver.write_text(r'''
proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
package provide orPrmWebComp 1.0
namespace eval ::orPrm {
    variable WDOCK_RIGHT 1
    variable WDALLOW_RIGHT 2
    variable WF_CEF 4
    variable loads 0
    variable creates 0
    variable failShow 0
    variable failDestroy 0
    proc CreateControlBar {args} { variable creates; incr creates }
    proc LoadResource {args} { variable loads; incr loads }
    proc SetTitle {args} {}
    proc IsContolBarVisible {id} {return [expr {![info exists ::hidden] || !$::hidden}]}
    proc ShowWidget {args} { variable failShow; if {$failShow} { set failShow 0; error stale } }
    proc DestroyWidget {args} { variable failDestroy; if {$failDestroy} { error cleanup } }
}
source [lindex $argv 0]
::edakit::openCefMall http://127.0.0.1:1000/embed
::edakit::openCefMall http://127.0.0.1:1000/embed
if {$::orPrm::loads != 1 || $::orPrm::creates != 1} { error "reuse reloaded" }
::edakit::openCefMall http://127.0.0.1:2000/embed
if {$::orPrm::loads != 2} { error "new URL not loaded" }
set ::orPrm::failShow 1
::edakit::openCefMall http://127.0.0.1:2000/embed
if {$::orPrm::creates != 2} { error "stale not rebuilt" }
set ::orPrm::failShow 1
set ::orPrm::failDestroy 1
if {![catch {::edakit::openCefMall http://127.0.0.1:2000/embed}]} { error "cleanup failure swallowed" }
if {$::orPrm::creates != 2 || ![info exists ::edakit::cefWidget]} { error "ownership lost" }
set ::orPrm::failShow 0
set ::orPrm::failDestroy 0
proc ::edakit::properties::serverUrl {} {return http://127.0.0.1:1234/}
proc ::edakit::schematicActive {} {return 0}
set before $::orPrm::creates
::edakit::properties::openPanel
set loads $::orPrm::loads
::edakit::properties::openPanel
if {$::orPrm::creates != $before+1 || $::orPrm::loads != $loads} {error "Property dock lost state"}
set ::hidden 1
::edakit::properties::openPanel
if {$::orPrm::loads != $loads+1} {error "Hidden CEF not reloaded on reopen"}
set ::hidden 0
set ::orPrm::failShow 1
::edakit::properties::openPanel
if {$::orPrm::creates != $before+2} {error "Property stale dock not recovered"}
set ::orPrm::failShow 1
set ::orPrm::failDestroy 1
if {![catch {::edakit::properties::openPanel}]} {error "Property cleanup failure swallowed"}
if {$::orPrm::creates != $before+2 || ![info exists ::edakit::properties::widget]} {error "Property dock ownership lost"}
puts PASS
''', encoding="ascii")
    result = subprocess.run([TCLSH, str(driver), str(PLUGIN)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout
    assert PLUGIN.read_bytes().isascii()

# 真方言（17.2）：<Lib> / <Package><Defn name=...>。插件在合并后按
# Package name 核对零件名（不匹配会导致 PlacePart 报 ORCAP-1687）。
PART_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<Lib xmlns:xsd="http://www.w3.org/2001/XMLSchema"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:noNamespaceSchemaLocation="olb.xsd">
  <Defn name="D:/cadence/project.olb"/>
  <Package>
    <Defn alphabeticNumbering="2" isHomogeneous="1" name="RP2040" pcbFootprint=""
          pcbLib="" refdesPrefix="U" timestamp="0" timezone="1"/>
  </Package>
</Lib>
"""

DRIVER = r"""
# ---- 参数先解析 (下面打桩要用) ----
set ::workdir    [lindex $argv 0]
set tmpl         [lindex $argv 1]
set appdata      [lindex $argv 2]
set fakeExe      [lindex $argv 3]
set ::withXmatic [lindex $argv 4]
set ::mode       [lindex $argv 5]

# ---- 打桩: 事件循环与对话框 ----
# `after` 记下「随光标放置」的挂起回调，driver 末尾统一执行。
set ::armScripts {}
set ::registeredActions {}
set ::insertedMenus {}
proc after {args} {
    if {[llength $args] == 2 && [string first "armClickPlace" [lindex $args 1]] >= 0} {
        lappend ::armScripts [lindex $args 1]
    }
}
proc tk_messageBox {args} {}

# ---- 打桩: Capture 的库转换命令 ----
if {$::withXmatic} {
    proc RegisterAction {args} { lappend ::registeredActions $args }
    proc InsertXMLMenu {args} { lappend ::insertedMenus $args }
    proc XMATIC_OLB2XML {olb xml} {
        # 模拟真实行为：XML2OLB 桩把「生成它的 XML 路径」写进 .olb；
        # 回读时把那几份 XML 原样拷回来（并集），这样插件里的
        # olbHasPart 零件名核对才能被真实地执行到。
        if {[file exists $olb]} {
            set fp [open $olb r]; set body [read $fp]; close $fp
            set found 0
            set out [open $xml w]; fconfigure $out -encoding utf-8
            foreach {- src} [regexp -all -inline {OLB-GENERATED-FROM ([^\r\n]+)} $body] {
                set src [string trim $src]
                if {[file exists $src]} {
                    set f2 [open $src r]; fconfigure $f2 -encoding utf-8
                    set data [read $f2]; close $f2
                    set data [regsub -all {</Lib>} $data ""]
                    puts -nonewline $out $data
                    set found 1
                }
            }
            puts $out "</Lib>"
            close $out
            if {$found} { return "_0_p_DboState" }
        }
        set fp [open $xml w]; fconfigure $fp -encoding utf-8
        puts $fp "<?xml version=\"1.0\"?>\n<CaptureLibrary>\n  <Part Name=\"OLD\"/>\n</CaptureLibrary>"
        close $fp
        "_0_p_DboState"
    }
    proc XMATIC_XML2OLB {xml olb} {
        set fp [open $olb w]; fconfigure $fp -encoding utf-8
        puts $fp "OLB-GENERATED-FROM $xml"
        close $fp
    }
    # 模拟 `exe olb-merge --base X --part Y --out Z`: 记下调用, 并把内容粘到 Z
    proc exec {args} {
        set base ""; set part ""; set out ""
        for {set i 0} {$i < [llength $args]} {incr i} {
            set a [lindex $args $i]
            switch -- $a {
                --base { incr i; set base [lindex $args $i] }
                --part { incr i; set part [lindex $args $i] }
                --out  { incr i; set out  [lindex $args $i] }
            }
        }
        set fp [open [file join $::workdir "merge_call.txt"] w]
        fconfigure $fp -encoding utf-8
        puts $fp "base=$base"; puts $fp "part=$part"; puts $fp "out=$out"
        close $fp
        set data ""
        if {$base ne "" && [file exists $base]} { set b [open $base r]; append data [read $b]; close $b }
        if {$part ne "" && [file exists $part]} { set p [open $part r]; append data [read $p]; close $p }
        set fo [open $out w]; fconfigure $fo -encoding utf-8; puts $fo $data; close $fo
    }
    proc PlacePartEx {args} { error "PlacePartEx must not be used on this installation" }
    proc capGetMostRecentSchFrameID {} { _recordCall cursor_steps.txt frame; return FRAME1 }
    proc DboTclHelper_sGetConstCharPtr {value} { return $value }
    namespace eval ::ui {}
    proc ::ui::SchematicActivate {frame} {
        _recordCall cursor_steps.txt activate $frame
        if {$::mode eq "activation-error"} { error "activation failed" }
    }
    proc UnSelectAll {} { _recordCall cursor_steps.txt unselect }
    proc ZoomRedraw {} { _recordCall cursor_steps.txt redraw }
    proc capGetIsSchematicEditingDisabled {} { return [expr {$::mode eq "read-only"}] }
    proc PlaceNew {args} {
        if {$::mode eq "cursor-error" || $::mode eq "defer-error"} { error "native cursor failed" }
        _recordCall cursor_steps.txt place
        _recordCall cursor_call.txt {*}$args
        if {$::mode eq "cursor-zero"} { return 0 }
        return 1
    }
    if {$::mode eq "no-cursor"} { rename PlaceNew {} }
    # 模拟放置: 记录参数
    proc PlacePart {args} {
        set fp [open [file join $::workdir "place_call.txt"] w]
        fconfigure $fp -encoding utf-8
        foreach a $args { puts $fp $a }
        close $fp
    }
    # 交互式放置链（真机 17.2 确认）：AddLib -> SelectByNameAndLib ->
    # MenuCommand 13958 -> PlacePartClickPlace。每个都记录到独立文件。
    proc _recordCall {file args} {
        set fp [open [file join $::workdir $file] a]
        fconfigure $fp -encoding utf-8
        foreach a $args { puts $fp $a }
        close $fp
    }
    proc PlacePartAddLib {args} { _recordCall addlib_call.txt {*}$args; return 1 }
    proc PlacePartGetLibIndex {args} { return 4 }
    proc PlacePartSelectLibIndex {args} { _recordCall libindex_call.txt {*}$args; return 1 }
    proc PlacePartSelectPartIndex {args} { _recordCall partindex_call.txt {*}$args; return 1 }
    proc PlacePartSelectPartByNameAndLib {args} { _recordCall select_call.txt {*}$args; return 1 }
    proc MenuCommand {args} { _recordCall menu_command.txt {*}$args; return 0 }
    proc PlacePartClickPlace {args} { _recordCall clickplace_call.txt {*}$args; return 1 }
    # 原理图是否活动：测试用全局开关 ::schemActive 控制（默认 1）
    set ::schemActive 1
    proc IsSchematicViewActive {} { return $::schemActive }
    # defer 模式在 source 之前就把原理图设为「非活动」
    if {$::mode eq "defer" || $::mode eq "defer-error"} { set ::schemActive 0 }
}

set ::env(LOCALAPPDATA) $appdata
set ::env(EDAKIT_EXE) $fakeExe
unset -nocomplain ::env(USERPROFILE)

# source 插件本身 —— 它会注册菜单并立刻轮询一次
source [file join $tmpl "edakit.tcl"]

# 菜单动作要能调用而不炸 (showProbe 会去调 tk_messageBox, 已打桩)
catch { ::edakit::showProbe }
catch { ::edakit::showLog }

# 可选：模拟「先切到原理图，再遇上下一次轮询」（须在 armClickPlace 回放之前）
if {[lindex $argv 5] eq "defer" || [lindex $argv 5] eq "defer-error"} {
    puts "PRE-MENU=[file exists [file join $::workdir menu_command.txt]]"
    puts "PRE-CLICK=[file exists [file join $::workdir clickplace_call.txt]]"
    set ::schemActive 1
    ::edakit::tryPendingPlace
    puts "PENDING-RUN"
}

# 执行挂起的「随光标」回调（armClickPlace）
foreach s $::armScripts { uplevel #0 $s }

::edakit::registerMenu
puts "MENU-COUNT=[llength $::insertedMenus]"
foreach action $::registeredActions {
    set callback [lindex $action 3]
    puts "CALLBACK=$callback:[llength [info commands $callback]]"
    if {[lindex $action 0] eq "EdaKitProbe"} { $callback testArg }
}
puts "ENABLED=[::edakit::menuTrue extraArg]"
puts "MENUS=$::insertedMenus"
puts "ACTIONS=$::registeredActions"
puts "QUEUE=[::edakit::locateQueueDir]"
puts "DONE"
"""


@pytest.fixture
def run_plugin(tmp_path):
    """把插件 source 一遍。req 里可用 @PART_XML@ / @PROJECT_OLB@ 占位真实路径。"""

    def _run(req_lines: str, *, with_xmatic: bool = True, mode: str = "") -> dict:
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        appdata = tmp_path / "appdata"
        qd = appdata / "edakit" / "queue"
        qd.mkdir(parents=True, exist_ok=True)

        part_xml = tmp_path / "C2040.olb.xml"
        part_xml.write_text(PART_XML, encoding="utf-8")
        project_olb = tmp_path / "project.olb"
        project_olb.write_text("OLD-OLB-BYTES", encoding="utf-8")  # 让 OLB2XML 分支被走到
        fake_exe = tmp_path / "edakit.exe"
        fake_exe.write_text("", encoding="utf-8")

        req = (
            req_lines.replace("@PART_XML@", str(part_xml))
            .replace("@PROJECT_OLB@", str(project_olb))
        )
        # 请求必须在 source 之前就位 —— 插件在 source 时就会 poll 一次
        (qd / "req_1.req").write_text(req, encoding="utf-8")

        driver = tmp_path / "driver.tcl"
        driver.write_text(DRIVER, encoding="utf-8")
        r = subprocess.run(
            [TCLSH, str(driver), str(work), str(TEMPLATES), str(appdata),
             str(fake_exe), "1" if with_xmatic else "0", mode],
            capture_output=True, text=True, timeout=120, encoding="utf-8",
        )
        return {
            "out": r.stdout or "", "err": r.stderr or "", "rc": r.returncode,
            "work": work, "queue": qd, "project_olb": project_olb,
            "part_xml": part_xml,
        }

    return _run


def _resp(res: dict, seq: str) -> dict:
    f = res["queue"] / f"resp_{seq}.resp"
    assert f.exists(), f"插件没写 resp_{seq}.resp（stdout={res['out']!r} stderr={res['err']!r}）"
    return dict(
        line.split("=", 1)
        for line in f.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


@pytest.mark.parametrize("path", [PLUGIN, INIT, PROBE], ids=lambda p: p.name)
def test_tcl_templates_are_syntactically_complete(path):
    # 不执行，只判语法完整性 —— 所以用 stdin 喂给 tclsh (它没有 -c 选项)
    script = (
        f'set fp [open {{{path}}} r]; fconfigure $fp -encoding utf-8; set s [read $fp]; '
        'close $fp; if {[info complete $s]} { puts OK } else { puts BAD; exit 1 }'
    )
    r = subprocess.run(
        [TCLSH], input=script, capture_output=True, text=True, timeout=60, encoding="utf-8"
    )
    assert r.stdout.strip() == "OK", f"{path.name} 语法不完整: {r.stdout} {r.stderr}"


def test_plugin_sources_and_registers_menu(run_plugin):
    res = run_plugin("seq=1\ncid=C1\nstage_only=1\n")
    assert res["rc"] == 0, res["err"]
    assert "DONE" in res["out"]
    assert "EdaKit top-level menu registered" in res["out"]
    assert "EdaKit Mall" in res["out"]
    assert "EdaKitEnabled" in res["out"]
    assert "MENU-COUNT=6" in res["out"]
    assert "CALLBACK=edakitMallLegacy:1" not in res["out"]
    assert "Diagnostics" in res["out"]
    assert "Legacy Viewer" not in res["out"]
    assert "ENABLED=true" in res["out"]
    assert "CALLBACK=edakitMall:1" in res["out"]
    assert "CALLBACK=edakitProbe:1" in res["out"]
    assert "started, polling queue" in res["out"]


def test_plugin_writes_heartbeat(run_plugin):
    res = run_plugin("seq=1\ncid=C1\nstage_only=1\n")
    hb = res["queue"] / "heartbeat.txt"
    assert hb.exists()
    assert "ts=" in hb.read_text(encoding="utf-8")


def test_stage_only_request_writes_response_and_consumes_request(run_plugin):
    res = run_plugin("seq=1\ncid=C2040\npart_name=RP2040\nstage_only=1\n")
    kv = _resp(res, "1")
    assert kv["ok"] == "1"
    assert kv["stage"] == "stage"
    assert "staged" in kv["message"]
    assert not (res["queue"] / "req_1.req").exists()


def test_full_place_request_runs_merge_and_place(run_plugin):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\n"
        "follow_cursor=0\nx_mil=500\ny_mil=500\nstage_only=0\n"
        "footprint=LQFN-56_L7.0-W7.0-P0.4-EP\n"
    )
    assert res["rc"] == 0, res["err"]
    kv = _resp(res, "1")
    assert kv["ok"] == "1", kv
    assert kv["stage"] == "place"
    assert "placed" in kv["message"]

    # 1) 走了 exe 合并: --base 是工程库回读出来的 XML, --part 是我们的元件 XML
    merge = (res["work"] / "merge_call.txt").read_text(encoding="utf-8")
    assert str(res["part_xml"]) in merge
    assert "C2040.base.xml" in merge          # OLB2XML 的产物
    assert "@" not in merge                   # 占位符都被替换成了真实路径
    # 2) 工程库被真的写回去了 (XML2OLB 桩)
    assert "OLB-GENERATED-FROM" in res["project_olb"].read_text(encoding="utf-8")
    # 3) PlacePart 收到元件名；封装名不出现在 PlacePart 里（它进的是属性/日志）
    place = (res["work"] / "place_call.txt").read_text(encoding="utf-8").splitlines()
    assert "RP2040" in place
    assert place[-1] == "FALSE"                # PlacePart 的最后一个参数
    assert "LQFN-56_L7.0-W7.0-P0.4-EP" not in place
    # Use an immutable snapshot; a fixed path remains cached as the first part in Capture.
    lib = place[2]
    assert Path(lib).name.startswith("place_"), lib
    assert Path(lib).exists()
    # 桩 .olb 记录的是它由哪份 XML 生成 —— 固定库在最后还经过一次
    # 「OLB2XML → XML2OLB」规范化（Capture 自写格式才会画对引脚），
    # 所以它由规范化产生的 lcsc_test.olb.norm.xml 生成。
    assert "lcsc_test.olb.norm.xml" in Path(lib).read_text(encoding="utf-8")

    # 封装名应该被记进日志 (stdout)
    assert "LQFN-56_L7.0-W7.0-P0.4-EP" in res["out"]


def test_cursor_request_uses_verified_placenew_chain(run_plugin):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\n"
        "follow_cursor=1\nstage_only=0\n"
    )
    kv = _resp(res, "1")
    assert kv["ok"] == "1", kv
    assert kv["message"].startswith("armed:")
    work = res["work"]
    assert not (work / "place_call.txt").exists()
    assert not (work / "menu_command.txt").exists()
    args = (work / "cursor_call.txt").read_text().splitlines()
    assert Path(args[0]).name.startswith("place_")
    assert args[1:] == ["RP2040", "0"]
    steps = (work / "cursor_steps.txt").read_text().splitlines()
    assert steps == ["frame", "activate", "FRAME1", "unselect", "redraw", "place"]


@pytest.mark.parametrize("mode", ["no-cursor", "cursor-error"])
def test_cursor_failure_never_falls_back_to_fixed_placement(run_plugin, mode):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\nfollow_cursor=1\n",
        mode=mode,
    )
    kv = _resp(res, "1")
    assert kv["ok"] == "0", kv
    assert not (res["work"] / "place_call.txt").exists()



def test_place_deferred_until_schematic_is_active(run_plugin):
    """内嵌商城页签处于活动时（IsSchematicViewActive=0），PlacePart 会失败，
    所以放置必须挂起，等切回原理图（下一次轮询）再执行。"""
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\n"
        "follow_cursor=1\nstage_only=0\n",
        mode="defer",
    )
    assert res["rc"] == 0, res["err"]
    kv = _resp(res, "1")
    assert kv["ok"] == "1"
    assert kv["message"].startswith("armed:")
    work = res["work"]
    assert "PRE-MENU=0" in res["out"]
    assert "PRE-CLICK=0" in res["out"]
    assert "PENDING-RUN" in res["out"]
    # 切回原理图后的那次轮询完成了直接放置
    assert (work / "cursor_call.txt").exists()


def test_missing_xmatic_is_reported_not_silent(run_plugin):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\nolb_xml=@PART_XML@\n"
        "project_olb=@PROJECT_OLB@\nstage_only=0\n",
        with_xmatic=False,
    )
    kv = _resp(res, "1")
    assert kv["ok"] == "0"
    assert kv["stage"] == "check-xmatic"
    assert "XMATIC_XML2OLB" in kv["message"]


def test_missing_cid_reported(run_plugin):
    res = run_plugin("seq=1\npart_name=X\nstage_only=0\n")
    kv = _resp(res, "1")
    assert kv["ok"] == "0"
    assert "cid" in kv["message"]


def test_missing_keys_do_not_crash_polling(run_plugin):
    """缺键不能把整轮轮询打挂 —— 这正是 kvGet 存在的原因。"""
    res = run_plugin("seq=1\ncid=C1\n")
    assert res["rc"] == 0, res["err"]
    assert (res["queue"] / "resp_1.resp").exists()


# ---------------------------------------------------------------------------
#  probe.tcl 的行为测试
#
#  这份脚本是决定「项目能不能往下走」的关键一测，所以它自己不能有 bug。
#  实际踩过两个 Tcl 坑，都在这里钉住：
#    ① 双引号里的 [可以] 会被当成命令替换去执行 → invalid command name
#    ② set seen {} 之后又 set seen(k) → variable isn't array
# ---------------------------------------------------------------------------

def _run_probe(stub_commands: bool) -> subprocess.CompletedProcess:
    driver = ""
    if stub_commands:
        driver = (
            "proc XMATIC_XML2OLB {args} {}\n"
            "proc XMATIC_OLB2XML {args} {}\n"
            "proc PlacePart {args} {}\n"
        )
    driver += f'source {str(PROBE)!r}\n'.replace("'", '"')
    return subprocess.run(
        [TCLSH], input=driver, capture_output=True, text=True,
        timeout=120, encoding="utf-8",
    )


def test_probe_runs_without_capture_and_gives_verdict():
    r = _run_probe(stub_commands=False)
    assert r.returncode == 0, r.stderr
    assert "capability probe" in r.stdout
    assert "PlacePartEx" in r.stdout
    assert "PlaceNew" in r.stdout
    assert "InsertXMLMenu" in r.stdout
    assert "MISSING" in r.stdout
    # 关键：结论段必须真的打出来（踩过 [可以] 被当命令执行的坑，会在这里断掉）
    assert "verdict" in r.stdout
    assert "[BLOCKED]" in r.stdout
    # 不能有 Tcl 运行时错误漏出来
    assert "invalid command name" not in r.stderr
    assert "isn't array" not in r.stderr


def test_probe_reports_full_support_when_commands_exist():
    r = _run_probe(stub_commands=True)
    assert r.returncode == 0, r.stderr
    assert "XMATIC_XML2OLB             OK" in r.stdout
    assert "PlacePart: OK" in r.stdout
    assert "[READY]" in r.stdout
    # 有 XMATIC 时不该跑「尝试加载 DLL」那段
    assert "trying to load" not in r.stdout


def test_probe_lists_searched_dirs_when_nothing_found():
    r = _run_probe(stub_commands=False)
    assert "directories checked" in r.stdout
    # 去重逻辑不能把 base 变量写成标量数组（踩过）
    assert "variable isn't array" not in r.stderr


# ---------------------------------------------------------------------------
#  ★ 最关键的一条：所有 .tcl 模板必须是纯 ASCII
#
#  Capture 的 Tcl 按系统代码页（中文 Windows 上是 cp936/GBK）读文件。
#  UTF-8 的中文字节被当 GBK 解码后，尾字节可能正好是 0x7B '{'、0x7D '}'、
#  0x5C '\' —— 解析结构被悄悄改坏，最后报 "missing close-brace"。
#  2026-10-19 在用户的 Capture 17.2 上真实踩到过，整个插件都加载不了。
# ---------------------------------------------------------------------------

def test_all_tcl_templates_are_pure_ascii():
    bad = []
    for path in sorted(TEMPLATES.glob("*.tcl")):
        raw = path.read_bytes()
        offenders = [(i, b) for i, b in enumerate(raw) if b > 127]
        if offenders:
            bad.append((path.name, len(offenders), offenders[:3]))
    assert not bad, (
        "这些 .tcl 模板含非 ASCII 字节，在中文 Windows 的 Capture 里会解析失败"
        "（GBK 尾字节可能变成 { } \\）：" + repr(bad)
    )


def test_gbk_decoding_of_templates_stays_brace_balanced():
    """更贴近真实：按 GBK 解码后，花括号数必须与字节里的一致。"""
    for path in sorted(TEMPLATES.glob("*.tcl")):
        raw = path.read_bytes()
        as_gbk = raw.decode("gbk", errors="replace")
        assert as_gbk.count("{") == raw.count(b"{"), f"{path.name}: GBK 解码后多出了左花括号"
        assert as_gbk.count("}") == raw.count(b"}"), f"{path.name}: GBK 解码后多出了右花括号"


def test_probe_reports_capture_seventeen_paths():
    """探测脚本要能报出 CDSROOT —— 用户的机器是 D:/Cadence/SPB_17.2。"""
    r = subprocess.run(
        [TCLSH], input=f'set ::env(CDSROOT) "D:/Cadence/SPB_17.2"\nsource "{PROBE.as_posix()}"\n',
        capture_output=True, text=True, timeout=60, encoding="utf-8",
    )
    assert "CDSROOT" in r.stdout
    assert "SPB_17.2" in r.stdout


# ---------------------------------------------------------------------------
#  diag_olb2xml.tcl —— B2 卡住时的诊断脚本
# ---------------------------------------------------------------------------

DIAG = TEMPLATES / "diag_olb2xml.tcl"


def test_diag_is_pure_ascii_and_complete():
    raw = DIAG.read_bytes()
    assert all(b < 128 for b in raw), "diag_olb2xml.tcl 含非 ASCII 字节（GBK 下会解析崩）"
    script = (
        f'set fp [open {{{DIAG}}} r]; fconfigure $fp -encoding utf-8; set s [read $fp]; '
        'close $fp; if {[info complete $s]} { puts OK } else { puts BAD }'
    )
    r = subprocess.run([TCLSH], input=script, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "OK", r.stderr


def _run_diag(stub: str, olb: Path, xml: Path) -> subprocess.CompletedProcess:
    driver = stub + "\n"
    driver += f'set lcsc_olb "{olb}"\n'.replace("\\", "/")
    driver += f'set lcsc_xml "{xml}"\n'.replace("\\", "/")
    driver += f'source "{str(DIAG).replace(chr(92), "/")}"\n'
    return subprocess.run([TCLSH], input=driver, capture_output=True, text=True, timeout=120)


def test_diag_reports_missing_command(tmp_path):
    r = _run_diag("", tmp_path / "a.olb", tmp_path / "a.xml")
    assert "XMATIC_OLB2XML is NOT defined" in r.stdout


def test_diag_reports_missing_input(tmp_path):
    r = _run_diag("proc XMATIC_OLB2XML {a b} {}", tmp_path / "nope.olb", tmp_path / "b.xml")
    assert "input file does not exist" in r.stdout
    assert "Stopped" in r.stdout


def test_diag_detects_silent_no_output(tmp_path):
    """命令回了 DboState 但什么都没写 —— 这正是用户遇到的情况。"""
    olb = tmp_path / "ref.olb"
    olb.write_bytes(b"x" * 40)
    xml = tmp_path / "out" / "ref.xml"
    r = _run_diag('proc XMATIC_OLB2XML {a b} { return "_0_p_DboState" }', olb, xml)
    assert "returned: _0_p_DboState" in r.stdout
    assert "no output file" in r.stdout
    # 顺带把输出目录建好了，用户可以直接重试
    assert (tmp_path / "out").is_dir()


def test_diag_succeeds_when_file_is_written(tmp_path):
    olb = tmp_path / "ref.olb"
    olb.write_bytes(b"x" * 40)
    xml = tmp_path / "out" / "ref.xml"
    stub = (
        'proc XMATIC_OLB2XML {a b} { set fp [open $b w]; '
        'puts $fp "<CaptureLibrary><Part Name=\\"REF\\"/>"; close $fp; return "_0_p_DboState" }'
    )
    r = _run_diag(stub, olb, xml)
    assert "output written" in r.stdout
    assert xml.exists()


def test_deferred_failure_updates_response(run_plugin):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\nfollow_cursor=1\n",
        mode="defer-error",
    )
    reply = _resp(res, "1")
    assert reply["ok"] == "0", reply
    assert reply["stage"] == "place"
    assert "native cursor failed" in reply["message"]


@pytest.mark.parametrize("mode", ["activation-error", "read-only"])
def test_cursor_preconditions_prevent_placement(run_plugin, mode):
    res = run_plugin(
        "seq=1\ncid=C2040\npart_name=RP2040\n"
        "olb_xml=@PART_XML@\nproject_olb=@PROJECT_OLB@\nfollow_cursor=1\n",
        mode=mode,
    )
    assert _resp(res, "1")["ok"] == "0"
    assert not (res["work"] / "cursor_call.txt").exists()
    assert not (res["work"] / "place_call.txt").exists()

def test_cursor_placement_chain_is_independent_of_storefront():
    source = PLUGIN.read_text(encoding='ascii')
    assert 'openMallExternal' not in source
    assert 'MallBrowser' not in source
    assert 'cursor CALL PlaceNew' in source
    assert 'OpenURL $page "EdaKit Mall"' in source


def test_live_service_is_reused_without_deleting_discovery(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    driver = tmp_path / 'live-server.tcl'
    driver.write_text(r'''
proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
source [lindex $argv 0]
proc accepted {args} {}
set listener [socket -server accepted -myaddr 127.0.0.1 0]
set port [lindex [fconfigure $listener -sockname] 2]
set url "http://127.0.0.1:$port/"
set f [open [::edakit::urlFile] w]; puts $f $url; close $f
proc ::edakit::locateExe {} {return dummy.exe}
rename exec originalExec
proc exec {args} {error "Unexpected service relaunch"}
if {![::edakit::serverAlive $url]} {error "Live socket misidentified as dead"}
if {[::edakit::ensureServer] ne $url} {error "First reuse failed"}
if {[::edakit::ensureServer] ne $url} {error "Reopen reuse failed"}
if {![file exists [::edakit::urlFile]]} {error "Live discovery deleted"}
close $listener
if {[::edakit::serverAlive $url]} {error "Closed socket reported live"}
if {[llength [info commands edakitSelectedProperties]]} {error "Removed entry remains"}
puts PASS
''', encoding='ascii')
    result = subprocess.run([TCLSH, str(driver), str(PLUGIN)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS' in result.stdout


def test_property_startup_is_async_and_deduplicated(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    driver = tmp_path / 'async-open.tcl'
    driver.write_text(r'''
proc after {args} {if {[llength $args] == 1} {error "Blocking UI sleep"};lappend ::callbacks $args}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
source [lindex $argv 0]
set ::callbacks {};set ::launches 0;set ::shown 0;set ::ready "";set ::messages 0
proc ::edakit::schematicActive {} {return 0}
proc ::edakit::locateExe {} {return dummy.exe}
proc ::edakit::properties::serverUrl {} {return $::ready}
proc ::edakit::properties::showPanel {url scope} {incr ::shown}
proc ::edakit::showText {args} {incr ::messages}
rename exec originalExec
proc exec {args} {incr ::launches}
::edakit::properties::openPanel
::edakit::properties::openPanel
if {$::launches != 1 || [llength $::callbacks] != 1} {error "Repeated click launched duplicate"}
::edakit::properties::waitForServer design
if {[llength $::callbacks] != 2} {error "No async retry"}
set ::ready http://127.0.0.1:1234/
::edakit::properties::waitForServer design
::edakit::properties::openPanel
if {$::shown != 2 || $::launches != 1} {error "Ready service not reused"}
set ::ready ""; set ::edakit::properties::opening 1;set ::edakit::properties::openDeadline 0
::edakit::properties::waitForServer design
if {$::edakit::properties::opening || $::messages != 1} {error "Timeout did not release retry guard"}
puts PASS
''', encoding='ascii')
    result = subprocess.run([TCLSH, str(driver), str(PLUGIN)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS' in result.stdout

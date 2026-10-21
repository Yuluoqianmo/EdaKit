"""部署测试 —— 在假 Cadence 安装树上验证拷贝与路径探测。"""

from pathlib import Path

import pytest

# 注意: 必须 import 模块本身。`from edakit.install import deploy` 拿到的是
# install/__init__.py 里导出的 deploy **函数** (同名遮蔽)。
import importlib
import argparse
import sys

deploy_mod = importlib.import_module("edakit.install.deploy")


def test_cli_deploy_records_windowed_executable(tmp_path, monkeypatch):
    from edakit.cli import cmd_deploy

    gui = tmp_path / "edakit.exe"
    gui.write_bytes(b"test")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "edakit-cli.exe"))
    monkeypatch.setattr(deploy_mod, "deploy", lambda **kwargs: None)
    assert cmd_deploy(argparse.Namespace(cadence_root=None, dry_run=False, no_allegro=True)) == 0
    assert (tmp_path / "edakit/exe_path.txt").read_text(encoding="utf-8") == str(gui)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("CDSROOT", raising=False)
    monkeypatch.delenv("CDS_INST_DIR", raising=False)


def _fake_spb(root: Path) -> Path:
    """造一个 <root>/tools/capture/tclscripts 结构。"""
    tcl = root / "tools" / "capture" / "tclscripts"
    tcl.mkdir(parents=True)
    return tcl


def test_find_capture_tcl_root_explicit(tmp_path):
    spb = tmp_path / "SPB_17.4"
    tcl = _fake_spb(spb)
    assert deploy_mod.find_capture_tcl_root(str(spb)) == tcl


def test_find_capture_tcl_root_not_found(tmp_path):
    from edakit.errors import DeployError

    with pytest.raises(DeployError):
        deploy_mod.find_capture_tcl_root(str(tmp_path / "nope"))


def test_deploy_copies_templates(tmp_path, capsys):
    spb = tmp_path / "SPB_17.4"
    _fake_spb(spb)
    target = deploy_mod.deploy(str(spb), config_allegro=False)
    assert target.is_dir()
    # 主逻辑在子目录，入口在 capAutoLoad 根目录（Capture 只扫根目录）
    assert (target / "edakit.tcl").is_file()
    init = target.parent / "edakitInit.tcl"
    assert init.is_file()
    assert not (target / "edakitInit.tcl").exists()
    # 模板内容确实拷进去了
    assert "namespace eval edakit" in (target / "edakit.tcl").read_text(encoding="utf-8")
    assert "edakit" in init.read_text(encoding="utf-8")


def test_deploy_dry_run_writes_nothing(tmp_path):
    spb = tmp_path / "SPB_17.4"
    _fake_spb(spb)
    target = deploy_mod.deploy(str(spb), dry_run=True, config_allegro=False)
    assert not target.exists()


def test_undeploy_removes_plugin_dir(tmp_path):
    spb = tmp_path / "SPB_17.4"
    _fake_spb(spb)
    target = deploy_mod.deploy(str(spb), config_allegro=False)
    assert target.exists()
    deploy_mod.undeploy(str(spb))
    assert not target.exists()
    assert not (target.parent / "edakitInit.tcl").exists()


def test_tcl_template_exposes_menu_and_polling():
    tcl = (
        Path(deploy_mod.__file__).parent / "templates" / "edakit.tcl"
    ).read_text(encoding="utf-8")
    assert "RegisterAction" in tcl
    assert "XMATIC_XML2OLB" in tcl
    assert "XMATIC_OLB2XML" in tcl
    assert "PlacePart" in tcl
    assert "after $pollMs" in tcl          # 轮询
    # 菜单注册必须走 Cadence 自己的 hook（capAppLaunchMenu.tcl 的写法）：
    # 纯字符串 "POPL"/"Schematic" 会被当成 proc 名，永远不触发。
    assert "InsertXMLMenu" in tcl
    assert 'list "EdaKit"' in tcl
    assert "AddAccessoryMenu" not in tcl
    assert "olb-merge" in tcl              # 调用 exe 合并库
    # 键缺失不能把轮询打挂
    assert "proc kvGet" in tcl


# ---------------------------------------------------------------------------
#  显式 --cadence-root 必须严格
#
#  用户机器上 D:\Cadence\SPB_17.2 是真实存在的。如果 find_capture_tcl_root
#  在「指定的路径不存在」时偷偷退回扫别的安装，就会装到一个他没预期的版本里，
#  很难排查。这两条测试锁死这个行为。
# ---------------------------------------------------------------------------

def test_explicit_root_is_strict_even_if_other_installs_exist(tmp_path, monkeypatch):
    from edakit.errors import DeployError

    # 造一个「别的盘上有的」安装
    real = tmp_path / "other" / "Cadence" / "SPB_17.2"
    (real / "tools" / "capture" / "tclscripts").mkdir(parents=True)
    monkeypatch.setattr(deploy_mod, "DRIVES", (str(tmp_path / "other"),))
    monkeypatch.delenv("CDSROOT", raising=False)
    monkeypatch.delenv("CDS_INST_DIR", raising=False)

    # 指定一个不存在的根 → 必须报错，不能悄悄用上面那个
    with pytest.raises(DeployError) as e:
        deploy_mod.find_capture_tcl_root(str(tmp_path / "nope"))
    assert "nope" in str(e.value)


def test_auto_discovery_scans_drive_cadence_dir(tmp_path, monkeypatch):
    """不给 root 时，要能在 <盘>:\\Cadence\\<任意版本> 下自动找到安装。"""
    spb = tmp_path / "vol" / "Cadence" / "SPB_17.2"
    tcl = spb / "tools" / "capture" / "tclscripts"
    tcl.mkdir(parents=True)

    monkeypatch.setattr(deploy_mod, "DRIVES", (str(tmp_path / "vol"),))
    monkeypatch.delenv("CDSROOT", raising=False)
    monkeypatch.delenv("CDS_INST_DIR", raising=False)
    monkeypatch.delenv("CONCEPTHDL_CDS_ROOT", raising=False)

    assert deploy_mod.find_capture_tcl_root() == tcl


def test_auto_discovery_finds_unknown_version_folder(tmp_path, monkeypatch):
    """版本号不在已知列表里也要找得到 —— 靠扫 Cadence 目录下的子目录兜底。"""
    spb = tmp_path / "vol" / "Cadence" / "SPB_99.9"
    tcl = spb / "tools" / "capture" / "tclscripts"
    tcl.mkdir(parents=True)

    monkeypatch.setattr(deploy_mod, "DRIVES", (str(tmp_path / "vol"),))
    monkeypatch.delenv("CDSROOT", raising=False)
    monkeypatch.delenv("CDS_INST_DIR", raising=False)
    monkeypatch.delenv("CONCEPTHDL_CDS_ROOT", raising=False)

    assert deploy_mod.find_capture_tcl_root() == tcl


def test_deploy_disables_only_known_legacy_startup_scripts(tmp_path):
    spb = tmp_path / "SPB_17.2"
    auto = _fake_spb(spb) / "capAutoLoad"
    legacy = auto / "lcsc2cadence"
    legacy.mkdir(parents=True)
    old_init = auto / "lcsc2cadenceInit.tcl"
    old_main = legacy / "lcsc2cadence.tcl"
    old_init.write_text("legacy init")
    old_main.write_text("legacy main")
    unrelated = auto / "otherPlugin.tcl"
    unrelated.write_text("keep")
    deploy_mod.deploy(str(spb), config_allegro=False)
    assert not old_init.exists()
    assert not old_main.exists()
    assert old_init.with_suffix(".tcl.disabled").read_text() == "legacy init"
    assert old_main.with_suffix(".tcl.disabled").read_text() == "legacy main"
    assert unrelated.read_text() == "keep"
    deploy_mod.deploy(str(spb), config_allegro=False)

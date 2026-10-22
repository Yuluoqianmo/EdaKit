"""命令行入口。

子命令:
    mall          旧命令兼容，仅启动内嵌商城服务
    serve         只起本地服务，不开浏览器 (调试用)
    search        命令行搜立创商城 (不依赖界面)
    stage         把一个元件落盘 (符号 XML / 封装 SKILL / STEP / 3D 映射)
    olb-merge     把元件符号库 XML 合并进工程库 XML (Capture TCL 回调)
    allegro-env   配置 / 查看 / 移除 Allegro 环境变量
    fetch         只取数，落 component.json
    parse         解析本地 component.json，打印摘要 (校准解析器用)
    build         完整流水线: 取数 + 解析 + 生成全部中间件
    learn-schema  从参考 OLB 回读 Capture 库 XML schema
    probe         生成 Cadence 能力探测脚本 (在 Capture 命令窗口 source)
    deploy        把插件装进 Cadence 安装树 (+ 可选配 Allegro env)
    undeploy      卸载插件
    status        查看配置、队列、Capture 是否在线

典型用法:
    edakit mall                              # 打开商城界面
    edakit stage --lcsc C2040                # 命令行落盘一个元件
    edakit deploy                            # 装插件并配环境
    edakit build --lcsc C2040 --out .\\out   # 旧式一次性出全套
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .easyeda.parse import parse_component
from .errors import LcscError
from .fetch import Fetcher
from .footprint.skill import generate_skill
from .symbol.olb_xml import generate_olb_xml, load_schema_profile
from .symbol.tcl import generate_capture_run_tcl, generate_place_tcl
from .threed.mapping import build_map_xml, calibrate
from .threed.step import StepFetcher
from .symbol.naming import capture_part_name


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 商城 / 服务
# --------------------------------------------------------------------------- #
def cmd_mall(args: argparse.Namespace) -> int:
    from .server.app import serve_forever
    from .server.lifecycle import CaptureSessions, managed_server_lock, remove_owned_url, publish_owned_url
    from .bridge.queue import app_dir
    from contextlib import nullcontext
    import time

    from .runtime import configure_logging
    configure_logging()
    directory = app_dir()
    from .config import Config
    from .install import capture_ini
    cfg = Config.load()
    if cfg.footprint_lib:
        try:
            capture_ini.configure(cfg.footprint_lib, cadence_root=cfg.cadence_root)
        except (OSError, ValueError) as error:
            import logging
            logging.getLogger(__name__).warning('Capture footprint search path sync failed: %s', error)
    managed = bool(getattr(args, "capture_pid", 0))
    with managed_server_lock(directory) if managed else nullcontext(True) as acquired:
        if not acquired:
            print("Capture service already running; duplicate launch exits.")
            return 0
        sessions = CaptureSessions(directory / "capture_hosts") if managed else None
        try:
            if sessions and not (directory / "capture_hosts" / f"{args.capture_pid}.owner").is_file():
                raise RuntimeError("Capture host registration missing; cannot start owned service")
            httpd, url = serve_forever(port=args.port, verbose=args.verbose)
            print(f"内嵌商城服务已启动: {url}embed")
            print("Capture-managed service" if managed else "Manual service: Ctrl+C to stop")
            try:
                while not sessions or not sessions.should_stop():
                    from .bridge.sessions import maintain_queue
                    maintain_queue()
                    if managed:
                        try:
                            publish_owned_url(directory, url)
                        except OSError:
                            import logging
                            logging.getLogger(__name__).warning("Service discovery could not be repaired; retrying", exc_info=True)
                    time.sleep(1)
                print("All registered Capture processes exited; service stopping.")
            except KeyboardInterrupt:
                print("\n正在退出…")
            finally:
                httpd.shutdown()
                httpd.server_close()
                remove_owned_url(directory / "url.txt", url)
        finally:
            if sessions:
                sessions.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    args.no_browser = True
    return cmd_mall(args)


def cmd_search(args: argparse.Namespace) -> int:
    from .catalog import MallClient

    res = MallClient().search_keyword(args.keyword, page=1, page_size=args.size)
    print(f"关键词 {args.keyword!r} —— 命中 {res.total} 项，显示前 {len(res.parts)} 项")
    for p in res.parts:
        price = p.price_str
        stock = f"库存 {p.stock}" if p.stock else ""
        print(f"  {p.cid:<8} {p.model:<28} {p.brand:<14} {p.package:<20} {price:<14} {stock}")
        if p.description:
            print(f"           {p.description[:80]}")
    return 0


# --------------------------------------------------------------------------- #
# 落盘 / 桥接
# --------------------------------------------------------------------------- #
def cmd_stage(args: argparse.Namespace) -> int:
    from .bridge.queue import Config
    from .pipeline import fetch_component, stage_component

    cfg = Config.load()
    if args.footprint_lib:
        cfg.footprint_lib = args.footprint_lib
    if args.calib:
        cfg.calib = args.calib
    if args.schema:
        cfg.schema_profile = args.schema

    print(f"取数 {args.lcsc.upper()} …")
    comp = fetch_component(args.lcsc)
    st = stage_component(comp, cfg, download_step=not args.no_step)

    print(f"\n元件 {comp.title} ({comp.cid})")
    print(f"  封装名        {st.footprint_name}")
    print(f"  符号 XML      {st.symbol_xml or '(无)'}")
    print(f"  封装 SKILL    {st.footprint_skill or '(无)'}")
    print(f"  3D STEP       {st.step or '(无)'}")
    print(f"  3D 映射       {st.map_xml or '(无)'}")
    print(f"  工作目录      {st.workdir}")
    for w in st.warnings:
        print(f"  · {w}")
    return 0


def cmd_olb_merge(args: argparse.Namespace) -> int:
    from .symbol.olb import merge_files

    n = merge_files(args.base or "", args.part, args.out)
    print(f"合并完成: {args.out}（库内共 {n} 个元件）")
    return 0


def cmd_place(args: argparse.Namespace) -> int:
    """命令行直接投一个放置请求 (等价于界面里点「放置」)。"""
    from .bridge.queue import Config, capture_alive
    from .runtime import configure_logging
    configure_logging()
    from .pipeline import fetch_component, stage_component

    cfg = Config.load()
    if args.footprint_lib:
        cfg.footprint_lib = args.footprint_lib
    if args.follow_cursor:
        cfg.place_mode = "cursor"

    comp = fetch_component(args.lcsc)
    from .services.placement import PlacementService, PreparationOptions
    result = PlacementService(stage_component).submit(comp, cfg,
        PreparationOptions(capture_only=False, download_step=not args.no_step),
        target=getattr(args, "session", ""), stage_only=args.stage_only,
        follow_cursor=args.follow_cursor, x=args.x, y=args.y)
    print(f"已投递放置请求 seq={result['seq']}")
    print(f"Capture 在线: {'是' if capture_alive() else '否'}")
    print("在 Capture 里选择位置即可落位。可用 `edakit place-status` 查询结果。")
    return 0


def cmd_place_status(args: argparse.Namespace) -> int:
    from .bridge.queue import read_response

    res = read_response(args.seq)
    if res is None:
        print("尚未有结果（Capture 未在线或还没处理）。")
        return 1
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 2


# --------------------------------------------------------------------------- #
# Allegro 环境
# --------------------------------------------------------------------------- #
def cmd_allegro_env(args: argparse.Namespace) -> int:
    from .install import allegro_env
    from .config import Config

    if args.show:
        allegro_env.show()
        return 0
    if args.remove:
        allegro_env.unconfigure()
        return 0
    lib = args.lib
    if not lib:
        from .bridge.queue import Config

        lib = Config.load().footprint_lib
    if not lib:
        print("需要 --lib <封装库目录>（或先在配置里设好 footprint_lib）。", file=sys.stderr)
        return 2
    allegro_env.configure(lib, dry_run=args.dry_run, step_dir=Config.load().effective_step_lib)
    return 0


# --------------------------------------------------------------------------- #
# 取数 / 解析 / 旧式构建
# --------------------------------------------------------------------------- #
def cmd_fetch(args: argparse.Namespace) -> int:
    fetcher = Fetcher()
    result = fetcher.get_component(args.lcsc)
    out = Path(args.out) / f"{args.lcsc.upper()}.json"
    _write(out, json.dumps(result, ensure_ascii=False, indent=2))
    print(f"已保存 {out}")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    comp = parse_component(args.lcsc, payload)
    print(f"元件: {comp.title}  ({comp.cid})")
    if comp.symbol:
        s = comp.symbol
        print(f"  符号: {len(s.primitives)} 图元, {len(s.pins)} 引脚, "
              f"{s.width_mm:.2f}x{s.height_mm:.2f} mm, 前缀 {s.prefix!r}")
        for pin in s.pins[:5]:
            print(f"    引脚 {pin.number:>4} {pin.name:<10} @({pin.x_mm:.2f},{pin.y_mm:.2f}) "
                  f"{pin.electrical_type}")
    if comp.footprint:
        f = comp.footprint
        print(f"  封装: {len(f.pads)} 焊盘, {len(f.padstacks)} padstack, "
              f"{len(f.lines)} 丝印段")
    if comp.model3d:
        m = comp.model3d
        print(f"  3D: uuid={m.uuid[:12]}… origin=({m.origin_mm[0]:.2f},{m.origin_mm[1]:.2f}) "
              f"z={m.z_mm:.2f} rot={m.rotation_deg}")
    if args.dump:
        Path(args.dump).write_text(
            json.dumps(_summary(comp), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  dump → {args.dump}")
    return 0


def _summary(comp) -> dict:
    out: dict = {"cid": comp.cid, "title": comp.title}
    if comp.symbol:
        out["symbol"] = {
            "pins": [vars(p) for p in comp.symbol.pins],
            "width_mm": comp.symbol.width_mm,
            "height_mm": comp.symbol.height_mm,
        }
    if comp.footprint:
        out["footprint"] = {
            "pads": [vars(p) for p in comp.footprint.pads],
            "padstacks": [
                {"name": ps.name, "drill_mm": ps.drill_mm,
                 "layers": [vars(lay) for lay in ps.layers]}
                for ps in comp.footprint.padstacks
            ],
        }
    if comp.model3d:
        out["model3d"] = vars(comp.model3d)
    return out


def cmd_build(args: argparse.Namespace) -> int:
    from .services.export import ExportService
    comp = parse_component(args.lcsc.upper(), json.loads(Path(args.offline_json).read_text(encoding="utf-8"))) if args.offline_json else None
    if comp is None:
        from .pipeline import fetch_component
        comp = fetch_component(args.lcsc)
    if comp.symbol is None and comp.footprint is None:
        print("错误: 既无符号也无封装，无法生成。", file=sys.stderr)
        return 2
    result = ExportService().bundle(comp, Path(args.out), calib=args.calib,
                                   download_step=args.download_step, dll=args.dll or "")
    print(f"完成。产物在 {result.workdir}")
    for warning in result.warnings:
        print(warning)
    return 0


def _read_text_auto(path: Path) -> str:
    """读文本，自动识别编码。

    XMATIC_OLB2XML 吐出来的编码不固定（不同版本有 UTF-8、UTF-16、ANSI 的），
    硬按 UTF-8 读会把中文/属性弄成乱码，进而让结构清单失真。
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def cmd_learn_schema(args: argparse.Namespace) -> int:
    """从参考 OLB 回读 schema。需要先在本机 Capture 里用 XMATIC_OLB2XML 转出 XML。

    产出两个文件：
      profile.json      —— 尽量往 DEFAULT_PROFILE 的键上套的 profile（能直接喂给 --schema）
      schema-report.txt —— 参考库 XML 的**完整结构清单**（元素/属性/样例值），
                           用来把生成器改对。这份清单才是关键。
    """
    from .symbol.olb_xml import (
        analyze_olb_xml,
        build_profile_from_olb_xml,
        render_schema_report,
    )

    if not args.roundtrip_xml:
        print("需要 --roundtrip-xml —— 也就是先用 XMATIC_OLB2XML 把参考 .olb 转出来的那份 XML。")
        print()
        print("怎么拿这份 XML：")
        print("  1) 在 OrCAD Capture 里手建一个参考元件（哪怕只有一个矩形 + 两个引脚），")
        print("     存成 ref.olb")
        print("  2) 在 Capture 的命令窗口敲：")
        print('       load "<DboTclWriteBasic.dll>" DboTclWriteBasic')
        if args.olb:
            print(f'       XMATIC_OLB2XML "{args.olb}" "ref.xml"')
        else:
            print('       XMATIC_OLB2XML "<ref.olb 的全路径>" "ref.xml"')
        print("  3) 回到命令行：")
        print("       edakit learn-schema --roundtrip-xml ref.xml --out ./schema")
        return 1

    xml_path = Path(args.roundtrip_xml)
    if not xml_path.exists():
        print(f"找不到这个文件：{xml_path}", file=sys.stderr)
        print()
        print("说明 Capture 里的 XMATIC_OLB2XML 没有真正写出 XML。常见原因有三个：")
        print(f"  1. 输入的 .olb 不存在（先确认 {args.olb or '<ref.olb>'} 这个文件在）")
        print(f"  2. 输出目录不存在（{xml_path.parent} —— 目录必须先建好，命令不会自动创建）")
        print("  3. 命令虽然回了句 _xxxx_p_DboState，但其实没成功（它不一定抛错）")
        print()
        print("用 dist\\diag_olb2xml.tcl 一步一步查：")
        print('  set lcsc_olb "D:/cadence/ref.olb"')
        print('  set lcsc_xml "D:/cadence/ref.xml"')
        print('  source "C:/.../dist/diag_olb2xml.tcl"')
        print()
        # 顺手在附近找找有没有 XML —— 也许它写到了别的目录
        found: list[Path] = []
        for d in (xml_path.parent, Path.cwd()):
            if d.is_dir():
                try:
                    found.extend(sorted(d.glob("*.xml")))
                except OSError:
                    pass
        if found:
            print("不过在这几个目录里找到了这些 .xml，也许其中一个是：")
            for f in found[:10]:
                print(f"  {f}  ({f.stat().st_size} 字节)")
            print("如果是，直接用它：learn-schema --roundtrip-xml <上面那个路径>")
        return 2
    if xml_path.stat().st_size == 0:
        print(f"文件是空的（0 字节）：{xml_path}", file=sys.stderr)
        print("说明 XMATIC_OLB2XML 建了个空文件就结束了 —— 多半是输入的 .olb 不存在或没有内容。")
        print("先用 Capture 打开那个 .olb，确认里面有 Part。")
        return 2

    text = _read_text_auto(xml_path)

    outdir = Path(args.out or "schema")
    outdir.mkdir(parents=True, exist_ok=True)

    # ---- 真方言检测：<Lib>/<Package> 才是 Capture 真正吐出来的 ----
    from .symbol.capture_lib import (
        extract_default_values,
        is_capture_lib_dialect,
        generate_lib_xml,
    )

    is_real = is_capture_lib_dialect(text)
    defaults = extract_default_values(text) if is_real else None

    if defaults:
        tpl = outdir / "capture_defaults.xml"
        tpl.write_text(defaults + "\n", encoding="utf-8", newline="\n")
        print("检测到 Capture 真方言（<Lib>/<Package>）")
        print(f"  DefaultValues 已抽出 → {tpl}（生成器会原样复用它）")
        print()

    prof = build_profile_from_olb_xml(text)
    prof_path = outdir / "profile.json"
    prof_path.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        analysis = analyze_olb_xml(text)
    except Exception as e:  # noqa: BLE001 —— 不是合法 XML 时退化成只出 profile
        print(f"警告: 没能按 XML 解析这份文件（{e}）。")
        print("      XMATIC_OLB2XML 的输出可能不是标准 XML，或者文件不完整。")
        print(f"      只写出了 {prof_path}")
        return 1

    report = render_schema_report(analysis, source=str(xml_path))
    report_path = outdir / "schema-report.txt"
    report_path.write_text(report, encoding="utf-8", newline="\n")

    # 顺便把机器可读的那份也存着，方便整份发回来
    (outdir / "schema-structure.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"根元素        : {analysis['root']}")
    print(f"元素总数      : {analysis['elementCount']}")
    print(f"不同标签      : {len(analysis['elements'])}")
    print()
    print("最上面的几层结构：")
    for e in analysis["elements"][:12]:
        depth = e["path"].count("/")
        name = e["path"].rsplit("/", 1)[-1]
        attrs = ", ".join(e["attrs"]) if e["attrs"] else "—"
        print(f"  {'  ' * depth}{name}  ×{e['count']}   @{attrs}")
    if len(analysis["elements"]) > 12:
        print(f"  … 还有 {len(analysis['elements']) - 12} 个标签，见清单文件")
    print()
    print("产出：")
    print(f"  {report_path}              结构清单（人读，**把这个发回给我**）")
    print(f"  {outdir / 'schema-structure.json'}  同上，机器可读")
    print(f"  {prof_path}              初次尝试的 profile（可能不全，先别急着用）")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """生成探测脚本，并打印一行「可直接粘进 Capture 命令窗口」的 source 命令。"""
    src = Path(__file__).parent / "install" / "templates" / "probe.tcl"
    text = src.read_text(encoding="utf-8") if src.exists() else _FALLBACK_PROBE
    out = (Path(args.out or "probe.tcl")).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")

    # Capture 的 Tcl 里路径用正斜杠最稳（反斜杠会被当转义）
    fwd = str(out).replace("\\", "/")

    print(f"探测脚本 → {out}")
    print()
    print("在 OrCAD Capture 的命令窗口里粘贴这一行，回车：")
    print()
    print(f'  source "{fwd}"')
    print()
    print("命令窗口怎么开：Capture 菜单 View → Command Window（一般在界面底部）。")
    print("找不到的话，见 docs/上机测试步骤.md 里 B1 的三种替代办法。")
    print()
    print("跑完把整段输出发给我 —— 尤其是「尝试加载」和「结论」两段。")
    return 0


_FALLBACK_PROBE = """# edakit 能力探测 —— 在 Capture 命令窗口 source 本文件
foreach c {XMATIC_XML2OLB XMATIC_OLB2XML capCreatePartsFromData PlacePart \\
           PlacePartEx PlaceNew InsertXMLMenu} {
    set st [expr {[llength [info commands $c]] ? "OK" : "MISSING"}]
    puts [format "%-26s %s" $c $st]
}
"""


def cmd_deploy(args: argparse.Namespace) -> int:
    import sys

    from .bridge.queue import app_dir
    from .install.deploy import deploy

    runtime_exe = Path(sys.executable)
    if getattr(sys, "frozen", False) and runtime_exe.name.lower() == "edakit-cli.exe":
        runtime_exe = runtime_exe.with_name("edakit.exe")
        if not runtime_exe.is_file():
            raise FileNotFoundError(str(runtime_exe))

    deploy(
        cadence_root=args.cadence_root,
        dry_run=args.dry_run,
        config_allegro=(False if args.no_allegro else None),
    )

    # TCL 插件调商城窗口时需要 exe 的路径；Cadence 进程里没有我们的环境变量，
    # 所以把「部署者自己的路径」记到 app 目录，locateExe 会优先读它。
    if not args.dry_run and getattr(sys, "frozen", False):
        marker = app_dir() / "exe_path.txt"
        marker.write_text(str(runtime_exe), encoding="utf-8")
        print(f"已记录 exe 路径: {marker} -> {runtime_exe}")
    return 0


def cmd_undeploy(args: argparse.Namespace) -> int:
    from .install.deploy import undeploy

    undeploy(cadence_root=args.cadence_root, remove_allegro=args.remove_allegro)
    return 0


def _sample_component_path() -> Path | None:
    """找一个可用于自检的元件样例 JSON（打包后 / 开发环境两条路都试）。"""
    here = Path(__file__).parent
    candidates = (
        here / "samples" / "C2040.json",                         # 打包后 (spec 的 datas)
        here.parent.parent / "tests" / "data" / "C2040.json",    # 开发环境
    )
    for c in candidates:
        if c.is_file():
            return c
    return None


def cmd_selftest(args: argparse.Namespace) -> int:
    """自检 —— 打包完跑一次，确认资源齐全、核心代码路径真的能用。

    别小看它：上一版 exe 因为打包入口写错，一跑就 ImportError，而「打包成功」
    的提示是照打不误的。这个命令就是把「文件生成了」和「真的能用」分开。
    """
    from . import install as install_pkg

    failures: list[str] = []

    def check(label: str, fn) -> None:
        try:
            detail = fn()
            suffix = f"   {detail}" if detail else ""
            print(f"  [OK]   {label}{suffix}")
        except Exception as e:  # noqa: BLE001 —— 自检就是要抓住一切异常
            print(f"  [失败] {label}: {type(e).__name__}: {e}")
            failures.append(label)

    print(f"edakit {__version__}")
    print(f"  解释器  : {sys.executable}")
    print(f"  打包运行: {'是' if getattr(sys, 'frozen', False) else '否'}")
    print()

    # ---- 1. 网页资源（没打进去的话 mall 会是个白页）----
    def check_web() -> str:
        from .server.app import WEB_DIR

        need = ["embed.html", "embed.js", "embed.css", "properties.html", "properties.js", "properties.css"]
        missing = [n for n in need if not (WEB_DIR / n).is_file()]
        if missing:
            raise FileNotFoundError(f"缺 {missing}（在 {WEB_DIR}）")
        total = sum((WEB_DIR / n).stat().st_size for n in need)
        return f"{len(need)} 个文件, 共 {total:,} 字节"

    check("网页资源", check_web)

    # ---- 2. TCL 模板（deploy 靠它们）----
    def check_templates() -> str:
        d = Path(install_pkg.__file__).parent / "templates"
        need = ["edakit.tcl", "edakitInit.tcl", "properties.tcl", "probe.tcl", "diag_olb2xml.tcl"]
        missing = [n for n in need if not (d / n).is_file()]
        if missing:
            raise FileNotFoundError(f"缺 {missing}（在 {d}）")
        return f"{len(need)} 个模板"

    check("TCL 模板", check_templates)

    def check_capture_templates() -> str:
        from .symbol import capture_lib

        blk = capture_lib.default_values_block()
        if "<DefaultValues>" not in blk:
            raise ValueError("capture172_defaults.xml 内容不对")
        return f"{len(blk):,} 字节"

    check("Capture 库 XML 模板", check_capture_templates)

    # ---- 3. 配置/队列目录可写 ----
    def check_dirs() -> str:
        from .bridge.queue import Config, queue_dir

        cfg = Config.load()
        cfg.ensure_dirs()
        probe_file = queue_dir() / ".selftest"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        return str(queue_dir())

    check("配置与队列目录可写", check_dirs)

    # ---- 4. 解析核心 ----
    sample = _sample_component_path()

    def check_parse() -> str:
        if sample is None:
            raise FileNotFoundError("没找到自检样例 JSON")
        payload = json.loads(sample.read_text(encoding="utf-8"))
        comp = parse_component("C2040", payload)
        if comp.symbol is None or comp.footprint is None:
            raise ValueError("样例元件解析后缺符号或缺封装")
        return f"{comp.title}: {len(comp.symbol.pins)} 引脚 / {len(comp.footprint.pads)} 焊盘"

    check("解析器", check_parse)

    # ---- 5. 符号 XML 生成 ----
    def check_symbol_xml() -> str:
        if sample is None:
            raise FileNotFoundError("没找到自检样例 JSON")
        from .symbol.capture_lib import generate_lib_xml

        payload = json.loads(sample.read_text(encoding="utf-8"))
        comp = parse_component("C2040", payload)
        xml = generate_lib_xml(
            comp.symbol,  # type: ignore[arg-type]
            package_name=comp.footprint.name if comp.footprint else "PART",
            footprint=comp.footprint.name if comp.footprint else "",
            refdes_prefix=comp.symbol.prefix,  # type: ignore[union-attr]
        )
        for marker in ("<SymbolPinScalar>", "<SymbolBBox>", "<IsPinNamesVisible>", "<IsPinNumbersVisible>"):
            if marker not in xml:
                raise ValueError(f"生成的 XML 里没有 {marker}")
        return f"{len(xml):,} 字节"

    check("符号 XML 生成", check_symbol_xml)

    # ---- 6. 封装 SKILL 生成 ----
    def check_skill() -> str:
        if sample is None:
            raise FileNotFoundError("没找到自检样例 JSON")
        payload = json.loads(sample.read_text(encoding="utf-8"))
        comp = parse_component("C2040", payload)
        il = generate_skill(comp.footprint, refdes_prefix=comp.symbol.prefix if comp.symbol else "")  # type: ignore[arg-type]
        for fn in ("axlDBCreatePadStack", "axlDBCreatePin", "axlSaveDesign"):
            if fn not in il:
                raise ValueError(f"生成的 SKILL 里没有 {fn}")
        return f"{len(il):,} 字节"

    check("封装 SKILL 生成", check_skill)

    def check_extended_geometry() -> str:
        import tempfile
        from .footprint.shapes import shape_scripts
        from .footprint.geometry import path_polygons
        from .easyeda.parse import _Transform
        from .easyeda.model import Pad, Footprint
        from .footprint.padstack import merge_padstacks
        source = Path(__file__).parent / "samples" / "C165948.json"
        if not source.exists():
            source = Path(__file__).resolve().parents[2] / "tests/data/C165948.json"
        comp = parse_component("C165948", json.loads(source.read_text(encoding="utf-8")))
        with tempfile.TemporaryDirectory(prefix="edakit-geometry-") as directory:
            scripts = shape_scripts(comp.footprint, Path(directory))
        if not scripts or sum(p.mechanical for p in comp.footprint.padstacks) != 2:
            raise ValueError("异形焊盘或机械孔解析失败")
        path_polygons("M0 0 C1 0 2 1 2 2 L0 2Z", _Transform(0, 0, flip_y=False))
        fp = Footprint(name="RR", padstacks=merge_padstacks([
            Pad(number="1", shape="ROUNDRECT", w_mm=2, h_mm=1,
                layers=["TOP"], corner_radius_mm=.2)]))
        if "ROUNDED_RECTANGLE" not in generate_skill(fp):
            raise ValueError("圆角焊盘生成失败")
        return f"{len(scripts)} 个形状依赖，机械孔、曲线和圆角焊盘通过"

    check("扩展封装几何与动态库", check_extended_geometry)

    # ---- 7. SVG 预览生成 ----
    def check_render() -> str:
        if sample is None:
            raise FileNotFoundError("没找到自检样例 JSON")
        from .render import render_footprint_svg, render_symbol_svg

        payload = json.loads(sample.read_text(encoding="utf-8"))
        comp = parse_component("C2040", payload)
        a = render_symbol_svg(comp.symbol)          # type: ignore[arg-type]
        b = render_footprint_svg(comp.footprint)    # type: ignore[arg-type]
        if not a.startswith("<svg") or not b.startswith("<svg"):
            raise ValueError("渲染结果不是 SVG")
        return f"符号 {len(a):,} B / 封装 {len(b):,} B"

    check("SVG 预览渲染", check_render)

    def check_png() -> str:
        from .render.png import render_png
        png = render_png('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><circle cx="5" cy="5" r="3" fill="red"/></svg>', 512)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG preview renderer returned invalid data")
        return f"{len(png):,} bytes"

    check("PNG 内嵌预览", check_png)

    def check_model_preview():
        from .threed.preview import render_model_png
        data = b"v 0 0 0\nv 2 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 2 4\nf 2 3 4\nf 3 1 4\n"
        png = render_model_png(data, 512)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        return f"{len(png):,} bytes"

    check("3D 模型预览", check_model_preview)

    # ---- 8. HTTP 服务能起来（不起端口、不联网）----
    def check_server() -> str:
        from . import server as server_pkg

        port = server_pkg.app.find_free_port()
        httpd = server_pkg.app.make_server(port=port, verbose=False)
        httpd.server_close()
        return f"可用端口 {port}"

    check("HTTP 服务", check_server)

    print()
    if failures:
        print(f"自检未通过，{len(failures)} 项失败: {', '.join(failures)}")
        return 2
    print("自检全部通过。")
    return 0


def cmd_lib_xml(args: argparse.Namespace) -> int:
    """把一个元件生成 Capture 真方言的库 XML（可直接喂 XMATIC_XML2OLB）。"""
    from .symbol.capture_lib import default_values_block, extract_default_values, generate_lib_xml

    if args.offline_json:
        payload = json.loads(Path(args.offline_json).read_text(encoding="utf-8"))
        cid = args.lcsc or "C0000"
    else:
        cid = args.lcsc.upper()
        print(f"取数 {cid} …")
        payload = Fetcher().get_component(cid)

    comp = parse_component(cid, payload)
    if comp.symbol is None:
        print("该元件没有原理图符号，无法生成库 XML。", file=sys.stderr)
        return 2

    defaults = default_values_block()
    if args.template:
        found = extract_default_values(Path(args.template).read_text(encoding="utf-8", errors="replace"))
        if found:
            defaults = found
            print(f"DefaultValues 取自 {args.template}")
        else:
            print(f"警告: {args.template} 里没找到 <DefaultValues>，改用内置模板")

    pkg = args.package or (comp.footprint.name if comp.footprint else comp.symbol.name)
    xml = generate_lib_xml(
        comp.symbol,
        lib_path=args.lib_path or "",
        package_name=pkg,
        footprint=(comp.footprint.name if comp.footprint else ""),
        refdes_prefix=comp.symbol.prefix,
        defaults=defaults,
        include_text=args.text,
    )
    out = Path(args.out or f"{pkg}.olb.xml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8", newline="\n")

    fwd = str(out.resolve()).replace("\\", "/")
    print(f"库 XML → {out}  ({len(xml):,} 字节, {len(comp.symbol.pins)} 引脚)")
    print()
    print("在 Capture 命令窗口里转成 .olb：")
    print(f'  XMATIC_XML2OLB "{fwd}" "D:/cadence/lcsc_test.olb"')
    print("然后在 Capture 里 File > Open > Library 打开 D:/cadence/lcsc_test.olb")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .bridge.queue import Config, capture_alive, pending_requests, queue_dir

    cfg = Config.load()
    print("配置:")
    for k, v in vars(cfg).items():
        print(f"  {k:<20} {v}")
    print(f"\n队列目录: {queue_dir()}")
    pend = pending_requests()
    print(f"待处理请求: {len(pend)}")
    for r in pend:
        print(f"  {r.get('seq','?'):<24} {r.get('cid','?')}")
    print(f"Capture 在线: {'是' if capture_alive() else '否'}")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edakit", description="EdaKit / EDA 工具箱")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mall", help="旧命令兼容：仅启动内嵌商城服务")
    m.add_argument("--port", type=int, default=0, help="0 = 自动选端口")
    m.add_argument("--no-browser", action="store_true")
    m.add_argument("--verbose", action="store_true")
    m.set_defaults(func=cmd_mall)

    s = sub.add_parser("serve", help="只起本地服务，不开浏览器")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--verbose", action="store_true")
    s.add_argument("--capture-pid", type=int, default=0, help="Capture-owned lifetime (plugin use)")
    s.set_defaults(func=cmd_serve)

    se = sub.add_parser("search", help="命令行搜立创商城")
    se.add_argument("keyword")
    se.add_argument("--size", type=int, default=20)
    se.set_defaults(func=cmd_search)

    stg = sub.add_parser("stage", help="把一个元件落盘 (符号/封装/3D)")
    stg.add_argument("--lcsc", required=True)
    stg.add_argument("--footprint-lib", help="覆盖封装库目录")
    stg.add_argument("--calib", default="", choices=["", "easyeda2kicad", "lcsc"])
    stg.add_argument("--schema", help="Capture 库 XML schema profile")
    stg.add_argument("--no-step", action="store_true", help="不下载 3D STEP")
    stg.set_defaults(func=cmd_stage)

    pl = sub.add_parser("place", help="投递一次放置请求 (等价界面点放置)")
    pl.add_argument("--lcsc", required=True)
    pl.add_argument("--footprint-lib")
    pl.add_argument("--session", default="", help="目标 Capture 会话标识")
    pl.add_argument("--follow-cursor", action="store_true")
    pl.add_argument("--x", type=float, default=500.0)
    pl.add_argument("--y", type=float, default=500.0)
    pl.add_argument("--stage-only", action="store_true", help="只落盘不动 OrCAD")
    pl.add_argument("--no-step", action="store_true")
    pl.set_defaults(func=cmd_place)

    ps = sub.add_parser("place-status", help="查一次放置请求的结果")
    ps.add_argument("seq")
    ps.set_defaults(func=cmd_place_status)

    om = sub.add_parser("olb-merge", help="把元件 XML 合并进工程库 XML (Capture 回调)")
    om.add_argument("--base", help="已有库 XML (空 = 新建)")
    om.add_argument("--part", required=True)
    om.add_argument("--out", required=True)
    om.set_defaults(func=cmd_olb_merge)

    ae = sub.add_parser("allegro-env", help="配置/查看/移除 Allegro 环境变量")
    ae.add_argument("--lib", help="封装库目录")
    ae.add_argument("--show", action="store_true")
    ae.add_argument("--remove", action="store_true")
    ae.add_argument("--dry-run", action="store_true")
    ae.set_defaults(func=cmd_allegro_env)

    f = sub.add_parser("fetch", help="只取数")
    f.add_argument("--lcsc", required=True)
    f.add_argument("--out", default=".")
    f.set_defaults(func=cmd_fetch)

    pa = sub.add_parser("parse", help="解析本地 JSON")
    pa.add_argument("--lcsc", required=True)
    pa.add_argument("--json", required=True)
    pa.add_argument("--dump")
    pa.set_defaults(func=cmd_parse)

    b = sub.add_parser("build", help="完整流水线 (旧式: 一次性出全套文件)")
    b.add_argument("--lcsc", required=True)
    b.add_argument("--out", default="./lcsc_out")
    b.add_argument("--offline-json", help="离线: 用本地 component.json 代替取数")
    b.add_argument("--schema", help="Capture 库 XML schema profile (learn-schema 产物)")
    b.add_argument("--calib", default="easyeda2kicad", choices=["easyeda2kicad", "lcsc"])
    b.add_argument("--dll", help="DboTclWriteBasic 扩展 DLL 路径")
    b.add_argument("--download-step", action="store_true", default=True)
    b.set_defaults(func=cmd_build)

    ls = sub.add_parser("learn-schema", help="从参考 OLB 回读 Capture schema")
    ls.add_argument("--olb", help="参考 .olb 路径（只用于打印提示，可省）")
    ls.add_argument("--roundtrip-xml", help="XMATIC_OLB2XML 转出来的 XML")
    ls.add_argument("--out", default="./schema", help="输出目录")
    ls.set_defaults(func=cmd_learn_schema)

    pr = sub.add_parser("probe", help="生成 Cadence 能力探测脚本")
    pr.add_argument("--out")
    pr.set_defaults(func=cmd_probe)

    d = sub.add_parser("deploy", help="部署插件到 Cadence")
    d.add_argument("--cadence-root")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--no-allegro", action="store_true", help="不自动配 Allegro env")
    d.set_defaults(func=cmd_deploy)

    u = sub.add_parser("undeploy", help="卸载插件")
    u.add_argument("--cadence-root")
    u.add_argument("--remove-allegro", action="store_true", help="同时回滚 Allegro env")
    u.set_defaults(func=cmd_undeploy)

    st = sub.add_parser("status", help="查看配置 / 队列 / Capture 在线状态")
    st.set_defaults(func=cmd_status)

    sc = sub.add_parser("selftest", help="自检: 确认打包资源齐全、核心路径可用")
    sc.set_defaults(func=cmd_selftest)

    lx = sub.add_parser("lib-xml", help="生成 Capture 真方言的库 XML (喂 XMATIC_XML2OLB)")
    lx.add_argument("--lcsc", help="立创 C 编号")
    lx.add_argument("--offline-json", help="离线: 用本地 component.json")
    lx.add_argument("--package", help="Package 名 (默认用封装名)")
    lx.add_argument("--lib-path", help="写进 <Defn name> 的 .olb 路径 (可省)")
    lx.add_argument("--template", help="参考库 XML (从中取 DefaultValues)")
    lx.add_argument("--text", action="store_true", help="把文字图元也生成进去")
    lx.add_argument("--out")
    lx.set_defaults(func=cmd_lib_xml)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LcscError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        # 裸 traceback 对用户没有任何帮助，给一句人话
        print(f"错误: 找不到文件 —— {e.filename or e}", file=sys.stderr)
        return 2
    except PermissionError as e:
        print(f"错误: 没有权限访问 {e.filename or e}（文件可能正被别的程序占用）", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

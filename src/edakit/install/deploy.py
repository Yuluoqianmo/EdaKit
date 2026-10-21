"""把 Capture TCL 插件装进 Cadence 安装树，并配置 Allegro 环境。

定位 Cadence 安装根 → 找 tools/capture/tclscripts/capAutoLoad/ → 拷模板。
23.x 起换成 OrCAD X 新安装布局，路径可能变，所以按「在若干候选根里找特征目录」写，
不硬编码单一版本。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ..bridge.queue import Config
from ..errors import DeployError
from . import allegro_env

# capAutoLoad 的加载行为按「只扫本目录、不递归」处理（最坏情况也兼容递归）：
#   - 主逻辑放子目录 capAutoLoad/edakit/edakit.tcl
#   - 入口 edakitInit.tcl 放 capAutoLoad 根目录，由它 source 主逻辑
# 主逻辑自带「重复 source 直接返回」的守卫，所以即使 Capture 递归扫描到
# 子目录里的主文件，也不会注册两遍/开两个轮询。
INIT_TEMPLATE = "edakitInit.tcl"
MAIN_TEMPLATE = "edakit.tcl"
TEMPLATES = (INIT_TEMPLATE, MAIN_TEMPLATE)

# \"Program Files\" 只是常见位置之一 —— 很多公司装在 D:\Cadence\SPB_17.2 这种地方，
# 所以下面还会按盘符扫 <盘>:\Cadence\SPB_* / OrCADX_*。
VERSIONS = ("16.6", "17.2", "17.4", "22.1", "23.1", "24.1", "25.1")

CANDIDATE_ROOTS = [
    rf"Program Files\Cadence\SPB_{v}" for v in VERSIONS
] + [
    rf"Cadence\SPB_{v}" for v in VERSIONS
] + [
    r"Program Files\Cadence\OrCADX_23.1",
    r"Program Files\Cadence\OrCADX_24.1",
    r"Cadence\OrCADX_23.1",
    r"Cadence\OrCADX_24.1",
]

DRIVES = ("C:\\", "D:\\", "E:\\", "F:\\")


def _tclscripts_under(root: Path) -> Path | None:
    for cand in (root / "tools" / "capture" / "tclscripts", root / "capture" / "tclscripts"):
        if cand.is_dir():
            return cand
    return None


def find_capture_tcl_root(cadence_root: str | None = None) -> Path:
    """返回 tclscripts 目录 (capAutoLoad 的父目录)。

    **显式给了 cadence_root 就只用它**：指定了却找不到，直接报错，不偷偷退回
    去扫别的安装 —— 否则用户以为装到了 Z 盘，实际装进了另一个版本，很难查。
    没给时才按「环境变量 → 常见安装位置 → 各盘符兜底扫描」去找。
    """
    if cadence_root:
        root = Path(cadence_root)
        found = _tclscripts_under(root)
        if found:
            return found
        raise DeployError(
            f"指定的 Cadence 根目录下没有 Capture 的 tclscripts：\n"
            f"  {root}\n"
            f"应该存在 {root / 'tools' / 'capture' / 'tclscripts'}。\n"
            f"请确认 --cadence-root 指向的是 SPB 安装根（例如 D:\\Cadence\\SPB_17.2），"
            f"而不是 tools 或 capture 子目录。"
        )

    roots: list[Path] = []
    for env in ("CDSROOT", "CDS_INST_DIR", "CONCEPTHDL_CDS_ROOT"):
        if os.environ.get(env):
            roots.append(Path(os.environ[env]))
    for rel in CANDIDATE_ROOTS:
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ):
            roots.append(Path(base) / rel)
            roots.append(Path(base) / rel / "tools")
        for drive in DRIVES:
            d = Path(drive)
            if d.is_dir():
                roots.append(d / rel)
                roots.append(d / rel / "tools")

    # 兜底：扫各盘符的 Cadence 目录下的实际名字（万一版本号不在上面列表里）
    for drive in DRIVES:
        cad = Path(drive) / "Cadence"
        if cad.is_dir():
            try:
                for child in cad.iterdir():
                    if child.is_dir():
                        roots.append(child)
            except OSError:
                pass

    for root in roots:
        found = _tclscripts_under(root)
        if found:
            return found

    raise DeployError(
        "找不到 Capture 的 tclscripts 目录。\n"
        "请用 --cadence-root 指定 SPB 安装根 (例如 C:\\Cadence\\SPB_17.4)，"
        "或设置 CDSROOT 环境变量。"
    )


def target_dir(cadence_root: str | None = None) -> Path:
    return find_capture_tcl_root(cadence_root) / "capAutoLoad" / "edakit"


def spb_root_from_tcl(tcl_root: Path) -> Path | None:
    """tclscripts 的路径是 <SPB>/tools/capture/tclscripts —— 往上退三层就是 SPB 根。"""
    try:
        if tcl_root.name.lower() == "tclscripts" and tcl_root.parent.name.lower() == "capture":
            return tcl_root.parents[2]
    except (IndexError, AttributeError):
        pass
    return None


def deploy(
    cadence_root: str | None = None,
    *,
    dry_run: bool = False,
    config_allegro: bool | None = None,
) -> Path:
    """装插件 + (可选) 配 Allegro env。返回插件目录。"""
    cfg = Config.load()
    cfg.ensure_dirs()

    tcl_root = find_capture_tcl_root(cadence_root or cfg.cadence_root or None)
    target = tcl_root / "capAutoLoad" / "edakit"
    src = Path(__file__).parent / "templates"

    print(f"Capture tclscripts: {tcl_root}")
    print(f"插件目标目录:       {target}")

    if not dry_run:
        auto = tcl_root / "capAutoLoad"
        auto.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        for name in TEMPLATES:
            s = src / name
            if not s.exists():
                raise DeployError(f"模板缺失: {s}")
        shutil.copy2(src / MAIN_TEMPLATE, target / MAIN_TEMPLATE)
        print(f"  已装 {MAIN_TEMPLATE}  → {target}")
        shutil.copy2(src / INIT_TEMPLATE, auto / INIT_TEMPLATE)
        print(f"  已装 {INIT_TEMPLATE}  → {auto}")
        # Disable only the two known legacy startup scripts, preserving them
        # for rollback. Do not delete an installation directory or user data.
        for legacy in (auto / "lcsc2cadenceInit.tcl",
                       auto / "lcsc2cadence" / "lcsc2cadence.tcl"):
            if legacy.is_file():
                backup = legacy.with_suffix(".tcl.disabled")
                if backup.exists():
                    backup = legacy.with_suffix(".tcl.disabled.new")
                if backup.exists():
                    raise DeployError(f"旧插件备份已存在，请先检查: {backup}")
                legacy.rename(backup)
                print(f"  旧插件入口已停用: {legacy}")
        # 旧版本把入口也装在子目录里 —— 清掉，免得起两遍
        stale = target / INIT_TEMPLATE
        if stale.exists():
            stale.unlink()

    # 封装库 / 工程库目录
    print(f"封装库目录:         {cfg.footprint_lib}")
    print(f"累积工程库:         {cfg.project_olb}")

    do_allegro = cfg.auto_config_allegro if config_allegro is None else config_allegro
    if do_allegro:
        try:
            spb = spb_root_from_tcl(tcl_root)
            allegro_env.configure(
                cfg.footprint_lib, dry_run=dry_run,
                cadence_root=str(spb) if spb else None,
            )
        except DeployError as e:
            print(f"  警告: 未能自动配置 Allegro env ({e})")
            print("        可以稍后手动跑: edakit allegro-env --lib <目录>")

    print()
    print("部署完成。重启 Capture 后：")
    print("  · 菜单栏会出现「EdaKit → LCSC Mall」")
    print("  · 启动时命令行会打印 'edakit: 已启动，队列轮询中'")
    return target


def undeploy(cadence_root: str | None = None, *, remove_allegro: bool = False) -> None:
    try:
        t = target_dir(cadence_root)
        init = t.parent / INIT_TEMPLATE
        if init.exists():
            init.unlink()
            print(f"已移除 {init}")
        if t.exists():
            shutil.rmtree(t)
            print(f"已移除 {t}")
    except DeployError as e:
        print(f"跳过 TCL 插件移除: {e}")
    if remove_allegro:
        try:
            allegro_env.unconfigure(cadence_root=cadence_root)
        except DeployError as e:
            print(f"跳过 Allegro env 清理: {e}")

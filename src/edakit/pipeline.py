"""流水线 —— 把一个元件「落盘」成 Cadence 需要的全部文件。

放置一次元件，要产出这些:

  Capture 侧 (放原理图)               Allegro 侧 (建封装)
  ----------------------             -----------------------
  <cid>.olb.xml   符号库 XML          <封装>.il   建封装的 SKILL 脚本
      ↓ XMATIC_XML2OLB 在 Capture 里跑      ↓ 在 Allegro 里 load()
  合并进工程 .olb                     <封装>.dra/.psm/.pad  (由 SKILL 生成)
                                     <封装>.step  3D 模型 (放 steppath)
                                     part_<cid>.map.xml  3D 映射

本模块负责把文件放到正确的地方，并返回一份清单给界面/日志。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

from .config import Config
from .storage import atomic_write
from .easyeda.model import Component
from .errors import UnsupportedGeometryError
from .easyeda.parse import parse_component
from .footprint.skill import generate_skill
from .footprint.validation import validate_pin_mapping
from .fetch import Fetcher
from .threed.mapping import build_3dcanvas_mapping_xml, build_map_xml, calibrate
from .threed.step import StepFetcher


@dataclass
class Staged:
    """落盘结果清单。"""

    cid: str = ""
    workdir: Path | None = None
    symbol_xml: Path | None = None
    footprint_skill: Path | None = None
    pin_map: Path | None = None
    step: Path | None = None
    map_xml: Path | None = None
    footprint_name: str = ""
    part_name: str = ""
    warnings: list[str] = field(default_factory=list)
    preparation_reused: bool = False

    def to_dict(self) -> dict:
        return {
            "cid": self.cid,
            "workdir": str(self.workdir) if self.workdir else "",
            "symbolXml": str(self.symbol_xml) if self.symbol_xml else "",
            "footprintSkill": str(self.footprint_skill) if self.footprint_skill else "",
            "pinMap": str(self.pin_map) if self.pin_map else "",
            "step": str(self.step) if self.step else "",
            "mapXml": str(self.map_xml) if self.map_xml else "",
            "footprint": self.footprint_name,
            "partName": self.part_name,
            "warnings": self.warnings,
            "preparationReused": self.preparation_reused,
        }


def fetch_component(cid: str) -> Component:
    cid = cid.strip().upper()
    if not cid.startswith("C"):
        cid = "C" + cid
    return parse_component(cid, Fetcher().get_component(cid))


def stage_component(comp: Component, cfg: Config, *, download_step: bool = True, capture_only: bool = False, output_dir: Path | None = None) -> Staged:
    """把元件落盘到配置好的目录。"""
    from .library import library_names
    identities = library_names(comp)
    # 所有模式均在写文件或复用 XML 缓存前校验，不能将错误的符号/封装配对交给用户。
    pin_map = (validate_pin_mapping(comp.symbol, comp.footprint)
               if comp.symbol is not None and comp.footprint is not None else None)
    if pin_map is not None:
        pin_map.update(identities)
        from .symbol.capture_lib import normalize_capture_symbol
        prepared_symbol = normalize_capture_symbol(comp.symbol)
        capture_pins = {p.number: p for p in prepared_symbol.pins}
        for entry in pin_map['pins']:
            pin = capture_pins[entry['number']]
            entry['capture_name'] = pin.name
            entry['capture_electrical_type'] = pin.electrical_type
        pin_map['capture_hotpoint_grid_mil'] = 100
    cfg.ensure_dirs()
    cid = comp.cid
    work = Path(output_dir) / cid if output_dir is not None else Path(cfg.footprint_lib).parent / "staging" / cid
    if output_dir is None and cfg.symbol_lib:
        work = Path(cfg.symbol_lib) / '.edakit-staging' / cid
    lib = work if output_dir is not None else Path(cfg.footprint_lib)
    work.mkdir(parents=True, exist_ok=True)

    out = Staged(cid=cid, workdir=work)
    fp_name = identities['footprint']
    out.footprint_name = fp_name
    if pin_map is not None:
        out.pin_map = work / f"{cid}.pinmap.json"
        atomic_write(out.pin_map, json.dumps(pin_map, ensure_ascii=False, indent=2) + "\n")

    # ---- 1. 符号库 XML (给 Capture 的 XMATIC) ----
    if comp.symbol is None:
        out.warnings.append("立创没有该元件的原理图符号，无法放置到原理图")
    else:
        from .symbol.capture_lib import (
            default_values_block,
            extract_default_values,
            generate_lib_xml,
        )

        # DefaultValues 从哪里来：用户用 learn-schema 抽出来的那份优先，
        # 否则用内置的（取自用户机器上 Capture 17.2 的真实导出）。
        defaults = None
        if cfg.schema_profile:
            prof_path = Path(cfg.schema_profile)
            for cand in (prof_path.parent / "capture_defaults.xml", prof_path):
                if cand.is_file():
                    txt = cand.read_text(encoding="utf-8", errors="replace")
                    found = extract_default_values(txt)
                    if found:
                        defaults = found
                        break
        if not defaults:
            defaults = default_values_block()

        # Bypass definitions without the placement properties in Capture's
        # design cache. PartValue keeps the original full model.
        pkg_name = identities['symbol']
        out.part_name = pkg_name
        def generate():
            return generate_lib_xml(
                comp.symbol,
                lib_path=str(Path(cfg.project_olb)) if cfg.project_olb else "",
                package_name=pkg_name,
                footprint=fp_name,
                refdes_prefix=comp.symbol.prefix,
                defaults=defaults,
            )
        if capture_only:
            from .symbol.prepared import prepare_xml
            out.symbol_xml, out.preparation_reused = prepare_xml(work, cid, {
                "symbol": asdict(comp.symbol), "package": pkg_name, "footprint": fp_name,
                "project_olb": cfg.project_olb, "defaults": defaults,
            }, generate)
        else:
            p = work / f"{cid}.olb.xml"
            atomic_write(p, generate())
            out.symbol_xml = p

    # Capture needs the symbol and footprint NAME, not Allegro files or STEP.
    # Full export callers retain the original behavior by default.
    if capture_only:
        (work / "CAPTURE.txt").write_text(
            f"{cid}: Capture symbol prepared. Full PCB/STEP export remains available through stage/build.\n",
            encoding="utf-8",
        )
        return out

    # ---- 2. 建封装的 SKILL (.il) → 放到封装库目录 ----
    if comp.footprint is None:
        out.warnings.append("立创没有该元件的 PCB 封装")
    else:
        try:
            from copy import deepcopy
            pcb = deepcopy(comp.footprint)
            pcb.name = fp_name
            if any(layer.shape == 'SHAPE' for pad in pcb.padstacks for layer in pad.layers):
                raise UnsupportedGeometryError('该封装包含自定义形状依赖，请使用插件“生成 PCB 封装”完成原生编译和完整发布。')
            il = generate_skill(pcb, output_dir=lib,
                                refdes_prefix=comp.symbol.prefix if comp.symbol else "")
        except UnsupportedGeometryError as e:
            out.warnings.append(f"PCB 封装脚本未生成: {e}")
        else:
            p = lib / f"{_safe(fp_name)}.il"
            atomic_write(p, il)
            out.footprint_skill = p

    # ---- 3. 3D STEP + 映射 ----
    if comp.model3d is not None:
        model = calibrate(comp.model3d, mode=cfg.calib)
        if download_step:
            try:
                step_folder = lib if output_dir is not None else Path(cfg.effective_step_lib)
                step_folder.mkdir(parents=True, exist_ok=True)
                target = step_folder / f"{_safe(fp_name)}.step"
                StepFetcher().download_step(model.uuid, target)
                model.step_path = target.name
                out.step = target
            except Exception as e:  # noqa: BLE001 —— 3D 失败不该挡住主体流程
                out.warnings.append(f"3D 模型下载失败: {e}")
        if out.step is not None:
            map_path = lib / f"{_safe(fp_name)}.map.xml"
            map_path.write_text(
                build_map_xml(model, package_name=fp_name), encoding="utf-8", newline="\n"
            )
            out.map_xml = map_path
            # 顺带出一份 3D Canvas 用的批量导入 XML (新机制)
            (lib / f"{_safe(fp_name)}.3dmap.xml").write_text(
                build_3dcanvas_mapping_xml(model, package_name=fp_name),
                encoding="utf-8",
                newline="\n",
            )
    else:
        out.warnings.append("该元件没有 3D 模型")

    # ---- 4. 一份人读的小抄 ----
    (work / "README.txt").write_text(_readme(comp, out), encoding="utf-8", newline="\n")
    return out


def _safe(name: str) -> str:
    """把封装名变成安全的文件名。"""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in name).strip()
    return out or "PACKAGE"


def _readme(comp: Component, st: Staged) -> str:
    lines = [
        f"元件: {comp.title} ({comp.cid})",
        f"封装: {st.footprint_name}",
        "",
        "=== 放到原理图 (OrCAD Capture) ===",
        "  在 Capture 里点菜单「EDA 工具箱 → 打开EDA 工具箱」，然后双击器件即可自动放置。",
        "  手工方式: 命令窗口 source 下面的文件，再 PlacePart:",
        f"    XMATIC_XML2OLB \"{st.symbol_xml}\" \"<你的库>.olb\"",
        "",
        "=== 建 PCB 封装 (Allegro) ===",
        (f"  在 Allegro 命令窗口: load(\"{st.footprint_skill}\")"
         if st.footprint_skill else "  未生成 PCB 候选脚本，请查看下方原因；不能作为完整 PCB 库使用。"),
        "  请在独立 Allegro 符号编辑器中加载候选脚本。",
        "  输出目录已写入脚本；已有 .dra/.psm 会拒绝覆盖。",
        "  当前支持矩形/圆形/OBLONG 焊盘；原生编译、引脚编号及尺寸仍须上机验收。",
        f"  编号/功能名映射清单: {st.pin_map or '(未校验：缺少符号或封装)'}",
        "  功能名来自原理图；仅在 PCB 源数据另有功能名时校验名称相等。",
        "",
        "=== 3D ===",
    ]
    if st.step:
        lines += [
            f"  STEP 模型文件: {st.step}",
            "  使用前请核实 Allegro 的 steppath / step_mapping_path 包含该目录。",
            f"  映射文件: {st.map_xml.name if st.map_xml else '(无)'}",
        ]
    else:
        lines.append("  (无 3D 模型)")
    if st.warnings:
        lines += ["", "=== 注意 ==="] + [f"  · {w}" for w in st.warnings]
    return "\n".join(lines) + "\n"

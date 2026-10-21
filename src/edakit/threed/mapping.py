"""3D 映射与位置校准。

EasyEDA **没有**公开发布过 3D 模型原点约定文档，所以「3D 自带位置校准」的真实含义是:
各家工具靠 SVGNODE 元数据 + 几何自洽反推。本模块实现两种已知口径，由 ``--calib`` 选:

  * ``easyeda2kicad``: 平移取 c_origin 相对封装原点 (解析时已算好), 旋转取反 (360-rx);
  * ``lcsc``: 保留立创装配旋转，仅平移到封装原点和板顶安装面，不二次套用模型旋转。

绑定侧也两条路:
  * 老机制 Step Package Mapping —— 生成文本 XML ``.map`` 放进 step_mapping_path;
  * 新机制 3D Canvas / 3D Mapper (17.2 起) —— File-based Mapping XML 批量导入。
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import quoteattr

from ..easyeda.model import Model3D, Pad

ORIGIN_TOLERANCE_MM = 0.1


def calibrate_easyeda2kicad(model: Model3D, canvas_origin=(0.0, 0.0)) -> Model3D:
    """easyeda2kicad 口径。

    model.origin_mm 已是「相对封装原点的 c_origin」(见 parse.parse_model3d)，
    因此平移 = origin_mm；旋转取反 (360 - rx 等)。
    """
    tx, ty = model.origin_mm
    tz = model.z_mm
    rx, ry, rz = model.rotation_deg
    model.calibrated_rotation_deg = ((360.0 - rx) % 360.0, (360.0 - ry) % 360.0, (360.0 - rz) % 360.0)
    model.offset_mm = (tx, ty, tz)
    return model


def calibrate_lcsc_converter(model: Model3D, pads: list[Pad] | None = None) -> Model3D:
    """lcsc-library-converter 口径: 保留装配旋转，仅平移到封装原点 + 板顶安装面。"""
    model.offset_mm = (0.0, 0.0, model.z_mm)
    model.calibrated_rotation_deg = model.rotation_deg
    return model


def build_map_xml(model: Model3D, *, step_name: str = "", package_name: str = "") -> str:
    """生成 Step Package Mapping 用的文本 XML (.map)。

    字段: step_name / rotation_x·y·z / offset_x·y·z。
    该文件放到 ``step_mapping_path`` 指向的目录。facet 几何 (stepFacetFiles4Map.zip)
    由 Allegro 自己产出，外部不能手写。
    """
    step = step_name or Path(model.step_path).name or f"{package_name}.step"
    rx, ry, rz = model.calibrated_rotation_deg
    ox, oy, oz = model.offset_mm
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<StepPackageMapping>",
        f"  <Package Name={quoteattr(package_name)}>",
        f"    <StepName>{step}</StepName>",
        f"    <RotationX>{rx:.6f}</RotationX>",
        f"    <RotationY>{ry:.6f}</RotationY>",
        f"    <RotationZ>{rz:.6f}</RotationZ>",
        f"    <OffsetX>{ox:.6f}</OffsetX>",
        f"    <OffsetY>{oy:.6f}</OffsetY>",
        f"    <OffsetZ>{oz:.6f}</OffsetZ>",
        "  </Package>",
        "</StepPackageMapping>",
    ]
    return "\n".join(lines) + "\n"


def build_3dcanvas_mapping_xml(model: Model3D, *, package_name: str = "") -> str:
    """生成 3D Canvas / 3D Mapper 的 File-based Mapping XML (批量导入用)。"""
    step = Path(model.step_path).name or f"{package_name}.step"
    rx, ry, rz = model.calibrated_rotation_deg
    ox, oy, oz = model.offset_mm
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<ModelMapping>",
        f"  <Model Package={quoteattr(package_name)} File={quoteattr(step)}>",
        f"    <Rotation>{rx:.6f} {ry:.6f} {rz:.6f}</Rotation>",
        f"    <Offset>{ox:.6f} {oy:.6f} {oz:.6f}</Offset>",
        "    <AlignMode>AUTO</AlignMode>",
        "  </Model>",
        "</ModelMapping>",
    ]
    return "\n".join(lines) + "\n"


CALIBRATORS = {
    "easyeda2kicad": calibrate_easyeda2kicad,
    "lcsc": calibrate_lcsc_converter,
}


def calibrate(model: Model3D, mode: str = "easyeda2kicad") -> Model3D:
    fn = CALIBRATORS.get(mode)
    if fn is None:
        raise ValueError(f"未知校准口径: {mode}，可选 {list(CALIBRATORS)}")
    return fn(model)

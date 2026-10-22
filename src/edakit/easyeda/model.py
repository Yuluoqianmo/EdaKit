"""EasyEDA 数据模型。

解析器只负责往这些 dataclass 里填，生成器只负责读。两边解耦，互不知道对方细节。

坐标约定 (已用真实 C2040 数据 + easyeda2kicad 参照实现验证):
  * 符号: x_mm = (ee_x - bbox中心x) * 0.254;  y_mm = -(ee_y - bbox中心y) * 0.254   (Y 翻转)
  * 封装: x_mm = (ee_x - 画布原点x) * 0.254;  y_mm = (ee_y - 画布原点y) * 0.254   (Y 不翻转)

  符号翻转、封装不翻，是因为 KiCad 符号库 Y 轴朝上、封装(及 EasyEDA 两种画布)Y 轴朝下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class DocType(IntEnum):
    """EasyEDA docType 枚举 (权威来源: KiCad 官方 EasyEDA 导入格式文档)。

    注意常被引用的 "2/3" 是错的: 3 是整块 PCB, 封装是 4。
    """

    SCHEMATIC_SHEET = 1
    SYMBOL = 2
    PCB = 3
    PCB_COMPONENT = 4  # 封装
    SCHEMATIC_LIST = 5
    PCB_MODULE = 14


# 引脚电气类型。EasyEDA 只用 0..4 (已核实 EasyedaPinType 枚举)。
# 映射到 Capture 的 PinType 见 symbol.olb_xml。
PIN_ELECTRICAL_TYPES = {
    "0": "unspecified",
    "1": "input",
    "2": "output",
    "3": "bidirectional",
    "4": "power",
}

# 封装层号 → 语义名。来自真实数据 dataStr.layers 的权威表。
FOOTPRINT_LAYERS = {
    "1": "TOP",
    "2": "BOTTOM",
    "3": "TOP_SILK",
    "4": "BOTTOM_SILK",
    "5": "TOP_PASTE",
    "6": "BOTTOM_PASTE",
    "7": "TOP_SOLDERMASK",
    "8": "BOTTOM_SOLDERMASK",
    "9": "RATLINES",
    "10": "BOARD_OUTLINE",
    "11": "MULTI_LAYER",
    "12": "DOCUMENT",
    "13": "TOP_ASSEMBLY",
    "14": "BOTTOM_ASSEMBLY",
    "99": "ComponentShapeLayer",
    "100": "LeadShapeLayer",
    "101": "ComponentPolarityLayer",
}


@dataclass
class Primitive:
    """一条原始 shape 记录。保留 raw 原文，方便与解析结果对照。"""

    kind: str  # 'R' 'C' 'P' 'PAD' 'TRACK' ...
    fields: list[str] = field(default_factory=list)  # 按 ~ 切分的字段
    sub: list[str] = field(default_factory=list)  # 按 ^^ 切分的子段
    raw: str = ""
    geom: dict[str, Any] = field(default_factory=dict)  # 已解析出的几何 (mm)


@dataclass
class Pin:
    number: str = ""
    name: str = ""
    x_mm: float = 0.0
    y_mm: float = 0.0
    length_mm: float = 0.0
    rotation_deg: float = 0.0  # EasyEDA 原始旋转
    orientation_deg: float = 0.0  # 引脚外指方向 = (rotation + 180) % 360 (Capture/KiCad 约定)
    electrical_type: str = "passive"
    visible: bool = True


@dataclass
class Pad:
    """封装焊盘。

    layers 保存该焊盘出现在哪些层 (语义名)。
    同一引脚的跨层焊盘 (顶/底/内层/阻焊/钢网) 在 padstack.merge 里合并成一个
    padstack，最终只生成一个引脚。
    """

    number: str = ""
    shape: str = "RECT"  # RECT / CIRCLE / OVAL / ROUNDRECT / POLY / ELLIPSE / REGULAR_POLYGON
    x_mm: float = 0.0
    y_mm: float = 0.0
    w_mm: float = 0.0
    h_mm: float = 0.0
    rotation_deg: float = 0.0
    layer_ids: list[str] = field(default_factory=list)  # 原始层号
    layers: list[str] = field(default_factory=list)  # 语义层名
    hole_mm: float = 0.0  # 通孔直径 (0 表示 SMD)
    polygon_mm: list[tuple[float, float]] = field(default_factory=list)
    is_smd: bool = True
    # 可选的独立功能名。EasyEDA Standard PAD 没有该字段，不能把 net 当作 name。
    name: str = ""
    slot_length_mm: float = 0.0
    hole_points_mm: list[tuple[float, float]] = field(default_factory=list)
    hole_plated: bool = True
    corner_radius_mm: float = 0.0
    solder_expansion_mm: float = 0.0
    paste_expansion_mm: float = 0.0
    paste_enabled: bool = True
    solder_enabled: bool = True

    @property
    def top_layer(self) -> str:
        """该焊盘的铜层 (TOP/BOTTOM/MULTI_LAYER)。"""
        for lay in self.layers:
            if lay in ("TOP", "BOTTOM", "MULTI_LAYER"):
                return lay
        return self.layers[0] if self.layers else "TOP"


@dataclass
class PadstackLayer:
    """一个 padstack 在某一层的铜形定义 (供 SKILL 生成用)。"""

    layer: str
    shape: str
    w_mm: float = 0.0
    h_mm: float = 0.0
    polygon_mm: list[tuple[float, float]] = field(default_factory=list)
    radius_mm: float = 0.0
    offset_x_mm: float = 0.0
    offset_y_mm: float = 0.0


@dataclass
class Padstack:
    """合并后的 padstack —— 一个可放置的引脚对应一个。"""

    name: str = ""
    layers: list[PadstackLayer] = field(default_factory=list)
    drill_mm: float = 0.0
    hole_plated: bool = True
    x_mm: float = 0.0  # 引脚锚点
    y_mm: float = 0.0
    rotation_deg: float = 0.0
    mechanical: bool = False
    slot_width_mm: float = 0.0
    slot_height_mm: float = 0.0
    drill_offset_x_mm: float = 0.0
    drill_offset_y_mm: float = 0.0


@dataclass
class Symbol:
    name: str = ""
    cid: str = ""
    primitives: list[Primitive] = field(default_factory=list)
    pins: list[Pin] = field(default_factory=list)
    width_mm: float = 0.0
    height_mm: float = 0.0
    origin: tuple[float, float] = (0.0, 0.0)  # 画布原点 (BBox 中心, 画布单位)
    prefix: str = ""  # 位号前缀, 如 'U'
    manufacturer: str = ""
    mpn: str = ""
    description: str = ""
    datasheet: str = ""
    extra_props: dict[str, str] = field(default_factory=dict)


@dataclass
class Footprint:
    name: str = ""
    pads: list[Pad] = field(default_factory=list)
    padstacks: list[Padstack] = field(default_factory=list)
    primitives: list[Primitive] = field(default_factory=list)
    # 丝印/装配层线段: (layer, [(x,y), ...])
    lines: list[tuple[str, list[tuple[float, float]]]] = field(default_factory=list)
    circles: list[tuple[str, float, float, float]] = field(default_factory=list)  # layer, cx, cy, r
    solid_regions: list[Primitive] = field(default_factory=list)
    height_mm: float = 0.0  # 元件高度 (若有)
    is_smd: bool = True
    model_3d_name: str = ""
    origin: tuple[float, float] = (0.0, 0.0)  # 画布原点 (画布单位)

    @property
    def origin_mm(self) -> tuple[float, float]:
        from .units import FOOTPRINT_UNIT_TO_MM

        return (self.origin[0] * FOOTPRINT_UNIT_TO_MM, self.origin[1] * FOOTPRINT_UNIT_TO_MM)


@dataclass
class Model3D:
    uuid: str = ""
    origin_mm: tuple[float, float] = (0.0, 0.0)  # c_origin (已换算 mm, 相对封装画布)
    z_mm: float = 0.0
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)  # rx, ry, rz
    width_mm: float = 0.0
    height_mm: float = 0.0
    step_path: str = ""
    obj_path: str = ""
    # 校准后的平移/旋转 (由 threed.mapping 计算)
    offset_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    calibrated_rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    outline_center_mm: tuple[float, float] | None = None


@dataclass
class Component:
    cid: str = ""
    uuid: str = ""
    title: str = ""
    symbol: Symbol | None = None
    footprint: Footprint | None = None
    model3d: Model3D | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # 原始 JSON, 便于 dump

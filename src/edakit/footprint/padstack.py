"""焊盘 → padstack 合并。

Cadence Allegro 的一个引脚对应一个 padstack。EasyEDA 里同一个引脚号可能分散在
多个 PAD 记录里 (顶层一个、底层一个、有时内层 + 阻焊/钢网)，必须合并成一个 padstack:

  * 钻孔由提供钻孔的那层定义 (通孔焊盘);
  * 顶/底/内层各自保留自己的铜形;
  * 最终只生成 **一个** 引脚。

同编号但位置/角度不同、或同层出现多个不同铜形的情况，属于「可能丢几何」，按设计
不猜 —— 直接抛 UnsupportedGeometryError，交给上层报错。
"""

from __future__ import annotations

from ..errors import UnsupportedGeometryError
from ..easyeda.model import Pad, Padstack, PadstackLayer

# 铜层集合 (决定谁算铜形)
_COPPER_LAYERS = {"TOP", "BOTTOM", "MULTI_LAYER"}


def _copper_layer(pad: Pad) -> str:
    """返回该焊盘的铜层。MULTI_LAYER(通孔)优先, 否则顶/底。"""
    for lay in pad.layers:
        if lay == "MULTI_LAYER":
            return "MULTI_LAYER"
    for lay in pad.layers:
        if lay in ("TOP", "BOTTOM"):
            return lay
    return pad.layers[0] if pad.layers else "TOP"


def merge_padstacks(pads: list[Pad]) -> list[Padstack]:
    """按引脚号合并焊盘。返回可直接喂给 SKILL 生成器的 padstack 列表。"""
    if not pads:
        return []

    groups: dict[str, list[Pad]] = {}
    for pad in pads:
        key = pad.number or f"@{round(pad.x_mm, 3)},{round(pad.y_mm, 3)}"
        groups.setdefault(key, []).append(pad)

    return [_merge_one(name, group) for name, group in groups.items()]


def _merge_one(name: str, group: list[Pad]) -> Padstack:
    if any(abs((p.rotation_deg - group[0].rotation_deg + 180) % 360 - 180) > 1e-4 for p in group):
        raise UnsupportedGeometryError(f"焊盘 {name} 的同编号记录角度不一致，无法安全合并。")
    holes = {round(p.hole_mm, 4) for p in group if p.hole_mm > 0}
    if len(holes) > 1:
        raise UnsupportedGeometryError(f"焊盘 {name} 的钻孔直径不一致。")
    # 位置一致性检查: 同编号焊盘中心必须重合 (容差 0.01 mm)
    xs = {round(p.x_mm, 2) for p in group}
    ys = {round(p.y_mm, 2) for p in group}
    if len(xs) > 1 or len(ys) > 1:
        raise UnsupportedGeometryError(
            f"焊盘 {name} 的同编号记录位置不一致 (x={sorted(xs)}, y={sorted(ys)})，"
            f"拒绝合并以免生成错误引脚。请人工确认该封装。"
        )

    ps = Padstack(
        name=name,
        x_mm=group[0].x_mm,
        y_mm=group[0].y_mm,
        rotation_deg=group[0].rotation_deg,
        drill_mm=max((p.hole_mm for p in group), default=0.0),
        hole_plated=True,
    )

    seen: dict[str, Pad] = {}
    for pad in group:
        layer = _copper_layer(pad)
        if layer in seen:
            same = seen[layer]
            if (round(same.w_mm, 3), round(same.h_mm, 3), same.shape) != (
                round(pad.w_mm, 3),
                round(pad.h_mm, 3),
                pad.shape,
            ) or same.polygon_mm != pad.polygon_mm:
                raise UnsupportedGeometryError(
                    f"焊盘 {name} 的 {layer} 层存在多个不同铜形，无法安全合并。"
                )
            continue
        seen[layer] = pad
        for mapped in _padstack_layers(layer):
            ps.layers.append(
                PadstackLayer(
                    layer=mapped,
                    shape=_map_shape(pad.shape, pad.w_mm, pad.h_mm),
                    w_mm=pad.w_mm,
                    h_mm=pad.h_mm,
                    polygon_mm=list(pad.polygon_mm),
                )
            )
    return ps


def _padstack_layers(copper_layer: str) -> list[str]:
    """由铜层推出要写进 padstack 的层集合 (铜 + 阻焊 + 钢网)。"""
    if copper_layer == "TOP":
        return ["TOP", "TOP_SOLDERMASK", "TOP_PASTE"]
    if copper_layer == "BOTTOM":
        return ["BOTTOM", "BOTTOM_SOLDERMASK", "BOTTOM_PASTE"]
    # MULTI_LAYER: 通孔, 顶底都写
    if copper_layer == "MULTI_LAYER":
        return ["TOP", "BOTTOM", "DEFAULT_INTERNAL", "TOP_SOLDERMASK", "BOTTOM_SOLDERMASK"]
    raise UnsupportedGeometryError(f"不支持的焊盘层: {copper_layer}")


def _map_shape(shape: str, w_mm: float = 0.0, h_mm: float = 0.0) -> str:
    """EasyEDA 焊盘形状 → padstack 形状。ELLIPSE 在 w==h 时是圆。"""
    s = (shape or "").upper()
    if s == "ELLIPSE":
        return "CIRCLE" if abs(w_mm - h_mm) < 1e-4 else "OBLONG"
    return {
        "RECT": "RECT",
        "CIRCLE": "CIRCLE",
        "OVAL": "OBLONG",
        "ROUNDRECT": "ROUNDED_RECT",
        "POLYGON": "SHAPE",
        "REGULAR_POLYGON": "SHAPE",
    }.get(s, "SHAPE")

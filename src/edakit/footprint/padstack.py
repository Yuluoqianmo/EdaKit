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
import math

from ..errors import UnsupportedGeometryError
from ..easyeda.model import Pad, Padstack, PadstackLayer

# 铜层集合 (决定谁算铜形)
_COPPER_LAYERS = {"TOP", "BOTTOM", "MULTI_LAYER"}
APERTURE_LAYERS = {'TOP_PASTE','BOTTOM_PASTE','TOP_SOLDERMASK','BOTTOM_SOLDERMASK'}


def is_aperture(pad):
    return bool(pad.layers) and set(pad.layers).issubset(APERTURE_LAYERS) and pad.hole_mm == 0


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
        if is_aperture(pad):
            continue
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
        hole_plated=group[0].hole_plated,
        mechanical=not group[0].number and not group[0].hole_plated and group[0].hole_mm > 0,
    )
    if any(p.hole_plated != ps.hole_plated for p in group if p.hole_mm):
        raise UnsupportedGeometryError(f'焊盘 {name} 镀孔属性不一致。')
    source = next((p for p in group if p.hole_mm), group[0])
    if source.slot_length_mm > source.hole_mm + .0001:
        # The source stores the two endpoints of the slot centerline in global XY.
        # Use their direction, including for rotated pads; length is the overall length.
        if len(source.hole_points_mm) != 2:
            raise UnsupportedGeometryError(f'焊盘 {name} 槽孔缺少明确的中心线端点。')
        a, b = source.hole_points_mm
        angle = math.radians(-ps.rotation_deg)
        dx, dy = b[0]-a[0], b[1]-a[1]
        dx, dy = dx*math.cos(angle)-dy*math.sin(angle), dx*math.sin(angle)+dy*math.cos(angle)
        if min(abs(dx), abs(dy)) > .001:
            raise UnsupportedGeometryError(f'焊盘 {name} 槽孔方向与焊盘坐标轴不一致。')
        ps.slot_width_mm, ps.slot_height_mm = ((source.slot_length_mm, ps.drill_mm)
            if abs(dx) > abs(dy) else (ps.drill_mm, source.slot_length_mm))
        ox, oy = (a[0]+b[0])/2-ps.x_mm, (a[1]+b[1])/2-ps.y_mm
        ps.drill_offset_x_mm = ox*math.cos(angle)-oy*math.sin(angle)
        ps.drill_offset_y_mm = ox*math.sin(angle)+oy*math.cos(angle)

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
        shape = _map_shape(pad.shape, pad.w_mm, pad.h_mm)
        local = []
        if shape == 'SHAPE':
            from .geometry import polygon
            a = math.radians(-pad.rotation_deg)
            for x, y in pad.polygon_mm:
                x, y = x-pad.x_mm, y-pad.y_mm
                local.append((x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a)))
            poly = polygon(local)
            local = list(poly.exterior.coords)[:-1]
        for mapped in _padstack_layers(layer):
            if mapped.endswith('_PASTE') and not pad.paste_enabled:
                continue
            if mapped.endswith('_SOLDERMASK') and not pad.solder_enabled:
                continue
            expansion = (pad.solder_expansion_mm if mapped.endswith('_SOLDERMASK') else
                         pad.paste_expansion_mm if mapped.endswith('_PASTE') else 0)
            w, h = pad.w_mm+2*expansion, pad.h_mm+2*expansion
            vertices = local
            if shape == 'SHAPE':
                poly = polygon(local).buffer(expansion, join_style='mitre') if expansion else polygon(local)
                if poly.is_empty or poly.geom_type != 'Polygon' or poly.interiors:
                    raise UnsupportedGeometryError(f'焊盘 {name} 开窗参数导致空形状或多片形状。')
                vertices = list(poly.exterior.coords)[:-1]
                w, h = 2*max(abs(x) for x,y in vertices), 2*max(abs(y) for x,y in vertices)
            if expansion and (w <= 0 or h <= 0):
                raise UnsupportedGeometryError(f'焊盘 {name} 开窗尺寸必须大于零。')
            ps.layers.append(
                PadstackLayer(
                    layer=mapped,
                    shape=shape,
                    w_mm=w,
                    h_mm=h,
                    polygon_mm=vertices,
                    radius_mm=max(0, pad.corner_radius_mm+expansion) if shape == 'ROUNDED_RECT' else 0,
                )
            )
    return ps


def footprint_padstacks(footprint):
    result = merge_padstacks(footprint.pads)
    for i, prim in enumerate(footprint.primitives):
        if prim.kind == 'HOLE' and prim.geom:
            g = prim.geom
            result.append(Padstack(name=f'@HOLE{i}', drill_mm=g['hole_mm'], hole_plated=False,
                x_mm=g['x_mm'], y_mm=g['y_mm'], mechanical=True))
    return result


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

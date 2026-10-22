"""把解析出的几何画成 SVG。

== 为什么不直接用立创的预览图 ==
EasyEDA 的 `api/products/{C}/svgs` 端点当前返回 403 (CloudFront 拦截)。而且就算能用，
我们也要用**自己解析出来的几何**画 —— 这样预览图本身就是解析正确性的可视化验证:
预览跟立创网页对得上，说明解析对；对不上，一眼就能看出。

== 坐标 ==
  符号: 解析时已 Y 翻转 (上为正)  → SVG y = -y_mm
  封装: 解析后 Y 与 SVG 同向 (下为正) → SVG y = +y_mm
viewBox 由所有图元的外接框决定，四周留 padding。
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from ..easyeda.model import Footprint, Symbol

# 颜色 (EAGLE/KiCad 风格)
C_BODY = "#7F0000"  # 元件外形 (深红)
C_PIN = "#00007F"  # 引脚 (深蓝)
C_PIN_NAME = "#5A5A5A"
C_SILK = "#E8A33D"  # 丝印 (橙)
C_PAD = "#B58900"  # 焊盘 (金)
C_PAD_HOLE = "#FFFFFF"
C_TEXT = "#333333"
C_CRT = "#00A0A0"  # 装配层 (青)

PAD_PADDING_MM = 1.5


class _Box:
    """累积外接框。"""

    def __init__(self) -> None:
        self.xs: list[float] = []
        self.ys: list[float] = []

    def add(self, x: float, y: float) -> None:
        self.xs.append(x)
        self.ys.append(y)

    def add_rect(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.add(x1, y1)
        self.add(x2, y2)

    def expanded(self, pad: float = PAD_PADDING_MM) -> tuple[float, float, float, float]:
        if not self.xs:
            return (0.0, 0.0, 10.0, 10.0)
        return (
            min(self.xs) - pad,
            min(self.ys) - pad,
            max(self.xs) + pad,
            max(self.ys) + pad,
        )


def _svg_open(w: float, h: float, x: float, y: float) -> list[str]:
    """开一个**正方形** viewBox，内容居中。

    之前 viewBox 直接取图形外接框（可能是 9.6×9.0 这种偏宽的比例），
    放进商城固定 260px 高的框里时内容会贴边。正方形 + 显式宽高能让
    浏览器按 `object-fit: contain` 居中显示（封装预览「顶左上角」的修法）。
    """
    side = max(w, h, 1.0) * 1.04  # 小封装也充分利用预览区域
    vx = x + w / 2 - side / 2
    vy = y + h / 2 - side / 2
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx:.3f} {vy:.3f} {side:.3f} {side:.3f}" '
        f'width="1024" height="1024" preserveAspectRatio="xMidYMid meet">',
    ]


# --------------------------------------------------------------------------- #
# 符号
# --------------------------------------------------------------------------- #
def render_symbol_svg(sym: Symbol) -> str:
    """渲染原理图符号。Y 取反 (符号坐标系上为正, SVG 下为正)。"""
    box = _Box()
    body: list[str] = []
    labels: list[str] = []
    from ..symbol.capture_lib import pin_names_hidden
    hide_names = pin_names_hidden(sym)

    # 预览要和真正放进 Capture 的符号一致：按 EasyEDA 原始布局画。
    # （2026-10-19：Capture 生成器已改成 IsLong=1 + Y 翻转，竖排名字由 Capture 自己旋转；
    # 不再做「按名字宽度疏排」，否则预览和实际符号会不一致。）
    def Y(v: float) -> float:
        return -v

    for prim in sym.primitives:
        g = prim.geom
        k = prim.kind
        if k == "R" and "w_mm" in g:
            x1, y1 = g["x_mm"], Y(g["y_mm"])
            x2, y2 = g["x2_mm"], Y(g["y2_mm"])
            box.add_rect(x1, y1, x2, y2)
            body.append(
                f'<rect x="{min(x1,x2):.3f}" y="{min(y1,y2):.3f}" '
                f'width="{abs(x2-x1):.3f}" height="{abs(y2-y1):.3f}" '
                f'fill="none" stroke="{C_BODY}" stroke-width="0.25"/>'
            )
        elif k == "C" and "r_mm" in g:
            cx, cy, r = g["x_mm"], Y(g["y_mm"]), g["r_mm"]
            box.add_rect(cx - r, cy - r, cx + r, cy + r)
            body.append(
                f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{r:.3f}" '
                f'fill="none" stroke="{C_BODY}" stroke-width="0.25"/>'
            )
        elif k == "E" and "rx_mm" in g:
            cx, cy = g["x_mm"], Y(g["y_mm"])
            rx, ry = g["rx_mm"], g["ry_mm"]
            box.add_rect(cx - rx, cy - ry, cx + rx, cy + ry)
            body.append(
                f'<ellipse cx="{cx:.3f}" cy="{cy:.3f}" rx="{rx:.3f}" ry="{ry:.3f}" '
                f'fill="none" stroke="{C_BODY}" stroke-width="0.25"/>'
            )
        elif k in ("PL", "PG", "PT") and g.get("points_mm"):
            pts = g["points_mm"]
            pairs = [(pts[i], Y(pts[i + 1])) for i in range(0, len(pts) - 1, 2)]
            for px, py in pairs:
                box.add(px, py)
            d = " ".join(f"{px:.3f},{py:.3f}" for px, py in pairs)
            tag = "polygon" if k == "PG" else "polyline"
            fill = C_BODY if k == "PG" else "none"
            body.append(
                f'<{tag} points="{d}" fill="{fill}" stroke="{C_BODY}" stroke-width="0.25"/>'
            )
        elif k == "T" and "text" in g:
            tx, ty = g["x_mm"], Y(g["y_mm"])
            box.add(tx, ty)
            labels.append(
                f'<text x="{tx:.3f}" y="{ty:.3f}" font-size="2.2" fill="{C_TEXT}" '
                f'text-anchor="middle" dominant-baseline="middle">{escape(str(g["text"]))}</text>'
            )

    # 引脚
    for pin in sym.pins:
        px, py = pin.x_mm, Y(pin.y_mm)
        length = pin.length_mm or 2.54
        ang = pin.orientation_deg
        ex, ey = px, py
        if abs(ang - 0.0) < 1e-6:  # 朝右
            ex = px + length
        elif abs(ang - 180.0) < 1e-6:  # 朝左
            ex = px - length
        elif abs(ang - 90.0) < 1e-6:  # 朝上 (SVG 里向上是 y 减小)
            ey = py - length
        elif abs(ang - 270.0) < 1e-6:  # 朝下
            ey = py + length
        box.add(px, py)
        box.add(ex, ey)
        body.append(
            f'<line x1="{px:.3f}" y1="{py:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" '
            f'stroke="{C_PIN}" stroke-width="0.22"/>'
        )
        vertical = abs(ex - px) < 1e-9 and abs(ey - py) > 1e-9
        if not hide_names and pin.name and pin.name not in ("~",):
            if vertical:
                # 竖直引脚（顶部/底部）：名字必须竖排（旋转 -90°，自下而上阅读）。
                # 立创/EasyEDA 的 QFN 符号就是竖排；若横排，2.54mm 引脚间距下
                # 长名字（VREG_VOUT、IOVDD…）会互相压字。
                # 文字块画在引脚线右侧，贴着本体边缘：rotate(-90) 后字形在锚点
                # 左侧、阅读方向向上，所以锚点取 px + 1.4 让字列落在引脚右侧。
                lx = px + 1.4
                if ey > py:
                    # 顶部引脚：本体在连接点下方（SVG y 向下），名字向下延伸
                    ly = ey + 0.5
                    anchor = "end"
                    reach = ly + len(pin.name) * 1.15
                else:
                    # 底部引脚：本体在连接点上方，名字向上延伸
                    ly = ey - 0.5
                    anchor = "start"
                    reach = ly - len(pin.name) * 1.15
                box.add(px, ly)
                box.add(px + 1.6, reach)
                labels.append(
                    f'<text x="{lx:.3f}" y="{ly:.3f}" font-size="1.8" '
                    f'fill="{C_PIN_NAME}" text-anchor="{anchor}" '
                    f'transform="rotate(-90 {lx:.3f} {ly:.3f})">{escape(pin.name)}</text>'
                )
            else:
                # 水平引脚：名称放在本体一端的内侧
                ox = 0.6 if ex >= px else -0.6
                anchor = "start" if ex >= px else "end"
                box.add(ex + ox, ey - 0.25)
                box.add(ex + ox + (1.1 * len(pin.name) if anchor == "start" else -1.1 * len(pin.name)), ey - 0.25)
                labels.append(
                    f'<text x="{ex + ox:.3f}" y="{ey - 0.25:.3f}" font-size="1.8" '
                    f'fill="{C_PIN_NAME}" text-anchor="{anchor}">{escape(pin.name)}</text>'
                )
        if pin.number:
            mx, my = (px + ex) / 2, (py + ey) / 2
            if vertical:
                # 编号竖排，画在引脚线左侧
                nx = px - 0.35
                labels.append(
                    f'<text x="{nx:.3f}" y="{my:.3f}" font-size="1.6" '
                    f'fill="{C_PIN_NAME}" text-anchor="middle" '
                    f'transform="rotate(-90 {nx:.3f} {my:.3f})">{escape(pin.number)}</text>'
                )
            else:
                labels.append(
                    f'<text x="{mx:.3f}" y="{my - 0.45:.3f}" font-size="1.6" '
                    f'fill="{C_PIN_NAME}" text-anchor="middle">{escape(pin.number)}</text>'
                )

    x, y, x2, y2 = box.expanded()
    out = _svg_open(x2 - x, y2 - y, x, y)
    out += body + labels
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 封装
# --------------------------------------------------------------------------- #
def render_footprint_svg(fp: Footprint) -> str:
    """渲染 PCB 封装俯视图。Y 与 SVG 同向，不翻转。"""
    box = _Box()
    body: list[str] = []
    from ..footprint.geometry import graphic_regions, pieces
    from ..errors import UnsupportedGeometryError
    try:
        filled = graphic_regions(fp)
    except (UnsupportedGeometryError, ValueError):
        filled = []
    for layer, geometry in filled:
        color = C_SILK if 'SILK' in layer else '#8b929b' if 'PASTE' in layer else C_CRT
        for poly in pieces(geometry):
            paths = []
            for ring in [poly.exterior, *poly.interiors]:
                pts = list(ring.coords)
                paths.append('M '+' L '.join(f'{x:.4f} {y:.4f}' for x,y in pts)+' Z')
                for x,y in pts:box.add(x,y)
            body.append(f'<path d="{" ".join(paths)}" fill="{color}" fill-rule="evenodd" opacity="0.45"/>')

    # 丝印 / 装配线
    for layer, pts in fp.lines:
        if len(pts) < 2:
            continue
        color = C_SILK if "SILK" in layer else C_CRT
        for px, py in pts:
            box.add(px, py)
        d = " ".join(f"{px:.3f},{py:.3f}" for px, py in pts)
        body.append(
            f'<polyline points="{d}" fill="none" stroke="{color}" '
            f'stroke-width="0.12" stroke-linecap="round"/>'
        )
    for layer, cx, cy, r in fp.circles:
        if ("SILK" not in layer and "ASSEMBLY" not in layer and "OUTLINE" not in layer
                and layer not in {"LeadShapeLayer", "ComponentShapeLayer", "ComponentPolarityLayer"}):
            continue
        color = C_SILK if "SILK" in layer else C_CRT
        box.add_rect(cx - r, cy - r, cx + r, cy + r)
        body.append(
            f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{r:.3f}" fill="none" '
            f'stroke="{color}" stroke-width="0.12"/>'
        )

    for primitive in fp.primitives:
        if primitive.kind not in {'RECT', 'RECTANGLE'} or 'x2_mm' not in primitive.geom:
            continue
        g = primitive.geom
        x, y, xx, yy = (g[k] for k in ('x_mm', 'y_mm', 'x2_mm', 'y2_mm'))
        color = C_SILK if 'SILK' in g['layer'] else C_CRT
        box.add_rect(min(x,xx), min(y,yy), max(x,xx), max(y,yy))
        fill = color if g['filled'] else 'none'
        body.append(f'<rect x="{min(x,xx):.4f}" y="{min(y,yy):.4f}" '
                    f'width="{abs(xx-x):.4f}" height="{abs(yy-y):.4f}" '
                    f'fill="{fill}" stroke="{color}" stroke-width="{g["width_mm"]:.4f}"/>')

    # Native circular arcs, using the same endpoint geometry as Allegro output.
    from ..easyeda.arcs import arc_bounds
    for primitive in fp.primitives:
        if primitive.kind != 'ARC':
            continue
        g = primitive.geom
        color = C_SILK if 'SILK' in g.get('layer', '') else C_CRT
        for arc in g.get('arcs', []):
            sx, sy = arc['start']
            ex, ey = arc['end']
            radius = arc['radius']
            for x, y in arc_bounds(arc):
                box.add(x, y)
            body.append(f'<path d="M {sx:.4f} {sy:.4f} A {radius:.4f} {radius:.4f} '
                        f'0 {int(arc["large"])} {int(not arc["clockwise"])} {ex:.4f} {ey:.4f}" '
                        f'fill="none" stroke="{color}" stroke-width="{g.get("width_mm", .12):.4f}"/>')

    # 焊盘 (按 1..n 顺序，便于对齐)
    def sort_key(p):
        try:
            return (0, int("".join(ch for ch in p.number if ch.isdigit()) or 0))
        except ValueError:
            return (1, 0)

    for pad in sorted(fp.pads, key=sort_key):
        from ..footprint.padstack import is_aperture
        if is_aperture(pad):
            continue
        w = max(pad.w_mm, 0.01)
        h = max(pad.h_mm, 0.01)
        x1, y1 = pad.x_mm - w / 2, pad.y_mm - h / 2
        box.add_rect(x1, y1, x1 + w, y1 + h)
        shape = (pad.shape or "RECT").upper()
        rot = f' transform="rotate({pad.rotation_deg:.1f} {pad.x_mm:.3f} {pad.y_mm:.3f})"' if pad.rotation_deg else ""
        if shape == "CIRCLE" or (shape == "ELLIPSE" and abs(w - h) < 1e-4):
            body.append(
                f'<circle cx="{pad.x_mm:.3f}" cy="{pad.y_mm:.3f}" r="{w/2:.3f}" '
                f'fill="{C_PAD}" stroke="#6B5200" stroke-width="0.03"{rot}/>'
            )
        elif shape in {'POLYGON', 'REGULAR_POLYGON'}:
            pts = ' '.join(f'{x:.4f},{y:.4f}' for x,y in pad.polygon_mm)
            for x,y in pad.polygon_mm:
                box.add(x,y)
            body.append(f'<polygon points="{pts}" fill="{C_PAD}" stroke="#6B5200" stroke-width="0.03"/>')
        else:
            radius = (min(w,h)/2 if shape in {'OVAL','ELLIPSE'} else
                      pad.corner_radius_mm if shape == 'ROUNDRECT' else 0)
            body.append(
                f'<rect x="{x1:.3f}" y="{y1:.3f}" width="{w:.3f}" height="{h:.3f}" '
                f'rx="{radius:.3f}" fill="{C_PAD}" stroke="#6B5200" '
                f'stroke-width="0.03"{rot}/>'
            )
        # pin-1 标记
        if pad.number == "1":
            body.append(
                f'<circle cx="{pad.x_mm:.3f}" cy="{pad.y_mm:.3f}" r="{min(w,h)*0.18:.3f}" '
                f'fill="none" stroke="#C00000" stroke-width="0.05"/>'
            )
        if pad.number and len(fp.pads) <= 64:
            label_size = min(0.6, max(0.08, min(w, h) * 0.7 / max(1, len(pad.number) * 0.6)))
            body.append(
                f'<text x="{pad.x_mm:.3f}" y="{pad.y_mm + label_size * 0.35:.3f}" font-size="{label_size:.3f}" '
                f'fill="#333" text-anchor="middle">{escape(pad.number)}</text>'
            )

    for ps in fp.padstacks:
        if ps.drill_mm <= 0:
            continue
        w,h = ps.slot_width_mm or ps.drill_mm, ps.slot_height_mm or ps.drill_mm
        x,y = ps.drill_offset_x_mm-w/2, ps.drill_offset_y_mm-h/2
        body.append(f'<rect x="{x:.4f}" y="{y:.4f}" width="{w:.4f}" height="{h:.4f}" '
                    f'rx="{min(w,h)/2:.4f}" fill="{C_PAD_HOLE}" stroke="#6B5200" stroke-width="0.03" '
                    f'transform="translate({ps.x_mm:.4f} {ps.y_mm:.4f}) rotate({ps.rotation_deg:.4f})"/>')
        box.add_rect(ps.x_mm-max(w,h)/2,ps.y_mm-max(w,h)/2,ps.x_mm+max(w,h)/2,ps.y_mm+max(w,h)/2)
    x, y, x2, y2 = box.expanded(0.8)
    out = _svg_open(x2 - x, y2 - y, x, y)
    out += body
    out.append("</svg>")
    return "\n".join(out)

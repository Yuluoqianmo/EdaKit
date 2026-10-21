"""SVG 预览渲染测试。

预览图是**解析正确性的可视化证据**: 自研渲染器画出来的几何必须和立创网页一致。
这里做结构性断言 (XML 合法、引脚/焊盘数量对得上、通孔有钻孔圈)。
"""

import json
import re
import xml.dom.minidom as minidom

from conftest import DATA

from edakit.easyeda.parse import parse_component
from edakit.render import render_footprint_svg, render_symbol_svg


def _text_elements(svg: str) -> list[str]:
    return re.findall(r"<text [^>]*>[^<]*</text>", svg)


def _text_for(svg: str, label: str) -> list[str]:
    return [t for t in _text_elements(svg) if f">{label}<" in t]



def _comp(name: str):
    payload = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    return parse_component(name, payload)


def test_symbol_svg_wellformed_and_counts():
    comp = _comp("C2040")
    svg = render_symbol_svg(comp.symbol)
    minidom.parseString(svg)  # 合法 XML
    assert svg.startswith("<svg")
    assert "viewBox=" in svg
    # 每个引脚一条线
    assert svg.count("<line ") == len(comp.symbol.pins)
    # 引脚名/号有文字标注
    assert "<text " in svg


def test_symbol_svg_rotates_vertical_pin_names():
    """竖直引脚（顶部/底部）的名字必须竖排，否则 2.54mm 间距下长名字互相压字。

    回归背景（2026-10-19）：RP2040 顶部 12 个引脚（DVDD/IOVDD/VREG_VOUT…）按
    2.54mm 间距排列，横排名字在 Capture 和浏览器预览里都渲染成一片糊。
    """
    comp = _comp("C2040")
    svg = render_symbol_svg(comp.symbol)
    minidom.parseString(svg)

    # 长名字 + 竖直引脚 → 必须带 rotate(-90)
    for label in ("VREG_VOUT", "ADC_AVDD", "TESTEN"):
        elements = _text_for(svg, label)
        assert elements, f"{label} 应有文字标注"
        assert all("rotate(-90" in t for t in elements), f"{label} 应竖排"

    # 水平引脚的名字保持横排
    for label in ("QSPI_SS", "USB_DP"):
        elements = _text_for(svg, label)
        assert elements, f"{label} 应有文字标注"
        assert all("rotate(-90" not in t for t in elements), f"{label} 不应旋转"

    # 竖直引脚的编号也竖排：12 个 270° + 2 个 90° = 14 个引脚，至少各有一个旋转元素
    vertical = [
        p for p in comp.symbol.pins
        if abs(p.orientation_deg - 90) < 1e-6 or abs(p.orientation_deg - 270) < 1e-6
    ]
    assert svg.count("rotate(-90") >= len(vertical)


def test_symbol_svg_vertical_name_columns_do_not_overlap():
    """同一条边上的相邻竖直引脚，名字列锚点间距应不小于 2.0mm。"""
    comp = _comp("C2040")
    svg = render_symbol_svg(comp.symbol)
    # (y, x)：顶部/底部名字列的 y 不同，分边比较，避免跨边误判
    cols: dict[float, list[float]] = {}
    for m in re.finditer(
        r'<text x="([\d.-]+)" y="([\d.-]+)" font-size="1.8"[^>]*rotate\(-90', svg
    ):
        x, y = round(float(m.group(1)), 2), round(float(m.group(2)), 2)
        cols.setdefault(y, []).append(x)
    assert len(cols) == 2  # 顶部 + 底部
    for y, xs in cols.items():
        xs = sorted(set(xs))
        gaps = [b - a for a, b in zip(xs, xs[1:])]
        assert all(g >= 2.0 for g in gaps), f"y={y} 处竖直名字列过密: {gaps}"




def test_symbol_svg_escapes_text():
    comp = _comp("C2040")
    svg = render_symbol_svg(comp.symbol)
    # 不会有裸的 & 破坏 XML (minidom 已经能把关，这里再看没有未转义的裸 &)
    assert "&<" not in svg


def _viewbox(svg: str) -> tuple[float, float, float, float]:
    m = re.search(r'viewBox="([\d.eE+-]+) (-?[\d.eE+-]+) (-?[\d.eE+-]+) (-?[\d.eE+-]+)"', svg)
    assert m, "svg 缺 viewBox"
    return tuple(float(g) for g in m.groups())


def test_svg_viewbox_is_square_1024():
    """正方形 viewBox + 显式 1024×1024，商城固定高度的框里内容才会居中。

    回归背景（2026-10-19）：封装预览在商城里「顶左上角」，是因为
    viewBox 直接取了外接框（偏宽），再被 CSS 拉伸/裁切。
    """
    comp = _comp("C2040")
    for svg in (render_symbol_svg(comp.symbol), render_footprint_svg(comp.footprint)):
        vx, vy, vw, vh = _viewbox(svg)
        assert abs(vw - vh) < 1e-6, f"viewBox 不是正方形: {vw}×{vh}"
        assert 'width="1024"' in svg and 'height="1024"' in svg
        assert 'preserveAspectRatio="xMidYMid meet"' in svg


def test_footprint_svg_smd_has_rects_or_circles():
    comp = _comp("C2040")
    svg = render_footprint_svg(comp.footprint)
    minidom.parseString(svg)
    # 57 个焊盘 → 每个至少一个几何图元
    total = svg.count("<rect ") + svg.count("<circle ")
    assert total >= len(comp.footprint.pads)
    # 有 pin-1 标记
    assert "#C00000" in svg


def test_footprint_svg_tht_draws_drill_holes():
    comp = _comp("C2337")
    assert comp.footprint is not None
    holes = [p for p in comp.footprint.pads if p.hole_mm > 0]
    assert holes, "C2337 应是通孔元件"
    svg = render_footprint_svg(comp.footprint)
    minidom.parseString(svg)
    # 每个通孔焊盘画一个白色钻孔圈
    assert svg.count('fill="#FFFFFF"') >= len(holes)

def test_dense_footprint_labels_fit_inside_small_pads():
    comp = _comp('C2040')
    svg = render_footprint_svg(comp.footprint)
    labels = _text_elements(svg)
    for pad in comp.footprint.pads:
        label = next(t for t in labels if t.endswith('>' + pad.number + '</text>'))
        font = float(re.search(r'font-size="([0-9.]+)"', label).group(1))
        assert font <= min(pad.w_mm, pad.h_mm) + 0.001

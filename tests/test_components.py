"""多元件回归测试 —— 覆盖 SMD、通孔(THT) 两类, 期望值取自 easyeda2kicad 实测。

  C25804 0603 电阻: pad 2 @ (0.753, 0) 0.807x0.864 (KiCad 打印 0.75)
  C2337  40P 排针  : pad 1 @ (-49.53, 0) 1.700x1.524 drill 1.100; pad 2 圆
"""

import json

from conftest import DATA

from edakit.easyeda.parse import parse_component
from edakit.footprint.padstack import merge_padstacks


def _comp(cid):
    payload = json.loads((DATA / f"{cid}.json").read_text(encoding="utf-8"))
    return parse_component(cid, payload)


def test_smd_resistor_geometry():
    comp = _comp("C25804")
    fp = comp.footprint
    assert fp.name.startswith("R0603") or "0603" in fp.name
    assert len(fp.pads) == 2
    pads = {p.number: p for p in fp.pads}
    assert abs(pads["2"].x_mm - 0.753) < 0.01
    assert abs(pads["2"].w_mm - 0.806) < 0.01
    # 2 引脚 SMD, 无钻孔
    assert all(p.hole_mm == 0 for p in fp.pads)


def test_tht_hole_is_diameter():
    comp = _comp("C2337")
    fp = comp.footprint
    assert fp.is_smd is False
    assert len(fp.pads) == 40
    p1 = next(p for p in fp.pads if p.number == "1")
    # hole_radius=2.1654 单位 → 半径 0.55mm → 直径 1.10mm
    assert abs(p1.hole_mm - 1.100) < 0.01
    assert "MULTI_LAYER" in p1.layers


def test_tht_padstack_has_no_paste():
    comp = _comp("C2337")
    ps = comp.footprint.padstacks[0]
    layers = {lay.layer for lay in ps.layers}
    # 通孔不上钢网
    assert "TOP_PASTE" not in layers and "BOTTOM_PASTE" not in layers
    assert {"TOP", "BOTTOM"} <= layers
    assert ps.drill_mm > 0


def test_pin1_rect_pads_round():
    comp = _comp("C2337")
    ps1 = next(p for p in comp.footprint.padstacks if p.name == "1")
    ps2 = next(p for p in comp.footprint.padstacks if p.name == "2")
    # pin1 是方的, 其余是圆 (ELLIPSE 等边)
    assert ps1.layers[0].shape == "RECT"
    assert ps2.layers[0].shape == "CIRCLE"


def test_merge_rejects_inconsistent_positions():
    from edakit.errors import UnsupportedGeometryError
    from edakit.easyeda.model import Pad

    a = Pad(number="1", x_mm=0.0, y_mm=0.0, w_mm=1.0, h_mm=1.0, layers=["TOP"])
    b = Pad(number="1", x_mm=5.0, y_mm=0.0, w_mm=1.0, h_mm=1.0, layers=["TOP"])
    try:
        merge_padstacks([a, b])
    except UnsupportedGeometryError:
        return
    raise AssertionError("应拒绝位置不一致的合并")

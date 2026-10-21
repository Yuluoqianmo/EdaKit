"""解析器测试 —— 用真实 C2040 (RP2040) 数据, 期望值取自 easyeda2kicad 的实测输出。

参照值 (easyeda2kicad v1.0.1, 2026-10-16 实测):
  KiCad 符号: bbox 中心 (400, 290); 引脚 9 GPIO7 @ (31.75, 15.24) 角 180; 矩形 (-29.21, 48.26)
  KiCad 封装: pad 1 @ (-3.42, -2.60) 0.85x0.20; pad 57 (EP) @ (0,0) 3.10x3.10
"""

import json

from conftest import DATA

from edakit.easyeda.parse import parse_component, split_shape


def _load():
    payload = json.loads((DATA / "C2040.json").read_text(encoding="utf-8"))
    return parse_component("C2040", payload)


def test_split_shape():
    p = split_shape("R~1~2~3")
    assert p.kind == "R"
    assert p.fields == ["R", "1", "2", "3"]


def test_component_identity():
    comp = _load()
    assert comp.title == "RP2040"
    assert comp.symbol.name == "RP2040"
    assert comp.symbol.prefix == "U?"


def test_symbol_origin_is_bbox_center():
    sym = _load().symbol
    assert sym.origin == (400.0, 290.0)


def test_symbol_pins_exact():
    sym = _load().symbol
    assert len(sym.pins) == 57
    by_num = {p.number: p for p in sym.pins}
    p9 = by_num["9"]
    assert p9.name == "GPIO7"
    assert p9.electrical_type == "bidirectional"
    # (525-400)*0.254 = 31.75; -(230-290)*0.254 = 15.24
    assert abs(p9.x_mm - 31.75) < 1e-6
    assert abs(p9.y_mm - 15.24) < 1e-6
    assert abs(p9.orientation_deg - 180.0) < 1e-6  # (0 + 180) % 360
    assert abs(p9.length_mm - 2.54) < 1e-6


def test_symbol_rect_exact():
    sym = _load().symbol
    rects = [p for p in sym.primitives if p.kind == "R"]
    assert len(rects) == 1
    g = rects[0].geom
    assert abs(g["x_mm"] - (-29.21)) < 1e-6  # (285-400)*0.254
    assert abs(g["y_mm"] - 48.26) < 1e-6  # -(100-290)*0.254
    assert abs(g["w_mm"] - 58.42) < 1e-6  # 230*0.254


def test_footprint_name_from_cpara():
    fp = _load().footprint
    assert fp.name == "LQFN-56_L7.0-W7.0-P0.4-EP"


def test_footprint_pads_exact():
    fp = _load().footprint
    assert len(fp.pads) == 57
    by_num = {p.number: p for p in fp.pads}
    p1 = by_num["1"]
    assert abs(p1.x_mm - (-3.42)) < 0.01
    assert abs(p1.y_mm - (-2.60)) < 0.01
    assert abs(p1.w_mm - 0.85) < 0.01
    assert abs(p1.h_mm - 0.20) < 0.01
    assert p1.layers == ["TOP"]
    ep = by_num["57"]
    assert abs(ep.x_mm) < 0.01 and abs(ep.y_mm) < 0.01
    assert abs(ep.w_mm - 3.10) < 0.01


def test_footprint_padstacks_merged():
    fp = _load().footprint
    # 每个引脚一个 padstack (SMD 顶层单层)
    assert len(fp.padstacks) == 57
    for ps in fp.padstacks:
        layers = {lay.layer for lay in ps.layers}
        assert "TOP" in layers and "TOP_SOLDERMASK" in layers


def test_footprint_tracks_layer_and_width():
    fp = _load().footprint
    assert fp.lines, "应有丝印线段"
    layer, pts = fp.lines[0]
    assert layer == "TOP_SILK"  # 层号 3
    assert len(pts) >= 2


def test_model3d():
    comp = _load()
    m = comp.model3d
    assert m is not None
    assert m.uuid.startswith("76b360a9")
    # c_origin == 封装原点 → 相对偏移 (0,0)
    assert abs(m.origin_mm[0]) < 0.01 and abs(m.origin_mm[1]) < 0.01

import json
import xml.dom.minidom as minidom
import pytest

from conftest import DATA

from edakit.easyeda.parse import parse_component
from edakit.easyeda.model import PadstackLayer
from edakit.footprint.skill import generate_skill
from edakit.errors import UnsupportedGeometryError
from edakit.symbol.olb_xml import generate_olb_xml
from edakit.symbol.tcl import generate_capture_run_tcl, generate_place_tcl
from edakit.threed.mapping import build_map_xml, calibrate


def _comp():
    payload = json.loads((DATA / "C2040.json").read_text(encoding="utf-8"))
    return parse_component("C2040", payload)


def test_olb_xml_is_wellformed():
    comp = _comp()
    xml = generate_olb_xml(comp.symbol, footprint_name="QFN-56")
    dom = minidom.parseString(xml)  # 不抛异常即格式正确
    assert dom.documentElement.tagName == "CaptureLibrary"
    assert "PCB Footprint" in xml
    assert "QFN-56" in xml
    # 引脚用 Capture 取向 (180 而非 0)
    assert 'Orientation="180.0"' in xml
    # 引脚电气类型映射到 Capture
    assert 'Type="Bidirectional"' in xml


def test_skill_has_expected_calls():
    comp = _comp()
    il = generate_skill(comp.footprint)
    assert "axlDBCreatePadStack" in il
    assert "axlDBCreatePin" in il
    assert "axlSaveDesign" in il
    assert il.count("axlDBCreatePin") == 57
    # 不能出现幻觉函数名
    assert "axlPadstackCreate" not in il
    # 焊盘锚点应是规范化后的坐标 (≈0), 不是画布绝对值
    assert '0.0000:0.0000 (make_axlPinText ?number "57"' in il
    assert '?mode "wf"' not in il
    assert '?figureSize "' not in il
    assert "?type 'REGULAR ?figure 'RECTANGLE" in il
    assert "?figure 'OVAL" not in il  # C2040 全部是矩形，不能凭空生成椭圆焊盘。
    assert '(axlDBChangeDesignUnits "millimeters" 4)' in il
    assert '(axlSaveDesign ?noMru t)' in il
    assert 'axlPadstackToDisk' in il
    # C2040 includes lead/component solid regions; generated geometry must retain them.
    assert "axlDBCreateShape" in il
    assert il.count("solid region failed") == len(comp.footprint.solid_regions)
    # Region vertices are converted to footprint-relative millimeters.
    assert "3971.4922" not in il


def test_skill_rejects_unsupported_solid_region_curve():
    comp = _comp()
    region = comp.footprint.solid_regions[0]
    region.geom["path_supported"] = False
    region.geom["path"] = "M 0 0 C 1 1 2 2 3 3 Z"
    with pytest.raises(UnsupportedGeometryError, match="填充区域"):
        generate_skill(comp.footprint)


def test_skill_solid_boundaries_are_explicitly_closed():
    import re
    comp = _comp()
    il = generate_skill(comp.footprint)
    boundaries = re.findall(r'axlDBCreateShape \(axlPathStart \(list ([^)]+)\)', il)
    assert len(boundaries) == len(comp.footprint.solid_regions) == 116
    for boundary in boundaries:
        vertices = boundary.split()
        assert vertices[0] == vertices[-1]
        assert len(set(vertices[:-1])) >= 3
        assert all(a != b for a, b in zip(vertices, vertices[1:]))


def test_skill_already_closed_region_has_no_duplicate_edges():
    comp = _comp()
    comp.footprint.solid_regions[0].geom['points_mm'] = [0, 0, 1, 0, 1, 1, 0, 0, 0, 0]
    il = generate_skill(comp.footprint)
    assert '(list 0.0000:0.0000 1.0000:0.0000 1.0000:1.0000 0.0000:0.0000)' in il


@pytest.mark.parametrize('points', [
    [0, 0, 1, 0, 2, 0],
    [0, 0, 0.00001, 0, 0, 0.00001],
])
def test_skill_rejects_degenerate_region_at_output_precision(points):
    comp = _comp()
    comp.footprint.solid_regions[0].geom['points_mm'] = points
    with pytest.raises(UnsupportedGeometryError, match='退化'):
        generate_skill(comp.footprint)


def test_skill_sets_extents_before_creating_negative_coordinate_pins():
    import re
    fp = _comp().footprint
    il = generate_skill(fp)
    assert il.index('axlDBChangeDesignUnits') < il.index('axlDBChangeDesignExtents')
    assert il.index('axlDBChangeDesignExtents') < il.index('axlDBCreatePin')
    assert '(bounds (axlGetParam "paramDesign")->bBox)' in il
    x1, y1, x2, y2 = map(float, re.findall(r'\((?:min|max) \([xy]Coord \((?:car|cadr) bounds\)\) ([\d.-]+)\)', il))
    assert x1 < 0 < x2 and y1 < 0 < y2
    for ps in fp.padstacks:
        assert x1 < ps.x_mm < x2
        assert y1 < ps.y_mm < y2


def test_skill_adds_required_refdes_before_saving_and_compiling():
    il = generate_skill(_comp().footprint)
    assert '"REF DES/SILKSCREEN_TOP" nil)' in il
    assert '"REF DES/ASSEMBLY_TOP" nil)' in il
    assert il.count('axlDBCreateText "U*"') == 2
    assert il.index('axlDBCreatePin') < il.index('axlDBCreateText "U*"')
    assert il.rindex('reference designator failed') < il.index('axlSaveDesign')
    assert il.index('axlSaveDesign') < il.index('axlCompileSymbol')


@pytest.mark.parametrize('prefix,expected', [
    ('R', 'R'), ('C', 'C'), ('L', 'L'), ('D', 'D'), ('Q', 'Q'),
    ('U', 'U'), ('J', 'J'), ('Y', 'Y'), ('TP', 'TP'),
    ('R?', 'R'), ('C*', 'C'), ('', 'U'),
])
def test_skill_refdes_uses_symbol_prefix_on_both_layers(prefix, expected):
    il = generate_skill(_comp().footprint, refdes_prefix=prefix)
    assert il.count(f'axlDBCreateText "{expected}*"') == 2
    assert il.count('axlDBCreatePin') == 57


@pytest.mark.parametrize('prefix', ['?', '*', 'R 1', 'R"', 'R\nC'])
def test_skill_rejects_invalid_refdes_prefix(prefix):
    with pytest.raises(UnsupportedGeometryError, match='位号前缀'):
        generate_skill(_comp().footprint, refdes_prefix=prefix)


def test_skill_uses_square_for_equal_rect_dimensions():
    il = generate_skill(_comp().footprint)
    assert "?figure 'SQUARE ?figureSize 3.1000:3.1000" in il
    assert "?figure 'RECTANGLE ?figureSize 3.1000:3.1000" not in il
    assert "?figure 'RECTANGLE ?figureSize 0.8500:0.2000" in il


def test_skill_maps_oblong_pad_to_native_axis():
    comp = _comp()
    comp.footprint.padstacks[0].layers[0] = PadstackLayer("TOP", "OBLONG", 1.0, 0.5)
    il = generate_skill(comp.footprint)
    assert "?figure 'OBLONG_X ?figureSize 1.0000:0.5000" in il
    comp.footprint.padstacks[0].layers[0] = PadstackLayer("TOP", "OBLONG", 0.5, 1.0)
    assert "?figure 'OBLONG_Y ?figureSize 0.5000:1.0000" in generate_skill(comp.footprint)


def test_tcl_generation():
    run = generate_capture_run_tcl("d.dll", "in.xml", "out.olb", "rt.xml")
    assert "XMATIC_XML2OLB" in run and "XMATIC_OLB2XML" in run
    place = generate_place_tcl("C:/x/out.olb", "RP2040", props={"PCB Footprint": "QFN-56"})
    assert "PlacePart" in place
    assert "C:/x/out.olb" in place  # 路径必须是正斜杠


def test_capture_run_rewrites_readback_before_reporting_success():
    script = generate_capture_run_tcl('d.dll', 'input.xml', 'library.olb', 'readback.xml')
    first = script.index('XMATIC_XML2OLB "input.xml" "library.olb"')
    read = script.index('XMATIC_OLB2XML "library.olb" "readback.xml"')
    rewrite = script.index('XMATIC_XML2OLB "readback.xml" "library.olb"')
    final = script.rindex('XMATIC_OLB2XML "library.olb" "readback.xml"')
    assert first < read < rewrite < final < script.index('puts "EDAKIT_OLB_OK"')


def test_map_xml_and_calibration():
    comp = _comp()
    model = calibrate(comp.model3d, mode="easyeda2kicad")
    xml = build_map_xml(model, package_name="LQFN-56_L7.0-W7.0-P0.4-EP")
    dom = minidom.parseString(xml)
    assert dom.documentElement.tagName == "StepPackageMapping"

import json
import xml.dom.minidom as minidom

from conftest import DATA

from edakit.easyeda.parse import parse_component
from edakit.footprint.skill import generate_skill
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
    assert il.count("axlDBCreatePadStack") == 57
    # 不能出现幻觉函数名
    assert "axlPadstackCreate" not in il
    # 焊盘锚点应是规范化后的坐标 (≈0), 不是画布绝对值
    assert "(list 0.0000 0.0000)" in il  # pad 57 (EP)


def test_tcl_generation():
    run = generate_capture_run_tcl("d.dll", "in.xml", "out.olb", "rt.xml")
    assert "XMATIC_XML2OLB" in run and "XMATIC_OLB2XML" in run
    place = generate_place_tcl("C:/x/out.olb", "RP2040", props={"PCB Footprint": "QFN-56"})
    assert "PlacePart" in place
    assert "C:/x/out.olb" in place  # 路径必须是正斜杠


def test_map_xml_and_calibration():
    comp = _comp()
    model = calibrate(comp.model3d, mode="easyeda2kicad")
    xml = build_map_xml(model, package_name="LQFN-56_L7.0-W7.0-P0.4-EP")
    dom = minidom.parseString(xml)
    assert dom.documentElement.tagName == "StepPackageMapping"

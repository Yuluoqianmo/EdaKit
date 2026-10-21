"""Real capacitor payloads: preserve the body and passive terminal semantics."""
import json
import xml.etree.ElementTree as ET
import pytest
from conftest import DATA
from edakit.easyeda.parse import parse_component
from edakit.symbol.capture_lib import generate_lib_xml


@pytest.mark.parametrize("cid", ["C23630", "C170151", "C19110"])
def test_real_capacitor_has_two_plates_and_passive_pins(cid):
    component = parse_component(cid, json.loads((DATA / f"{cid}.json").read_text(encoding="utf-8")))
    xml = ET.fromstring(generate_lib_xml(component.symbol, package_name=component.symbol.name))
    lines = xml.findall(".//NormalView/Line/Defn")
    plates = set()
    for line in lines:
        x1, x2, y1, y2 = [int(line.get(key)) for key in ("x1", "x2", "y1", "y2")]
        if x1 == x2 and y1 != y2:
            plates.add((x1, min(y1, y2), max(y1, y2)))
    assert plates == {(-2, -8, 8), (2, -8, 8)}
    assert len(lines) == 4
    pins = xml.findall(".//SymbolPinScalar")
    assert len(pins) == 2 and {pin.find("Defn").get("type") for pin in pins} == {"4"}
    for pin in pins:
        for flag in ("IsClock", "IsDot", "IsLeftPointing", "IsRightPointing"):
            assert pin.find(flag + "/Defn").get("val") == "0"


def test_zero_native_result_is_not_reported_as_armed(run_plugin):
    # run_plugin lives in test_tcl_plugin; use the shared fixture alias below.
    from test_tcl_plugin import _resp
    result = run_plugin("seq=1\ncid=C2040\npart_name=RP2040\nolb_xml=@PART_XML@\n"
        "project_olb=@PROJECT_OLB@\nfollow_cursor=1\n", mode="cursor-zero")
    response = _resp(result, "1")
    assert response["ok"] == "0"
    assert "returned <0>" in response["message"]


def test_two_pin_ic_keeps_its_input_and_output_types():
    from edakit.easyeda.model import Symbol, Pin
    symbol = Symbol(name="TWO_PIN_IC", prefix="U?", pins=[
        Pin(number="1", name="IN", electrical_type="input"),
        Pin(number="2", name="OUT", electrical_type="output")])
    xml = ET.fromstring(generate_lib_xml(symbol, package_name=symbol.name))
    assert [pin.get("type") for pin in xml.findall(".//SymbolPinScalar/Defn")] == ["0", "2"]


def test_fixed_capacitor_uses_new_cache_name_but_keeps_model(tmp_path, monkeypatch):
    from edakit.config import Config
    from edakit.pipeline import stage_component
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    component = parse_component("C23630", json.loads((DATA / "C23630.json").read_text(encoding="utf-8")))
    staged = stage_component(component, Config(footprint_lib=str(tmp_path / "lib")), capture_only=True)
    xml = ET.parse(staged.symbol_xml)
    assert staged.part_name.endswith("_P9") and len(staged.part_name.encode("utf-8")) <= 31
    assert xml.find("./Package/Defn").get("name") == staged.part_name
    assert xml.find(".//PartValue/Defn").get("name") == component.symbol.name


from test_tcl_plugin import run_plugin  # fixture used by the native-result regression

"""Real split-unit MCU: preserve all physical pins when placing one symbol."""
import copy
import json
import math
import xml.etree.ElementTree as ET

import pytest
from conftest import DATA
from edakit.easyeda.parse import parse_component
from edakit.errors import ParseError
from edakit.footprint.validation import validate_pin_mapping
from edakit.symbol.capture_lib import generate_lib_xml, normalize_capture_symbol, u


def payload():
    return json.loads((DATA / 'C28730.json').read_text(encoding='utf-8'))


def test_mcu_all_units_have_matching_pcb_pins_and_native_labels():
    data = payload()
    original = copy.deepcopy(data)
    component = parse_component('C28730', data)
    assert data == original
    validate_pin_mapping(component.symbol, component.footprint)
    pins = component.symbol.pins
    assert len(pins) == 100
    assert {p.number for p in pins} == {str(i) for i in range(1, 101)}
    assert next(p for p in pins if p.number == '6').name == 'VBAT'
    assert next(p for p in pins if p.number == '100').electrical_type == 'power'
    prepared = normalize_capture_symbol(component.symbol)
    assert len({(u(p.x_mm), u(p.y_mm)) for p in prepared.pins}) == 100
    for pin in prepared.pins:
        assert u(pin.x_mm) % 10 == u(pin.y_mm) % 10 == 0
        assert pin.length_mm == pytest.approx(7.62)
        angle = math.radians(pin.orientation_deg)
        end_x = pin.x_mm + math.cos(angle) * pin.length_mm
        end_y = pin.y_mm + math.sin(angle) * pin.length_mm
        g = prepared.primitives[0].geom
        assert any(abs(a-b) < 1e-6 for a, b in (
            (end_x, g['x_mm']), (end_x, g['x2_mm']),
            (end_y, g['y_mm']), (end_y, g['y2_mm'])))
    xml = generate_lib_xml(component.symbol, package_name='C28730_TEST')
    tree = ET.fromstring(xml)
    assert len(tree.findall('.//SymbolPinScalar')) == 100
    assert len(tree.findall('.//PinNumber')) == 100
    assert not tree.findall('.//Text')
    etree = pytest.importorskip('lxml.etree')
    schema = etree.XMLSchema(etree.parse(str(DATA / 'olb.xsd')))
    assert schema.validate(etree.fromstring(xml.encode('utf-8'))), str(schema.error_log)


@pytest.mark.parametrize('damage', ['duplicate', 'missing', 'empty'])
def test_invalid_units_cannot_silently_drop_or_duplicate_pins(damage):
    data = payload()
    if damage == 'duplicate':
        data['subparts'].append(copy.deepcopy(data['subparts'][1]))
    elif damage == 'missing':
        data['subparts'] = data['subparts'][1:]
    else:
        data['subparts'][1]['dataStr'] = {}
    with pytest.raises(ParseError):
        parse_component('C28730', data)

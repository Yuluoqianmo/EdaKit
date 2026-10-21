import copy
import json
import xml.etree.ElementTree as ET

from conftest import DATA
from edakit.easyeda.model import Pin, Symbol
from edakit.easyeda.parse import parse_component
from edakit.symbol.capture_lib import generate_lib_xml, normalize_capture_symbol, u
import pytest


def test_nonpower_names_unique_without_colliding_with_existing_names():
    source = Symbol(pins=[Pin(number=str(i+1), name=name, electrical_type=kind)
        for i, (name, kind) in enumerate([
            ('NC', 'passive'), ('NC', 'passive'), ('NC1', 'input'),
            ('VCC', 'power'), ('VCC', 'power'), ('VCC', 'input')])])
    normalized = normalize_capture_symbol(source)
    assert [p.name for p in normalized.pins] == ['NC2', 'NC3', 'NC1', 'VCC', 'VCC', 'VCC1']
    assert [p.electrical_type for p in normalized.pins] == [p.electrical_type for p in source.pins]
    assert [p.number for p in normalized.pins] == [p.number for p in source.pins]


def test_c2040_unique_names_grid_no_collisions_and_source_untouched():
    source = parse_component('C2040', json.loads((DATA/'C2040.json').read_text(encoding='utf-8'))).symbol
    before = copy.deepcopy(source)
    xml = ET.fromstring(generate_lib_xml(source, package_name='RP2040_P5'))
    pins = xml.findall('.//SymbolPinScalar/Defn')
    names = [p.get('name').casefold() for p in pins]
    coords = [(int(p.get('hotptX')), int(p.get('hotptY'))) for p in pins]
    assert len(names) == len(set(names)) == len(set(coords)) == 57
    assert all(x % 10 == y % 10 == 0 for x, y in coords)
    assert all(p.get('type') == '1' for p in pins if p.get('name').startswith('IOVDD'))
    assert source == before
    assert normalize_capture_symbol(normalize_capture_symbol(source)) == normalize_capture_symbol(source)
    physical = xml.findall('.//PhysicalPart/PinNumber/Defn')
    assert {p.get('number') for p in physical} == {str(i) for i in range(1,58)}


@pytest.mark.parametrize('angle', [0, 90, 180, 270])
def test_short_source_lead_becomes_line_without_moving_body_end(angle):
    source = Symbol(pins=[Pin(number='1', name='IN', x_mm=0.73,
                             y_mm=-0.81, length_mm=0.5, orientation_deg=angle)])
    old = source.pins[0]
    prepared = normalize_capture_symbol(source)
    pin = prepared.pins[0]
    assert u(pin.x_mm) % 10 == u(pin.y_mm) % 10 == 0
    assert pin.length_mm >= 2.54 - 1e-8
    horizontal = angle in (0, 180)
    direction = 1 if angle in (0, 90) else -1
    assert ((pin.x_mm if horizontal else pin.y_mm) + direction * pin.length_mm
            == pytest.approx((old.x_mm if horizontal else old.y_mm) + direction * old.length_mm))
    assert normalize_capture_symbol(prepared) == prepared
    root = ET.fromstring(generate_lib_xml(source, package_name='LINE'))
    assert root.find('.//IsLong/Defn').get('val') == '1'

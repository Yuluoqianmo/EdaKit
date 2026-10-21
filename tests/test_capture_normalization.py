import copy
import json
import xml.etree.ElementTree as ET

from conftest import DATA
from edakit.easyeda.model import Pin, Symbol
from edakit.easyeda.parse import parse_component
from edakit.symbol.capture_lib import generate_lib_xml, normalize_capture_symbol, u


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

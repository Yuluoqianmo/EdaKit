"""Electrical identity, custom shape dependencies and manufacturing geometry."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from edakit.easyeda.parse import parse_component, _Transform
from edakit.easyeda.model import Pad, Primitive
from edakit.errors import UnsupportedGeometryError
from edakit.footprint.geometry import path_polygons, rings_geometry, graphic_regions, pieces
from edakit.footprint.padstack import footprint_padstacks, merge_padstacks
from edakit.footprint.validation import validate_pin_mapping
from edakit.footprint.skill import generate_skill
from edakit.footprint.identity import pad_name
from edakit.services.footprint import prepare_footprint
from edakit.render.svg import render_footprint_svg


def component(cid='C165948'):
    return parse_component(cid,json.loads((Path(__file__).parent/'data'/f'{cid}.json').read_text(encoding='utf-8')))


def test_usb_custom_copper_slots_and_mechanics_have_distinct_identity(tmp_path):
    c = component()
    assert validate_pin_mapping(c.symbol,c.footprint)['pin_count'] == 16
    assert sum(p.mechanical for p in c.footprint.padstacks) == 2
    slots = [p for p in c.footprint.padstacks if p.slot_width_mm]
    assert len(slots) == 4
    assert sorted(round(p.slot_height_mm,3) for p in slots) == [1.2,1.2,1.5,1.5]
    assert all(p.slot_width_mm == pytest.approx(.8,abs=.0001) for p in slots)
    result = prepare_footprint(c,tmp_path)
    assert result['shapeSymbols']
    folder = Path(result['directory'])
    assert all((folder/(n+'.il')).exists() for n in result['shapeSymbols'])
    script = (folder/'manual_build.il').read_text()
    assert script.count('axlDBCreatePin ') == 18
    assert "'OVAL_SLOT" in script and "'NON_PLATED" in script
    assert '<polygon ' in render_footprint_svg(c.footprint)


def test_source_mask_and_paste_margins_are_applied():
    c = component()
    p = next(p for p in c.footprint.pads if p.shape == 'POLYGON')
    assert p.solder_expansion_mm == pytest.approx(.0510032)
    assert not p.paste_enabled
    ps = next(s for s in c.footprint.padstacks if s.name == p.number)
    assert {l.layer for l in ps.layers} == {'TOP','TOP_SOLDERMASK'}
    assert next(l for l in ps.layers if l.layer == 'TOP_SOLDERMASK').w_mm > next(l for l in ps.layers if l.layer == 'TOP').w_mm


def test_roundrect_and_slot_geometry_change_cache_identity():
    p = Pad(number='1',shape='ROUNDRECT',w_mm=2,h_mm=1,layers=['TOP'],corner_radius_mm=.2)
    a, = merge_padstacks([p])
    from edakit.easyeda.model import Footprint
    assert "'ROUNDED_RECTANGLE" in generate_skill(Footprint(name='RR',padstacks=[a]))
    b = deepcopy(a); b.layers[0].radius_mm=.1
    assert pad_name(a) != pad_name(b)
    b = deepcopy(a); b.drill_mm=.3;b.slot_width_mm=.3;b.slot_height_mm=.6
    assert pad_name(a) != pad_name(b)


@pytest.mark.parametrize('path',['M0 0L1','M0 0L2 0L2 2 garbage','M0 0A1 1 0 2 0 2 2Z','M0 0L1e999 0L1 1Z'])
def test_svg_parser_rejects_partial_or_nonfinite_paths(path):
    with pytest.raises(ValueError):path_polygons(path,_Transform(0,0,flip_y=False))


def test_nonzero_fill_preserves_void_and_same_winding_inner_fill():
    outer=[(0,0),(4,0),(4,4),(0,4)]
    inner=[(1,1),(3,1),(3,3),(1,3)]
    assert rings_geometry([outer,inner]).area == 16
    geometry=rings_geometry([outer,inner[::-1]])
    assert geometry.area == 12 and len(pieces(geometry)[0].interiors) == 1
    assert pieces(geometry.difference(geometry)) == []


def test_split_paste_apertures_do_not_create_electrical_pins():
    c=component('C23630')
    p=Pad(shape='RECT',x_mm=0,y_mm=0,w_mm=.2,h_mm=.3,layers=['TOP_PASTE'])
    c.footprint.pads.extend([p,deepcopy(p)])
    c.footprint.pads[-1].x_mm=.4
    c.footprint.padstacks=footprint_padstacks(c.footprint)
    assert validate_pin_mapping(c.symbol,c.footprint)['pin_count'] == 2
    assert len(graphic_regions(c.footprint)) >= 2
    assert 'PACKAGE GEOMETRY/PASTEMASK_TOP' in generate_skill(c.footprint)


def test_different_location_same_number_stays_an_explicit_error():
    c=component('C23630')
    p=deepcopy(c.footprint.pads[0]);p.x_mm+=5
    c.footprint.pads.append(p)
    with pytest.raises(UnsupportedGeometryError,match='位置不一致'):
        footprint_padstacks(c.footprint)


def test_through_hole_negative_plane_boundary_is_reported():
    from edakit.footprint.native import manufacturing_notes
    assert 'ANTI/THERMAL' in manufacturing_notes(component('C165948'))[0]
    assert manufacturing_notes(component('C23630')) == []


def test_unsupported_copper_cannot_reuse_supported_geometry_cache():
    from edakit.easyeda.model import Primitive
    from edakit.library import library_names
    c = component('C23630')
    before = library_names(c)['geometryDigest']
    c.footprint.primitives.append(Primitive(kind='VIA', raw='VIA~unsupported'))
    assert library_names(c)['geometryDigest'] != before

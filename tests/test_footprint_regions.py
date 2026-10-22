"""Regression coverage for filled artwork and unsafe region conversion."""
import json
from pathlib import Path

import pytest

from edakit.easyeda.parse import parse_component
from edakit.errors import UnsupportedGeometryError
from edakit.footprint.skill import DRAW, SOLID_DRAW, generate_skill


def footprint(layer='12', path='M 0 0 L 10 0 L 10 10 Z', kind='solid'):
    payload = json.loads((Path(__file__).parent / 'data/C2040.json').read_text(encoding='utf8'))
    payload['packageDetail']['dataStr']['shape'] = [
        s for s in payload['packageDetail']['dataStr']['shape']
        if not s.startswith('SOLIDREGION~')]
    payload['packageDetail']['dataStr']['shape'].append(
        f'SOLIDREGION~{layer}~~{path}~{kind}~regression')
    return parse_component('C2040', payload).footprint


@pytest.mark.parametrize('layer,target', [
    ('12', 'ASSEMBLY_TOP'), ('13', 'ASSEMBLY_TOP'), ('14', 'ASSEMBLY_BOTTOM'),
    ('3', 'SILKSCREEN_TOP'), ('4', 'SILKSCREEN_BOTTOM'),
    ('5', 'PASTEMASK_TOP'), ('6', 'PASTEMASK_BOTTOM'),
    ('7', 'SOLDERMASK_TOP'), ('8', 'SOLDERMASK_BOTTOM'),
    ('10', 'ASSEMBLY_TOP'), ('99', 'ASSEMBLY_TOP'),
    ('100', 'ASSEMBLY_TOP'), ('101', 'SILKSCREEN_TOP'),
])
def test_filled_graphics_keep_layer_and_closed_shape(layer, target):
    script = generate_skill(footprint(layer))
    shape, = [line for line in script.splitlines() if '(axlDBCreateShape ' in line]
    assert f'"PACKAGE GEOMETRY/{target}"' in shape
    assert 'solid region failed' in shape
    assert script.count('(axlDBCreatePin ') == 57


def test_outline_and_fill_layer_mapping_agree():
    assert all(SOLID_DRAW[layer] == target for layer, target in DRAW.items())


def test_c7171_tantalum_capacitor_retains_document_and_silk_fills():
    payload = json.loads((Path(__file__).parent / 'data/C7171.json').read_text(encoding='utf8'))
    comp = parse_component('C7171', payload)
    from edakit.footprint.validation import validate_pin_mapping
    validate_pin_mapping(comp.symbol, comp.footprint)
    script = generate_skill(comp.footprint, refdes_prefix=comp.symbol.prefix)
    shapes = [line for line in script.splitlines() if '(axlDBCreateShape ' in line]
    assert len(shapes) == len(comp.footprint.solid_regions) == 10
    assert sum('ASSEMBLY_TOP' in line for line in shapes) == 8
    assert sum('SILKSCREEN_TOP' in line for line in shapes) == 2
    assert script.count('(axlDBCreatePin ') == 2
    assert 'axlDBCreateText "C*"' in script


@pytest.mark.parametrize('layer', ['1', '2', '11', '21', '999'])
def test_copper_and_unknown_layers_are_not_silently_reassigned(layer):
    with pytest.raises(UnsupportedGeometryError, match='区域层'):
        generate_skill(footprint(layer))


@pytest.mark.parametrize('kind', ['npth', 'unknown'])
def test_non_solid_regions_are_not_filled(kind):
    with pytest.raises(UnsupportedGeometryError, match='区域类型'):
        generate_skill(footprint(kind=kind))


@pytest.mark.parametrize('path', [
    'M 0 0 L 10 0 L 10 10 garbage', 'M 0 0 L 10 0 L 10 10 5 Z',
    'M 0 0 Q 10 0 10 Z', '',
])
def test_invalid_or_unsupported_paths_fail_explicitly(path):
    with pytest.raises(UnsupportedGeometryError, match='填充区域'):
        generate_skill(footprint(path=path))


@pytest.mark.parametrize('path', ['m 0 0 l 10 0 l 0 10 z',
    'M 0 0 L 10 0 L 10 10 M 20 20 L 30 20 L 30 30 Z',
    'M 0 0 Q 10 0 10 10 Z'])
def test_extended_paths_preserve_valid_geometry(path):
    fp = footprint(path=path)
    assert fp.solid_regions[0].geom['path_supported']
    assert 'axlDBCreateShape' in generate_skill(fp)


def test_orphan_cutout_is_not_silently_discarded():
    with pytest.raises(UnsupportedGeometryError, match='挖空层'):
        generate_skill(footprint(layer='14',kind='cutout'))


def test_absolute_implicit_pairs_commas_and_exponents_parse_correctly():
    fp = footprint(path='M0,0 1e1,0 L10,1e1 Z')
    pts = fp.solid_regions[0].geom['points_mm']
    assert pts[2] - pts[0] == pytest.approx(2.54)
    assert pts[5] - pts[1] == pytest.approx(2.54)
    generate_skill(fp)

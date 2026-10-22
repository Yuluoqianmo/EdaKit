import json
from pathlib import Path
import pytest
from edakit.easyeda.parse import parse_component
from edakit.footprint.skill import generate_skill
from edakit.render.svg import render_footprint_svg
from edakit.errors import UnsupportedGeometryError
from edakit.footprint.identity import geometry


def capacitor():
    return parse_component('C2686214', json.loads(
        (Path(__file__).parent / 'data/C2686214.json').read_text(encoding='utf8'))).footprint


def test_real_through_hole_capacitor_preserves_rectangle_and_drills():
    fp = capacitor()
    rect, = [p for p in fp.primitives if p.kind == 'RECT']
    assert rect.geom['x_mm'] == pytest.approx(-5.969)
    assert rect.geom['x2_mm'] - rect.geom['x_mm'] == pytest.approx(12.065)
    assert rect.geom['width_mm'] == pytest.approx(.254)
    script = generate_skill(fp)
    assert '(list -5.9690:-3.6830 6.0960:-3.6830 6.0960:3.6830 -5.9690:3.6830 -5.9690:-3.6830) 0.2540' in script
    assert script.count('(axlDBCreatePin ') == 2
    assert '?drillDiameter 0.9144' in script
    assert "?plating 'PLATED" in script
    assert 'PACKAGE GEOMETRY/ASSEMBLY_TOP' in script
    assert 'width="12.0650" height="7.3660" fill="none"' in render_footprint_svg(fp)


@pytest.mark.parametrize('change', [{'layer': 'TOP'}, {'width_mm': -1},
    {'width_mm': 0}, {'x2_mm': -5.969}, {'x_mm': float('nan')}])
def test_invalid_rectangle_not_discarded(change):
    fp = capacitor()
    next(p for p in fp.primitives if p.kind == 'RECT').geom.update(change)
    with pytest.raises(UnsupportedGeometryError):
        generate_skill(fp)


def test_filled_rectangle_preserves_fill_and_stroke_and_identity():
    fp = capacitor()
    before = geometry(fp)
    next(p for p in fp.primitives if p.kind == 'RECT').geom['filled'] = True
    script = generate_skill(fp)
    assert '(axlDBCreateRectangle (list -5.9690:-3.6830 6.0960:3.6830) t "PACKAGE GEOMETRY/SILKSCREEN_TOP")' in script
    assert 'rectangle outline' in script
    assert before != geometry(fp)

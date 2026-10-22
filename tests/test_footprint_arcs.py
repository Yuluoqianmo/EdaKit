import json
from pathlib import Path
import pytest
from edakit.easyeda.arcs import circular_arcs
from edakit.easyeda.parse import _Transform, parse_component
from edakit.footprint.skill import generate_skill
from edakit.easyeda.arcs import arc_bounds


@pytest.mark.parametrize('large', [0, 1])
@pytest.mark.parametrize('sweep', [0, 1])
def test_direction_and_flags(large, sweep):
    arc, = circular_arcs(f'M 100 200 A 10 10 0 {large} {sweep} 110 210',
                          _Transform(100, 200, flip_y=False))
    assert arc['start'] == (0, 0)
    assert arc['end'] == pytest.approx((2.54, 2.54))
    assert arc['large'] == bool(large)
    assert arc['clockwise'] == (not bool(sweep))
    assert arc['radius'] == pytest.approx(2.54)


def test_radius_correction_and_relative_repeated_arcs():
    arcs = circular_arcs('M0 0 a1 1 0 0 1 4 0 1 1 0 0 0 -4 0',
                         _Transform(0, 0, flip_y=False))
    assert len(arcs) == 2
    assert arcs[0]['radius'] == pytest.approx(.508)
    assert arcs[-1]['end'] == (0, 0)


def test_small_and_large_arc_extrema():
    base = dict(start=(1, 0), end=(0, 1), radius=1, clockwise=False)
    small = arc_bounds(dict(base, large=False))
    assert min(x for x, y in small) == pytest.approx(0)
    assert min(y for x, y in small) == pytest.approx(0)
    large = arc_bounds(dict(base, large=True))
    assert max(x for x, y in large) == pytest.approx(2)
    assert max(y for x, y in large) == pytest.approx(2)


def test_c8734_source_arc():
    arcs = circular_arcs('M 577.6536 -211.0658 A 0.7874 0.7874 0 1 0 577.6636 -211.0658',
                         _Transform(580, -200, flip_y=False))
    assert len(arcs) == 1
    assert arcs[0]['large'] and arcs[0]['clockwise']
    assert arcs[0]['radius'] == pytest.approx(.1999996)


@pytest.mark.parametrize('path', ['M0 0 A1 2 0 0 1 3 4', 'M0 0 Q1 2 3 4',
                                  'M0 0 A1 1 0 2 1 3 4', 'M0 0 A1'])
def test_invalid_paths_not_silently_dropped(path):
    with pytest.raises(ValueError):
        circular_arcs(path, _Transform(0, 0, flip_y=False))


def test_real_capacitor_arcs_generate_native_paths():
    source = json.loads((Path(__file__).parent / 'data/C23630.json').read_text(encoding='utf8'))
    fp = parse_component('C23630', source).footprint
    arcs = [p for p in fp.primitives if p.kind == 'ARC']
    assert arcs
    script = generate_skill(fp)
    assert script.count('(axlPathArcRadius ') == sum(len(p.geom['arcs']) for p in arcs)
    assert '(axlDBCreatePath path "PACKAGE GEOMETRY/SILKSCREEN_TOP")' in script

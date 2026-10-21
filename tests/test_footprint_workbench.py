import json
from pathlib import Path

import pytest

from edakit.easyeda.parse import parse_component
from edakit.errors import UnsupportedGeometryError
from edakit.footprint.naming import footprint_name
from edakit.pipeline import stage_component
from edakit.config import Config
from edakit.services.footprint import prepare_footprint


def component(cid):
    return parse_component(cid, json.loads(
        (Path(__file__).parent / 'data' / (cid + '.json')).read_text(encoding='utf-8')))


def test_paired_name_and_manual_build(tmp_path):
    comp = component('C2040')
    original = comp.footprint.name
    result = prepare_footprint(comp, tmp_path / 'lib')
    folder = Path(result['directory'])
    script = (folder / 'manual_build.il').read_text(encoding='utf-8')
    staged = stage_component(comp, Config(footprint_lib=str(tmp_path / 'lib')),
                             capture_only=True, download_step=False)
    assert staged.footprint_name == result['footprint']
    assert result['footprint'] in staged.symbol_xml.read_text(encoding='utf-8')
    assert 'axlOpenDesign' not in script
    assert 'simplifyFilename' in script and 'axlIsSymbolEditor' in script
    assert 'output already exists' in script
    assert comp.footprint.name == original
    assert not result['nativeBuildVerified']
    assert len(result['footprint']) <= 31 and '.' not in result['footprint']
    assert Path(prepare_footprint(comp, tmp_path / 'lib')['directory']) != folder


def test_unsupported_geometry_creates_no_candidate(tmp_path):
    with pytest.raises(UnsupportedGeometryError, match='ARC'):
        prepare_footprint(component('C23630'), tmp_path / 'lib')
    assert not (tmp_path / 'pcb-candidates').exists()


def test_simple_name_preserved():
    assert footprint_name('R0603') == 'R0603'
    assert footprint_name('A.B') != footprint_name('A_B')

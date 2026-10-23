"""Real model cache integration, assembly units, and invalid-cache boundaries."""
import json
from pathlib import Path

import pytest

from edakit.ibom import facets, preview3d


def cache(unit='mm 0.001000', children=''):
    return (f'''<step-assembly root="root"><product id="root" shape="assembly"/>
      <shape id="assembly" unit="mm 0.001000">
        <child ref="body" xform="1 0 0 0 0 1 0 0 0 0 1 0 10 20 30 1"/>
        {children}</shape>
      <shape id="body" unit="{unit}" shell="shell"/>
      <shell id="shell" color="ff8000"><verts>
        <v p="0 0 0"/><v p="1 0 0"/><v p="0 1 0"/></verts>
        <facets><f v="0 1 2"/></facets></shell></step-assembly>''').encode()


def test_cache_keeps_real_geometry_colors_assembly_offsets_and_inch_units():
    meshes = facets.parse(cache('in 0.025400'))
    assert len(meshes) == 1
    assert meshes[0]['attributes']['position']['array'] == pytest.approx(
        [10, 20, 30, 35.4, 20, 30, 10, 45.4, 30])
    assert meshes[0]['index']['array'] == [0, 1, 2]
    assert meshes[0]['color'] == [1, 128/255, 0]


def test_repeated_assembly_instances_are_retained():
    meshes = facets.parse(cache(children='<child ref="body" xform="1 0 0 0 0 1 0 0 0 0 1 0 -10 0 0 1"/>'))
    assert len(meshes) == 2
    assert meshes[1]['attributes']['position']['array'][:3] == [-10, 0, 0]


def test_cache_preserves_sharp_corner_normals_and_inverse_transpose():
    raw = cache().replace(b'<f v="0 1 2"/>', b'''<f v="0 1 2">
      <n d="1 1 0"/><n d="1 1 0"/><n d="1 1 0"/></f>
      <f v="0 2 1"><n d="0 0 -1"/><n d="0 0 -1"/><n d="0 0 -1"/></f>''')
    raw = raw.replace(b'xform="1 0 0 0', b'xform="2 0 0 0')
    mesh = facets.parse(raw)[0]
    assert len(mesh['attributes']['position']['array']) == 18
    assert mesh['index']['array'] == [0, 1, 2, 3, 4, 5]
    assert mesh['attributes']['normal']['array'][:3] == pytest.approx(
        [1/5**.5, 2/5**.5, 0])
    assert mesh['attributes']['normal']['array'][-3:] == [0, 0, -1]


def test_drill_locations_include_package_rotation_and_offset(tmp_path):
    ipc = tmp_path/'drills.xml'
    ipc.write_text('''<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Step>
      <PadStackDef name="H"><PadstackHoleDef diameter="2" x="1" y="0"/></PadStackDef>
      <Package name="mount"><LandPattern><Pad padstackDefRef="H">
      <Location x="3" y="0"/><Xform rotation="90"/></Pad></LandPattern></Package>
      <Component refDes="MH1" packageRef="mount"><Location x="10" y="20"/>
      <Xform rotation="90"/></Component></Step></IPC-2581>''')
    holes = preview3d.board_holes(ipc)
    assert len(holes) == 1
    assert holes[0] == pytest.approx({'x': 9, 'y': 23, 'diameter': 2})


@pytest.mark.parametrize('raw', [
    b'<wrong/>', b'<step-assembly',
    b'<!DOCTYPE a><step-assembly/>',
    cache().replace(b'0 1 2', b'0 1 3'),
    cache().replace(b'p="1 0 0"', b'p="NaN 0 0"'),
    cache().replace(b'mm 0.001000', b'mm -1'),
    cache().replace(b'ref="body"', b'ref="assembly"'),
    cache().replace(b'shell="shell"', b'shell="missing"'),
])
def test_invalid_cache_is_rejected_without_guessing_geometry(raw):
    with pytest.raises(ValueError):
        facets.parse(raw)


def mapping(tmp_path, **extra):
    labels = tmp_path / 'labels.tsv'
    row = dict(refdes='R1', file='actual.STEP', rx='0', ry='90', rz='180',
               ox='1', oy='2', oz='3', search='', **extra)
    Path(str(labels) + '.models.tsv').write_text(
        '\t'.join(row) + '\n' + '\t'.join(row.values()) + '\n', encoding='utf-8')
    return labels


def test_native_psm_directory_cache_with_spaces_and_deduplication(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    folder = tmp_path / 'native library with spaces'
    (folder / 'stepFacetFiles4Map').mkdir(parents=True)
    (folder / 'stepFacetFiles4Map/actual.xml').write_bytes(cache())
    labels = mapping(tmp_path, package_resolved=str(folder / 'footprint.psm'))
    sidecar = Path(str(labels) + '.models.tsv')
    sidecar.write_text(sidecar.read_text() + sidecar.read_text().splitlines()[1].replace('R1\t', 'R2\t') + '\n')
    payload = {'components': [{'refdes': ref} for ref in ('R1', 'R2', 'R3')]}
    preview3d.prepare(payload, None, tmp_path/'board.brd', labels)
    assert len(payload['preview3d']['models']) == 1
    first, second, third = payload['components']
    assert first['model3d'] == second['model3d']
    assert first['model3d']['rotation'] == [0, 90, 180]
    assert first['model3d']['offset'] == [1, 2, 3]
    assert third['model3d'] is None
    entry = next(iter(payload['preview3d']['models'].values()))
    assert entry['format'] == 'allegro-facets' and entry['meshes']
    # A cache-only page must work without starting the STEP/WASM parser.
    assert 'window.__ibomWasm=' not in preview3d.embed('<body></body>', payload)


def test_native_resolved_cache_and_bad_step_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    actual = tmp_path / 'actual.STEP'
    actual.write_bytes(b'invalid STEP')
    native = tmp_path / 'native.xml'
    native.write_bytes(cache())
    labels = mapping(tmp_path, resolved=str(actual), facet_resolved=str(native))
    payload = {'components': [{'refdes': 'R1'}]}
    preview3d.prepare(payload, None, tmp_path/'board.brd', labels)
    assert payload['components'][0]['model3d']
    assert payload['preview3d']['diagnostics'][0]['file'] == str(native)


def test_real_step_remains_preferred_to_cache(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    actual = tmp_path / 'actual.STEP'
    actual.write_bytes(b'ISO-10303-21;actual STEP')
    native = tmp_path / 'native.xml'
    native.write_bytes(cache())
    labels = mapping(tmp_path, resolved=str(actual), facet_resolved=str(native))
    payload = {'components': [{'refdes': 'R1'}]}
    preview3d.prepare(payload, None, tmp_path/'board.brd', labels)
    assert next(iter(payload['preview3d']['models'].values()))['format'] == 'step'

import json
from copy import deepcopy
from pathlib import Path

import pytest

from edakit.config import Config
from edakit.easyeda.model import Component, Model3D
from edakit.easyeda.parse import parse_component
from edakit.install import allegro_env
from edakit.library import library_names
from edakit.services import library_settings, preview
from edakit.threed import assembly
from edakit.threed.preview import parse_obj

OBJ = b'v 1 2 -1\nv 3 2 -1\nv 1 6 2\nf 1 2 3\n'
STEP = b"ISO-10303-21;\nHEADER;FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;DATA;ENDSEC;END-ISO-10303-21;"


def part(cid='C23630'):
    return parse_component(cid, json.loads((Path(__file__).parent/'data'/(cid+'.json')).read_text(encoding='utf-8')))


def test_source_outline_overrides_stale_capacitor_origin():
    comp = part()
    assert comp.model3d.origin_mm != (0, 0)
    assert comp.model3d.outline_center_mm == pytest.approx((0, 0), abs=.001)
    angles, offset = assembly.placement(comp.model3d, OBJ)
    assert angles == (0, 0, 0)
    assert offset == (-2, -4, 1)


def test_rotation_and_negative_install_height_keep_board_coordinates():
    model = Model3D(rotation_deg=(0, 0, 90), outline_center_mm=(4, 7), z_mm=-.5)
    angles, offset = assembly.placement(model, OBJ)
    points = [tuple(a+b for a,b in zip(assembly.rotate(p, angles), offset))
              for p in parse_obj(OBJ).vertices]
    assert (min(p[0] for p in points)+max(p[0] for p in points))/2 == pytest.approx(4)
    assert (min(p[1] for p in points)+max(p[1] for p in points))/2 == pytest.approx(-7)
    assert min(p[2] for p in points) == pytest.approx(-.5)


def test_model_identity_prevents_wrong_body_reuse():
    comp = part()
    other = deepcopy(comp)
    other.model3d.uuid = 'a'*32
    assert library_names(comp)['footprint'] != library_names(other)['footprint']
    other = deepcopy(comp)
    other.model3d.rotation_deg = (0, 0, 90)
    assert library_names(comp)['footprint'] != library_names(other)['footprint']
    other = deepcopy(comp)
    other.cid = 'C99999'
    assert library_names(comp)['footprint'] == library_names(other)['footprint']


def test_download_cache_tamper_and_partial_model_are_not_bound(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assembly.StepFetcher, 'download_step_bytes', lambda self, uuid: calls.append(uuid) or STEP)
    monkeypatch.setattr(preview, 'model_bytes', lambda uuid: OBJ)
    comp = part()
    binding = assembly.prepare_model(comp, tmp_path)
    assert Path(binding['path']).read_bytes() == STEP
    assert assembly.prepare_model(comp, tmp_path) == binding
    assert len(calls) == 1
    Path(binding['path']).write_bytes(b'user edited model')
    with pytest.raises(ValueError, match='修改'):
        assembly.prepare_model(comp, tmp_path)
    assert Path(binding['path']).read_bytes() == b'user edited model'


@pytest.mark.parametrize('data', [b'<html>error</html>', b'ISO-10303-21;DATA;', b''])
def test_bad_download_does_not_create_model(tmp_path, monkeypatch, data):
    monkeypatch.setattr(assembly.StepFetcher, 'download_step_bytes', lambda self, uuid: data)
    with pytest.raises(ValueError, match='有效'):
        assembly.prepare_model(part(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_uuid_missing_model_and_nonfinite_transform(tmp_path):
    assert assembly.prepare_model(Component(), tmp_path) is None
    comp = part()
    comp.model3d.uuid = '../bad'
    with pytest.raises(ValueError, match='UUID'):
        assembly.prepare_model(comp, tmp_path)
    with pytest.raises(ValueError, match='无效'):
        assembly.placement(Model3D(z_mm=float('nan')), OBJ)


def test_binding_readback_rejects_wrong_rotation_and_units(tmp_path):
    binding = {'file': 'a.stp', 'rotation': (0, 0, 90), 'offset': (1, 2, -.5)}
    report = tmp_path/'native-step.txt'
    report.write_text('a.stp|0|0|90|1|2|-.5')
    assembly.validate_binding(binding, report)
    for content in ['b.stp|0|0|90|1|2|-.5', 'a.stp|0|0|0|1|2|-.5',
                    'a.stp|0|0|90|.0254|2|-.5', 'a.stp|0|0|90|nan|2|-.5']:
        report.write_text(content)
        with pytest.raises(RuntimeError, match='不一致'):
            assembly.validate_binding(binding, report)


def test_preview_uses_the_same_assembly_transform(monkeypatch):
    comp = part()
    captured = []
    monkeypatch.setattr(preview, 'render_model_png', lambda *args: captured.append(args) or b'png')
    assert preview.PreviewService(lambda uuid: OBJ).png(comp, 'model3d', 512, 0, 0) == b'png'
    assert captured[0][4] == assembly.placement(comp.model3d, OBJ)


def test_step_settings_roundtrip_and_separate_environment_paths(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path/'app'))
    cfg = Config.load()
    cfg.auto_config_allegro = False
    cfg.save()
    values = {'symbol_lib': str(tmp_path/'Symbols'), 'footprint_lib': str(tmp_path/'PCB'),
              'step_lib': str(tmp_path/'Model Space'), 'cadence_root': ''}
    assert library_settings.save_settings(values)['step_lib'] == str((tmp_path/'Model Space').resolve())
    assert Path(Config.load().step_lib).is_dir()
    text = allegro_env.build_block(values['footprint_lib'], values['step_lib'])
    assert 'steppath = "' + values['step_lib'].replace('\\', '/') + '" $steppath' in text
    assert 'psmpath = ' + values['footprint_lib'].replace('\\', '/') + ' $psmpath' in text
    values['step_lib'] = 'relative'
    with pytest.raises(ValueError):
        library_settings.save_settings(values)
    assert Config.load().step_lib == str((tmp_path/'Model Space').resolve())


def test_legacy_step_setting_does_not_change_existing_libraries():
    cfg = Config.from_dict({'footprint_lib': 'E:/custom/PCB', 'project_olb': 'E:/custom/a.olb'})
    assert cfg.effective_step_lib.replace('\\', '/') == 'E:/custom/STEP'
    assert cfg.footprint_lib == 'E:/custom/PCB'
    assert cfg.project_olb == 'E:/custom/a.olb'


def test_native_coordinate_boundary_reflects_all_figures_once():
    from edakit.footprint.coordinates import native_cartesian
    from edakit.footprint.skill import generate_skill
    comp = part('C165948')
    original = deepcopy(comp.footprint)
    converted = native_cartesian(comp.footprint)
    assert comp.footprint == original
    assert native_cartesian(converted) == converted
    for source, native in zip(original.padstacks, converted.padstacks):
        assert native.x_mm == source.x_mm
        assert native.y_mm == -source.y_mm
        assert native.rotation_deg == -source.rotation_deg
        assert native.drill_offset_y_mm == -source.drill_offset_y_mm
        for a,b in zip(source.layers, native.layers):
            assert b.polygon_mm == [(x,-y) for x,y in a.polygon_mm]
    script = generate_skill(original)
    p = converted.padstacks[0]
    assert f'{p.x_mm:.4f}:{p.y_mm:.4f}' in script
    for a,b in zip(original.lines, converted.lines):
        assert b[1] == [(x,-y) for x,y in a[1]]
    for a,b in zip(original.solid_regions, converted.solid_regions):
        assert b.geom['rings_mm'] == [[(x,-y) for x,y in ring] for ring in a.geom['rings_mm']]


def test_native_arc_reflection_and_model_preview_preserve_top_orientation():
    from edakit.footprint.coordinates import native_cartesian
    comp = part()
    a = next(p.geom['arcs'][0] for p in comp.footprint.primitives if p.kind == 'ARC')
    b = next(p.geom['arcs'][0] for p in native_cartesian(comp.footprint).primitives if p.kind == 'ARC')
    assert b['start'] == (a['start'][0], -a['start'][1])
    assert b['end'] == (a['end'][0], -a['end'][1])
    assert b['clockwise'] != a['clockwise']


def test_publish_does_not_relabel_old_binary_with_a_new_mapping(tmp_path):
    from edakit.footprint.native import publish, file_hash
    comp = part()
    names = library_names(comp)
    binary = tmp_path/(names['footprint'].lower()+'.psm')
    binary.write_bytes(b'original native binary')
    old = {'version': 2, 'file': 'a.stp', 'rotation': [0,0,0], 'offset': [0,0,0]}
    index = {'version': 1, 'files': {binary.name: file_hash(binary)}, 'packages': {
        names['footprint']: {**names, 'stepBinding': old}}}
    (tmp_path/'edakit-library.json').write_text(json.dumps(index))
    with pytest.raises(RuntimeError, match='映射发生变化'):
        publish(comp, {'footprint': names['footprint'], 'stepBinding': {**old,'offset': [1,0,0]}}, [binary], tmp_path)
    assert binary.read_bytes() == b'original native binary'
    assert json.loads((tmp_path/'edakit-library.json').read_text()) == index

import json
from copy import deepcopy
from pathlib import Path
import threading

import pytest

from edakit.config import Config
from edakit.easyeda.parse import parse_component
from edakit.easyeda.model import Primitive
from edakit.errors import DeployError, PinMappingError
from edakit.footprint import native
from edakit.footprint.padstack import merge_padstacks
from edakit.install import allegro_env
from edakit.library import library_names
from edakit.pipeline import stage_component
from edakit.services import library_settings
from edakit.services.footprint import prepare_footprint


@pytest.fixture
def component():
    comp = parse_component('C25804', json.loads(
        (Path(__file__).parent / 'data/C25804.json').read_text(encoding='utf-8')))
    # These tests isolate native geometry; STEP integration has separate coverage.
    comp.model3d = None
    return comp


def test_names_pair_and_change_with_geometry(component, tmp_path):
    names = library_names(component)
    assert library_names(deepcopy(component)) == names
    assert len(names['symbol']) <= 31 and len(names['footprint']) <= 31
    cfg = Config(symbol_lib=str(tmp_path / 'symbols'), footprint_lib=str(tmp_path / 'pcb'))
    stage = stage_component(component, cfg, capture_only=True, download_step=False)
    assert stage.part_name == names['symbol']
    assert names['footprint'] in stage.symbol_xml.read_text(encoding='utf-8')
    assert stage.symbol_xml.is_relative_to(tmp_path / 'symbols')
    assert cfg.project_olb == str(tmp_path / 'symbols/EdaKit.olb')
    changed = deepcopy(component)
    changed.footprint.padstacks[0].x_mm += .01
    assert library_names(changed)['footprint'] != names['footprint']
    assert library_names(changed)['symbol'] != names['symbol']


def test_settings_persist_and_preserve_options(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    cfg = Config.load()
    cfg.auto_config_allegro = False
    cfg.place_x_mil = 700
    cfg.extra = {'custom': 'keep'}
    cfg.save()
    result = library_settings.save_settings({'symbol_lib': str(tmp_path / 'symbol space'),
        'footprint_lib': str(tmp_path / 'pcb space'), 'cadence_root': ''})
    saved = Config.load()
    assert Path(saved.project_olb) == tmp_path / 'symbol space/EdaKit.olb'
    assert saved.place_x_mil == 700 and saved.extra == {'custom': 'keep'}
    assert result['footprint_lib'] == str((tmp_path / 'pcb space').resolve())
    with pytest.raises(ValueError):
        library_settings.save_settings({'symbol_lib': 'relative', 'footprint_lib': str(tmp_path)})
    assert Config.load() == saved


def test_env_quotes_spaces_and_rejects_expansion():
    assert '"E:/my library"' in allegro_env.build_block('E:/my library')
    for value in ('E:/a\nb', 'E:/$HOME', 'E:/a"b'):
        with pytest.raises(DeployError):
            allegro_env.build_block(value)


def native_files(component, tmp_path):
    result = prepare_footprint(component, tmp_path)
    folder = Path(result['directory'])
    (folder / 'native-success.txt').write_text('COMPILED')
    (folder / 'native-pins.txt').write_text(''.join(
        f'{p.name}|{p.x_mm:.4f}|{-p.y_mm:.4f}\n' for p in component.footprint.padstacks))
    for extension in ('.dra', '.psm'):
        (folder / (result['footprint'] + extension)).write_bytes(b'native')
    import re
    for name in set(re.findall(r'EK_[a-f0-9]{20}\.pad', (folder / 'manual_build.il').read_text())):
        (folder / name).write_bytes(b'pad')
    return result, native.validate_outputs(component, result)


def test_publish_reuse_tamper_and_conflict(component, tmp_path):
    result, files = native_files(component, tmp_path)
    native.publish(component, result, files, tmp_path)
    assert native.compiled_result(component, tmp_path)['reused']
    target = tmp_path / (result['footprint'].lower() + '.psm')
    target.write_bytes(b'user changed')
    assert native.compiled_result(component, tmp_path) is None
    with pytest.raises(RuntimeError, match='冲突'):
        native.publish(component, result, files, tmp_path)
    assert target.read_bytes() == b'user changed'
    assert not (tmp_path / '.edakit-publish.lock').exists()


def test_output_validation_rejects_missing_marker_and_pin_drift(component, tmp_path):
    result, _ = native_files(component, tmp_path)
    folder = Path(result['directory'])
    (folder / 'native-pins.txt').write_text('1|99|99\n2|0|0\n')
    with pytest.raises(RuntimeError, match='坐标'):
        native.validate_outputs(component, result)
    (folder / 'native-success.txt').unlink()
    with pytest.raises(RuntimeError, match='未完成'):
        native.validate_outputs(component, result)


def test_cache_requires_psm_and_pad(component, tmp_path):
    result, files = native_files(component, tmp_path)
    native.publish(component, result, files, tmp_path)
    path = tmp_path / 'edakit-library.json'
    data = json.loads(path.read_text())
    record = data['packages'][result['footprint']]
    record['files'] = {k: v for k, v in record['files'].items() if k.endswith('.dra')}
    path.write_text(json.dumps(data))
    assert native.compiled_result(component, tmp_path) is None


def test_jobs_failure_and_shutdown(component):
    done = threading.Event()
    def builder(*args, **kwargs):
        done.wait(2)
        raise ValueError('test failure')
    jobs = native.FootprintJobs(builder)
    result = jobs.submit(component, Config())
    with pytest.raises(ValueError, match='正在构建'):
        jobs.submit(component, Config())
    done.set()
    jobs.worker.join(3)
    assert jobs.status(result['job'])['status'] == 'failed'
    jobs.close()
    with pytest.raises(ValueError, match='关闭'):
        jobs.submit(component, Config())


def test_timeout_only_terminates_owned_process(component, tmp_path):
    root = tmp_path / 'cadence'
    (root / 'tools/bin').mkdir(parents=True)
    (root / 'tools/bin/allegro.exe').touch()
    (root / 'tools/bin/dbdoctor.exe').touch()
    template = root / 'share/pcb/examples/board_design/symbols/smdres.dra'
    template.parent.mkdir(parents=True)
    template.write_bytes(b'template')
    class Process:
        killed = False
        def poll(self):
            return 0 if self.killed else None
        def terminate(self):
            self.killed = True
        def wait(self, timeout):
            return 0
    process = Process()
    def launch(args, **kwargs):
        assert args[0].endswith('dbdoctor.exe')
        assert Path(kwargs['cwd']).is_relative_to(tmp_path / 'lib')
        return process
    with pytest.raises(RuntimeError, match='超时'):
        native.build_footprint(component, Config(footprint_lib=str(tmp_path / 'lib'),
            cadence_root=str(root)), timeout=-1, launch=launch)
    assert process.killed
    assert not (tmp_path / 'lib/edakit-library.json').exists()


def test_generic_footprint_reused_across_parts(component, tmp_path):
    result, files = native_files(component, tmp_path)
    native.publish(component, result, files, tmp_path)
    other = deepcopy(component)
    other.cid = 'C99999'
    other.symbol.manufacturer = 'Another manufacturer'
    other.symbol.mpn = 'Another value'
    other.footprint.model_3d_name = 'another model'
    other.footprint.origin = (999, 1000)
    other.footprint.pads.reverse()
    other.footprint.pads[0].x_mm += .0000001
    other.footprint.padstacks = merge_padstacks(other.footprint.pads)
    for p in other.footprint.primitives:
        if p.kind not in {'ARC', 'HOLE', 'RECT', 'RECTANGLE'}:
            p.raw += '~unrelated source metadata'
    assert library_names(other)['footprint'] == library_names(component)['footprint']
    assert library_names(other)['symbol'] != library_names(component)['symbol']
    def forbidden(*args, **kwargs):
        pytest.fail('reused geometry must not launch Cadence')
    cached = native.build_footprint(other, Config(footprint_lib=str(tmp_path)), launch=forbidden)
    assert cached['reused'] and cached['elapsedSeconds'] < 1


def test_generic_geometry_separates_numbering_and_layers(component):
    original = library_names(component)['footprint']
    for field, value in [('name', 'A'), ('rotation_deg', 90), ('drill_mm', .2)]:
        changed = deepcopy(component)
        setattr(changed.footprint.padstacks[0], field, value)
        assert library_names(changed)['footprint'] != original
    changed = deepcopy(component)
    changed.footprint.padstacks[0].layers[0].w_mm += .01
    assert library_names(changed)['footprint'] != original
    changed = deepcopy(component)
    changed.footprint.primitives.append(Primitive('ARC', raw='unsupported'))
    assert library_names(changed)['footprint'] != original


@pytest.mark.parametrize('source, label', [
    ('TSSOP-2_L4.9-W3.9-P0.65', 'SOP2_0D65_3D9X4D9'),
    ('SOIC-2_L4.9-W3.9-P0.65', 'SOP2_0D65_3D9X4D9'),
    ('SOT-23-2', 'SOT23_2'),
    ('unknown-source-metadata', 'R2'),
])
def test_reference_naming_categories(component, source, label):
    from edakit.library import package_label
    component.footprint.name = source
    assert package_label(component) == label
    assert len(library_names(component)['footprint']) <= 31


def test_pad_identity_reuses_rounding_noise_and_layer_order(component):
    from edakit.footprint.identity import pad_name
    pad = component.footprint.padstacks[0]
    other = deepcopy(pad)
    other.layers.reverse()
    other.layers[0].w_mm += .00000001
    assert pad_name(pad) == pad_name(other)
    other.layers[0].w_mm += .001
    assert pad_name(pad) != pad_name(other)


def test_standard_pad_definition_ignores_absolute_source_corners(component):
    from edakit.footprint.identity import pad_name
    pad = component.footprint.padstacks[0]
    other = deepcopy(pad)
    other.name = '500'
    other.x_mm += 100
    for layer in other.layers:
        layer.polygon_mm = [(100, 200), (101, 201)]
    assert pad_name(other) == pad_name(pad)
    assert len({pad_name(p) for p in component.footprint.padstacks}) == 1


def test_template_cache_uses_verified_upgrade_and_recovers_corruption(tmp_path):
    root = tmp_path / 'cadence'
    (root / 'tools/bin').mkdir(parents=True)
    (root / 'tools/bin/dbdoctor.exe').write_bytes(b'doctor')
    template = root / 'source.dra'
    template.write_bytes(b'old')
    folder = tmp_path / 'work'
    folder.mkdir()
    calls = []
    class Process:
        returncode = 0
        def poll(self):
            return 0
    def launch(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b'upgraded')
        return Process()
    args = (template, root, tmp_path / 'lib', folder, {}, {}, None, 30, launch)
    seed, reused = native.upgraded_template(*args)
    assert not reused and seed.read_bytes() == b'upgraded'
    assert native.upgraded_template(*args)[1] and len(calls) == 1
    seed.write_bytes(b'corrupt')
    assert not native.upgraded_template(*args)[1] and len(calls) == 2
    template.write_bytes(b'new release')
    assert not native.upgraded_template(*args)[1] and len(calls) == 3


def test_reuse_still_checks_new_symbol_pin_pairing(component, tmp_path):
    result, files = native_files(component, tmp_path)
    native.publish(component, result, files, tmp_path)
    other = deepcopy(component)
    other.symbol.pins[0].number = '99'
    with pytest.raises(PinMappingError):
        native.build_footprint(other, Config(footprint_lib=str(tmp_path)))

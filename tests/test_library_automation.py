import json
from copy import deepcopy
from pathlib import Path
import threading

import pytest

from edakit.config import Config
from edakit.easyeda.parse import parse_component
from edakit.errors import DeployError
from edakit.footprint import native
from edakit.install import allegro_env
from edakit.library import library_names
from edakit.pipeline import stage_component
from edakit.services import library_settings
from edakit.services.footprint import prepare_footprint


@pytest.fixture
def component():
    return parse_component('C25804', json.loads(
        (Path(__file__).parent / 'data/C25804.json').read_text(encoding='utf-8')))


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
        f'{p.name}|{p.x_mm:.4f}|{p.y_mm:.4f}\n' for p in component.footprint.padstacks))
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

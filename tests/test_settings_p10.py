import base64
from types import SimpleNamespace

import pytest

from edakit.config import Config
from edakit.easyeda.model import Symbol, Pin, Primitive
from edakit.symbol.capture_lib import normalize_capture_symbol, u
from edakit.services import directory_picker, library_settings
from edakit.services.preview import PreviewService
from edakit.render import render_symbol_svg


def test_resistor_body_and_preview_match_capture_geometry():
    symbol = Symbol(prefix='R?', primitives=[Primitive(kind='R', geom={
        'x_mm': -1.016, 'x2_mm': 1.016, 'y_mm': -2.54, 'y2_mm': 2.54})],
        pins=[Pin(number='1', name='1', x_mm=0, y_mm=-5.08,
                  length_mm=2.54, orientation_deg=90),
              Pin(number='2', name='2', x_mm=0, y_mm=5.08,
                  length_mm=2.54, orientation_deg=270)])
    prepared = normalize_capture_symbol(symbol)
    assert prepared.primitives == symbol.primitives
    assert normalize_capture_symbol(prepared) == prepared
    assert all(u(p.x_mm) % 10 == u(p.y_mm) % 10 == 0 for p in prepared.pins)
    assert PreviewService().svg(SimpleNamespace(symbol=symbol), 'symbol') == render_symbol_svg(prepared)


def test_settings_detect_real_path_and_preserve_explicit_choice(tmp_path, monkeypatch):
    import importlib
    deploy = importlib.import_module('edakit.install.deploy')
    root = tmp_path / 'SPB'
    binary = root / 'tools/bin/allegro.exe'
    binary.parent.mkdir(parents=True)
    binary.touch()
    cfg = Config(cadence_root='')
    monkeypatch.setattr(Config, 'load', lambda: cfg)
    monkeypatch.setattr(deploy, 'find_capture_tcl_root', lambda: root)
    monkeypatch.setattr(deploy, 'spb_root_from_tcl', lambda _: root)
    assert library_settings.read_settings()['cadence_root'] == str(root)
    assert library_settings.read_settings()['cadence_detected']
    cfg.cadence_root = str(tmp_path / 'missing')
    assert library_settings.read_settings()['cadence_root'] == cfg.cadence_root
    assert not library_settings.read_settings()['cadence_detected']


@pytest.mark.parametrize('output,error', [('E:/中文库', False), ('', False), ('', True)])
def test_directory_picker_result_and_literal_initial(monkeypatch, output, error):
    class ImmediateThread:
        def __init__(self, target, daemon): self.target = target
        def start(self): self.target()
    directory_picker._jobs.clear()
    initial = 'E:/a;$(Write-Output unexpected)'
    def pick(value, owner):
        assert value == initial
        if error: raise OSError('native dialog failed')
        return output
    monkeypatch.setattr(directory_picker.threading, 'Thread', ImmediateThread)
    monkeypatch.setattr(directory_picker, '_pick_directory', pick)
    result = directory_picker.picker_status(directory_picker.start_picker(initial)['job'])
    assert result['done']
    if error:
        assert result['message'] == 'native dialog failed'
        assert 'cancelled' not in result
    else:
        assert result['path'] == output
        assert result['cancelled'] == (not bool(output))


def test_directory_picker_repeated_request_joins_pending_window(monkeypatch):
    pending = []
    class DeferredThread:
        def __init__(self, target, daemon): self.target = target
        def start(self): pending.append(self.target)
    directory_picker._jobs.clear()
    monkeypatch.setattr(directory_picker.threading, 'Thread', DeferredThread)
    monkeypatch.setattr(directory_picker, '_pick_directory', lambda initial, owner: 'D:/库')
    first = directory_picker.start_picker('D:/first')
    assert directory_picker.start_picker('D:/second') == first
    assert len(pending) == 1
    assert not directory_picker.picker_status(first['job'])['done']
    pending.pop()()
    second = directory_picker.start_picker('D:/second')
    assert second != first
    assert directory_picker.picker_status(first['job'])['path'] == 'D:/库'
    pending.pop()()

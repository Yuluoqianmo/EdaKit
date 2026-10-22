from pathlib import Path
from edakit.config import Config


def test_new_install_defaults_to_d_drive(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    cfg = Config.load()
    assert Path(cfg.symbol_lib).as_posix() == 'D:/EdaKit/Libraries/Symbols'
    assert Path(cfg.footprint_lib).as_posix() == 'D:/EdaKit/Libraries/Footprints'
    assert Path(cfg.project_olb).as_posix() == 'D:/EdaKit/Libraries/Symbols/EdaKit.olb'


def test_saved_custom_libraries_remain_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    Config(symbol_lib='E:/custom/symbols', footprint_lib='E:/custom/pcb',
           project_olb='E:/custom/symbols/EdaKit.olb').save()
    cfg = Config.load()
    assert cfg.symbol_lib == 'E:/custom/symbols'
    assert cfg.footprint_lib == 'E:/custom/pcb'


def test_legacy_install_keeps_existing_library(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    legacy = tmp_path / 'lcsc2cadence/config.json'
    legacy.parent.mkdir()
    legacy.write_text('{"footprint_lib":"E:/existing/pcb","project_olb":"E:/existing/project.olb"}')
    cfg = Config.load()
    assert cfg.footprint_lib == 'E:/existing/pcb'
    assert cfg.project_olb == 'E:/existing/project.olb'

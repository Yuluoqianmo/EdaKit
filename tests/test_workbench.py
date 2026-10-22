import pytest
from edakit.services.workbench import navigation
from edakit.bridge.queue import app_dir


def test_native_menu_navigation_is_session_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    path = app_dir() / 'workbench'
    path.mkdir(parents=True)
    (path / 'host-1.nav').write_text('tab=bom\nscope=design\nrevision=42\n', encoding='utf-8')
    assert navigation('host-1')['tab'] == 'bom'
    assert navigation('host-2')['tab'] == ''
    with pytest.raises(ValueError):
        navigation('../host-1')
    (path / 'host-1.nav').write_text('tab=unknown\nscope=design\n', encoding='utf-8')
    with pytest.raises(ValueError):
        navigation('host-1')

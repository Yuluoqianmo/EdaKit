"""让测试无需安装即可 import src 下的包。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

DATA = Path(__file__).resolve().parent / "data"


import pytest


@pytest.fixture(autouse=True)
def skip_desktop_without_display(monkeypatch):
    """Pure tests still run on Linux CI; native Tk widgets need a display."""
    import os
    if os.name != 'nt' and not os.environ.get('DISPLAY'):
        import tkinter
        def unavailable(self, *args, **kwargs):
            pytest.skip('Native Tk UI requires a desktop display')
        monkeypatch.setattr(tkinter.Tk, '__init__', unavailable)


@pytest.fixture(autouse=True)
def isolated_test_storage(tmp_path, monkeypatch, request):
    """Keep app state and generated libraries away from real user data on every OS."""
    from edakit import config
    monkeypatch.setenv('EDAKIT_TEST_PYTHON', sys.executable)
    monkeypatch.setenv('EDAKIT_TEST_ENTRY', str(ROOT / 'entry.py'))
    monkeypatch.setenv('PYTHONPATH', str(SRC))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
    # Dedicated default-path/migration assertions explicitly opt out of library overrides.
    if request.node.name not in {'test_config_defaults_and_save', 'test_new_install_defaults_to_d_drive'}:
        monkeypatch.setattr(config, 'DEFAULT_LIBRARY_ROOT', tmp_path / 'libraries')
    config._configuration_text.cache_clear()
    yield
    config._configuration_text.cache_clear()

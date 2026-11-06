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
def retry_transient_windows_tk_loader(monkeypatch):
    """Repeated Tk interpreter setup can transiently fail on hosted Windows.

    Only loader errors are retried, never widget assertions or callback errors.
    An actually broken installation still fails after three attempts.
    """
    import os
    if os.name != 'nt':
        return
    import gc
    import tkinter
    original = tkinter.Tk.__init__
    def initialize(self, *args, **kwargs):
        for attempt in range(3):
            try:
                return original(self, *args, **kwargs)
            except tkinter.TclError as error:
                if attempt == 2 or not any(text in str(error) for text in
                        ('usable init.tcl', 'usable tk.tcl', 'invalid command name "tcl_findLibrary"')):
                    raise
                gc.collect()
    monkeypatch.setattr(tkinter.Tk, '__init__', initialize)


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

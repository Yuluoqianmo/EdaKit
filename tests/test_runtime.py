import sys

from edakit.runtime import configure_background_streams


def test_windowed_streams_log_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    configure_background_streams()
    stream = sys.stderr
    try:
        print("background output")
        print("background error", file=sys.stderr)
        assert (tmp_path / "edakit/background.log").read_text(encoding="utf-8") == "background output\nbackground error\n"
    finally:
        stream.close()


def test_console_streams_remain_available(monkeypatch):
    before = (sys.stdout, sys.stderr)
    configure_background_streams()
    assert (sys.stdout, sys.stderr) == before

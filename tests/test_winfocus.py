"""winfocus 的跨平台安全测试（Linux 沙盒里全部是空操作）。"""

from edakit import winfocus


def test_noop_on_non_windows(monkeypatch):
    monkeypatch.setattr(winfocus, "_IS_WINDOWS", False)
    v = winfocus.foreground_window()
    assert isinstance(v, int)
    assert winfocus.find_capture_window() == 0
    assert winfocus.is_browser_window(123) is False
    # 不应抛异常，也不应真的开线程
    winfocus.minimize_window(123)
    assert isinstance(winfocus.switch_to_capture(0), bool)


def test_switch_returns_false_off_windows():
    import os

    if os.name != "nt":
        assert winfocus.switch_to_capture(0) is False

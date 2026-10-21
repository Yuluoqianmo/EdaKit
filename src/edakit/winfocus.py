"""Windows 前台切换：双击放置后最小化浏览器、把 OrCAD Capture 提到最前。

背景（2026-10-19 用户反馈）：商城网页在系统浏览器里打开，双击器件后
浏览器仍盖在最前面，用户得手动切回 Capture 才能看到 Place Part 面板并落位。
直觉上应该「双击 → 商城退后、OrCAD 出来」。

做法：HTTP 请求到达时记下当前前台窗口（就是网页所在的浏览器），放置请求
提交后延迟一小段时间（让浏览器先收到响应），再：
  1. 最小化那个浏览器窗口；
  2. 找到 OrCAD Capture 主窗口，还原（若最小化）并 SetForegroundWindow。

全部用 ctypes 调 user32/kernel32，不引入第三方依赖。任何一步失败都静默
跳过——这只是体验优化，绝不能影响放置本身。非 Windows 平台是空操作。
"""

from __future__ import annotations

import ctypes
import os
import threading
import time

_SW_MINIMIZE = 6
_SW_RESTORE = 9

_IS_WINDOWS = os.name == "nt"

# 已知浏览器进程（小写可执行文件名）。前景窗口不在其中就不去最小化它，
# 避免把用户正在用的别的程序意外收起来。
_BROWSERS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "iexplore.exe", "brave.exe",
    "opera.exe", "vivaldi.exe", "360se.exe", "360chrome.exe", "qqbrowser.exe",
    "sogouexplorer.exe", "maxthon.exe", "thebrowser.exe", "arc.exe",
}


def _user32():
    return ctypes.windll.user32


def _image_name(hwnd: int) -> str:
    """窗口所属进程的完整路径（小写）；拿不到返回空串。"""
    kernel32 = ctypes.windll.kernel32
    pid = ctypes.c_ulong(0)
    _user32().GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(0x1000, False, pid.value)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value.lower()
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _title(hwnd: int) -> str:
    n = _user32().GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32().GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_window() -> int:
    """当前前台窗口句柄；非 Windows 或失败返回 0。"""
    if not _IS_WINDOWS:
        return 0
    try:
        return int(_user32().GetForegroundWindow() or 0)
    except Exception:  # noqa: BLE001
        return 0


def minimize_window(hwnd: int) -> None:
    if _IS_WINDOWS and hwnd:
        try:
            _user32().ShowWindow(hwnd, _SW_MINIMIZE)
        except Exception:  # noqa: BLE001
            pass


def _activate(hwnd: int) -> None:
    u = _user32()
    try:
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, _SW_RESTORE)
        if u.SetForegroundWindow(hwnd):
            return
        # 前台锁：把目标线程和我们自己的输入队列临时绑定，再设置一次。
        fg = u.GetForegroundWindow()
        fg_thread = u.GetWindowThreadProcessId(fg, None) if fg else 0
        my_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_thread and fg_thread != my_thread:
            u.AttachThreadInput(fg_thread, my_thread, True)
            try:
                u.SetForegroundWindow(hwnd)
            finally:
                u.AttachThreadInput(fg_thread, my_thread, False)
    except Exception:  # noqa: BLE001
        pass


def find_capture_window() -> int:
    """OrCAD Capture 主窗口；找不到返回 0。"""
    if not _IS_WINDOWS:
        return 0
    u = _user32()
    found: list[int] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):  # type: ignore[no-untyped-def]
        try:
            if not u.IsWindowVisible(hwnd):
                return True
            exe = _image_name(hwnd)
            name = exe.rsplit("\\", 1)[-1] if exe else ""
            title = _title(hwnd)
            cadre = ("\\spb_" in exe) or ("\\cadence" in exe)
            by_exe = cadre and name in {"capture.exe", "orcap.exe", "orcad_capture.exe"}
            by_title = ("orcad capture" in title.lower()) or ("capture cis" in title.lower())
            if by_exe or by_title:
                found.append(hwnd)
        except Exception:  # noqa: BLE001
            pass
        return True

    try:
        u.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:  # noqa: BLE001
        return 0
    return found[0] if found else 0


def is_browser_window(hwnd: int) -> bool:
    if not hwnd or not _IS_WINDOWS:
        return False
    exe = _image_name(hwnd)
    name = exe.rsplit("\\", 1)[-1] if exe else ""
    return name in _BROWSERS


def switch_to_capture(browser_hwnd: int = 0, *, delay: float = 0.6) -> bool:
    """后台线程：稍等片刻 → 最小化浏览器 → 激活 Capture。

    返回 True 表示已排队（不代表一定成功，失败静默）。
    """
    if not _IS_WINDOWS:
        return False

    def _run() -> None:
        try:
            time.sleep(delay)
            cap = find_capture_window()
            if not cap:
                return
            if browser_hwnd and browser_hwnd != cap and is_browser_window(browser_hwnd):
                minimize_window(browser_hwnd)
            _activate(cap)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, name="lcsc-switch-to-capture", daemon=True).start()
    return True

"""Capture-owned service lifetime, independent of Tcl heartbeat delays."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import time


class WindowsProcess:
    def __init__(self, pid: int):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.api.WaitForSingleObject.restype = wintypes.DWORD
        self.api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        self.handle = self.api.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not self.handle:
            code = ctypes.get_last_error()
            if code == 87:
                raise ProcessLookupError(pid)
            raise OSError(code, f"Cannot monitor Capture process {pid}")
        created, exited, kernel, user = [wintypes.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(self.handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            code = ctypes.get_last_error()
            self.close()
            raise OSError(code, "GetProcessTimes failed")
        self.created = ((created.dwHighDateTime << 32) | created.dwLowDateTime) / 10_000_000 - 11644473600

    def alive(self) -> bool:
        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 0xFFFFFFFF:
            raise OSError(ctypes.get_last_error(), "Capture process wait failed")
        return status == 258

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class CaptureSessions:
    def __init__(self, directory: Path, opener=WindowsProcess, grace: float = 3.0):
        self.directory = directory
        self.opener = opener
        self.grace = grace
        self.started = time.monotonic()
        self.empty_since = None
        self.sessions = {}

    def _remove_marker(self, path, stamp):
        try:
            if path.stat().st_mtime_ns == stamp:
                path.unlink()
        except FileNotFoundError:
            pass

    def should_stop(self) -> bool:
        for path in self.directory.glob("*.owner"):
            if not path.stem.isdecimal():
                continue
            pid = int(path.stem)
            if pid in self.sessions:
                continue
            try:
                stat = path.stat()
                process = self.opener(pid)
            except FileNotFoundError:
                continue
            except ProcessLookupError:
                self._remove_marker(path, stat.st_mtime_ns)
                continue
            # A stale marker must not adopt an unrelated process reusing a PID.
            if process.created > stat.st_mtime + 0.01:
                process.close()
                self._remove_marker(path, stat.st_mtime_ns)
                continue
            self.sessions[pid] = (process, path, stat.st_mtime_ns)
        for pid, (process, path, stamp) in list(self.sessions.items()):
            if not process.alive():
                process.close()
                del self.sessions[pid]
                self._remove_marker(path, stamp)
        if self.sessions:
            self.empty_since = None
            return False
        if self.empty_since is None:
            self.empty_since = time.monotonic()
        return time.monotonic() - self.empty_since >= self.grace

    def close(self):
        for process, _, _ in self.sessions.values():
            process.close()
        self.sessions.clear()


@contextmanager
def managed_server_lock(directory: Path):
    """One managed server per runtime directory; OS releases it after a crash."""
    if os.name != "nt":
        raise RuntimeError("Capture-managed service requires Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    digest = hashlib.sha256(str(directory.resolve()).lower().encode()).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = api.CreateMutexW(None, False, "Local\\EdaKit.Server." + digest)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    duplicate = ctypes.get_last_error() == 183
    try:
        yield not duplicate
    finally:
        api.CloseHandle(handle)


def remove_owned_url(path: Path, url: str):
    try:
        if path.read_text(encoding="utf-8").strip() == url.strip():
            path.unlink()
    except FileNotFoundError:
        pass


def publish_owned_url(directory: Path, url: str):
    """The managed mutex owner repairs discovery after deletion or stale writes."""
    from ..storage import atomic_write
    path = directory / "url.txt"
    try:
        if path.read_text(encoding="utf-8").strip() == url.strip():
            return
    except (OSError, UnicodeError):
        pass
    atomic_write(path, url.strip() + "\n")

"""Bound private export history without removing active jobs or user outputs."""
import ctypes
import json
import os
import re
import shutil
import time
from pathlib import Path


def alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # uncertain/access denied: preserve
        try:
            code = wintypes.DWORD()
            return not api.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def active(owner):
    try:
        return alive(json.loads(owner.read_text(encoding='utf-8'))['pid'])
    except (OSError, ValueError, KeyError, TypeError):
        return owner.exists()  # malformed lease: preserve


def cleanup(root, *, now=None, days=30):
    """Only recognized private job/snapshot names, aged 30 days; never follow links."""
    root = Path(root).resolve()
    cutoff = (time.time() if now is None else now) - days * 86400
    for category in ('jobs', 'snapshots'):
        folder = root / category
        if not folder.is_dir() or folder.is_symlink() or folder.resolve().parent != root:
            continue
        for item in folder.iterdir():
            pattern = r'\d{8}_\d{6}_[a-f0-9]{8}' if category == 'jobs' else r'[a-f0-9]{32}\.brd'
            if (not re.fullmatch(pattern, item.name) or item.is_symlink()
                    or item.resolve().parent != folder.resolve()):
                continue
            try:
                owner = item / 'owner.json' if category == 'jobs' else item.with_suffix('.owner.json')
                if item.stat().st_mtime >= cutoff or active(owner):
                    continue
                if category == 'jobs':
                    shutil.rmtree(item)
                else:
                    for path in (item, item.with_suffix('.tsv'), Path(str(item.with_suffix('.tsv')) + '.models.tsv'), owner):
                        path.unlink(missing_ok=True)
            except OSError:
                continue  # locked by Cadence or another cleanup; retry next export

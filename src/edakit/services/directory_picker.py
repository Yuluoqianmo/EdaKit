"""Nonblocking native Windows folder picker without a shell subprocess."""
import ctypes
import os
import threading
import uuid

_jobs = {}
_lock = threading.Lock()


def _pick_directory(initial, owner):
    """IFileOpenDialog in its own STA, selecting filesystem folders only."""
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('data', ctypes.c_ubyte * 16)]

        def __init__(self, value):
            super().__init__()
            self.data[:] = uuid.UUID(value).bytes_le

    pointer, hresult = ctypes.c_void_p, ctypes.c_long
    # WinDLL preserves HRESULTs so cancellation can be distinguished from errors.
    ole, shell = ctypes.WinDLL('ole32'), ctypes.WinDLL('shell32')
    ole.CoInitializeEx.argtypes = [pointer, wintypes.DWORD]
    ole.CoInitializeEx.restype = hresult
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), pointer, wintypes.DWORD,
                                   ctypes.POINTER(GUID), ctypes.POINTER(pointer)]
    ole.CoCreateInstance.restype = hresult
    ole.CoTaskMemFree.argtypes = [pointer]
    shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, pointer,
                                                 ctypes.POINTER(GUID), ctypes.POINTER(pointer)]
    shell.SHCreateItemFromParsingName.restype = hresult

    def call(obj, slot, result_type, argtypes, *args):
        table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(pointer))).contents
        return ctypes.WINFUNCTYPE(result_type, pointer, *argtypes)(table[slot])(obj, *args)

    def check(result):
        if result < 0:
            raise OSError(f'Windows 目录窗口错误 0x{result & 0xffffffff:08X}')

    check(ole.CoInitializeEx(None, 2))
    dialog, folder, selected, name = pointer(), pointer(), pointer(), pointer()
    item_iid = GUID('43826d1e-e718-42ee-bc55-a1e261c37bfe')
    try:
        check(ole.CoCreateInstance(ctypes.byref(GUID('dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7')),
              None, 1, ctypes.byref(GUID('d57c7288-d4ad-4768-be02-9d969532d960')), ctypes.byref(dialog)))
        # FOS_PICKFOLDERS | FORCEFILESYSTEM | PATHMUSTEXIST | NOCHANGEDIR
        check(call(dialog, 9, hresult, [wintypes.DWORD], 0x868))
        check(call(dialog, 17, hresult, [wintypes.LPCWSTR], 'EdaKit — 选择目录'))
        if initial and os.path.isdir(initial):
            check(shell.SHCreateItemFromParsingName(os.path.abspath(initial), None, ctypes.byref(item_iid), ctypes.byref(folder)))
            check(call(dialog, 12, hresult, [pointer], folder))
        result = call(dialog, 3, hresult, [wintypes.HWND], owner)
        if result & 0xffffffff == 0x800704C7:
            return ''
        check(result)
        check(call(dialog, 20, hresult, [ctypes.POINTER(pointer)], ctypes.byref(selected)))
        check(call(selected, 5, hresult, [wintypes.DWORD, ctypes.POINTER(pointer)],
                   0x80058000, ctypes.byref(name)))
        return ctypes.wstring_at(name)
    finally:
        if name:
            ole.CoTaskMemFree(name)
        for obj in (selected, folder, dialog):
            if obj:
                call(obj, 2, wintypes.ULONG, [])
        ole.CoUninitialize()


def start_picker(initial=''):
    if os.name != 'nt':
        raise ValueError('系统目录选择器仅支持 Windows')
    with _lock:
        for token, job in _jobs.items():
            if not job['done']:
                return {'job': token}
        token = uuid.uuid4().hex
        if len(_jobs) >= 32:
            _jobs.pop(next(iter(_jobs)))
        _jobs[token] = {'done': False}
    user32 = ctypes.WinDLL('user32')
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    owner = user32.GetForegroundWindow()

    def run():
        try:
            path = _pick_directory(str(initial), owner)
            value = {'done': True, 'path': path, 'cancelled': not bool(path)}
        except Exception as exc:
            value = {'done': True, 'message': str(exc)}
        with _lock:
            _jobs[token] = value
    threading.Thread(target=run, daemon=True).start()
    return {'job': token}


def picker_status(token):
    with _lock:
        if token not in _jobs:
            raise ValueError('目录选择会话已失效，请重新选择')
        return dict(_jobs[token])

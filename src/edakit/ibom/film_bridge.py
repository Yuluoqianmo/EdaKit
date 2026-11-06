"""Explicit, receipt-verified Film writes to the originating Allegro process.

No timers, startup hooks, arbitrary SKILL files, source-board saves, or fallback
to another Allegro instance. Only the fixed callback is sent over WM_COPYDATA.
"""
import copy
import ctypes
import json
import os
import re
import time
import uuid
from pathlib import Path

from ..storage import atomic_write
from . import gerber


def ancestor_host():
    """Capture PID and process creation time before the launcher detaches."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
                    ('exe', w.WCHAR * 260)]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    api.CreateToolhelp32Snapshot.restype = w.HANDLE
    api.Process32FirstW.argtypes = api.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    api.CloseHandle.argtypes = [w.HANDLE]
    handle = api.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        return None
    parents = {}
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        valid = api.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            parents[entry.pid] = (entry.parent, entry.exe)
            valid = api.Process32NextW(handle, ctypes.byref(entry))
    finally:
        api.CloseHandle(handle)
    pid, seen = os.getpid(), set()
    while pid in parents and pid not in seen:
        seen.add(pid)
        parent, exe = parents[pid]
        if exe.casefold() == 'allegro.exe':
            identity = process_identity(pid)
            return dict(pid=pid, identity=identity) if identity else None
        pid = parent
    return None


def process_identity(pid):
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; api.OpenProcess.restype = w.HANDLE
    api.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    api.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    api.CloseHandle.argtypes = [w.HANDLE]
    handle = api.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        times = [w.FILETIME() for _ in range(4)]
        path, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
        if not api.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)) or not api.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return None
        return dict(exe=path.value.casefold(), created=(times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        api.CloseHandle(handle)


def register(session, source):
    host = ancestor_host()
    if host:
        atomic_write(Path(str(session)+'.host.json'), json.dumps(dict(host=host, source=str(source))))


def send(host, nonce):
    if not re.fullmatch('[a-f0-9]{32}', nonce):
        raise ValueError('无效 Film 请求标识')
    if os.name != 'nt' or process_identity(host['pid']) != host['identity']:
        raise ValueError('原 Allegro 进程已关闭或改变，请从当前 PCB 重新打开生产交付。')
    from ctypes import wintypes as w
    api = ctypes.WinDLL('user32', use_last_error=True)
    callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    api.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    api.IsWindowVisible.argtypes = [w.HWND]
    api.IsWindowEnabled.argtypes = [w.HWND]
    api.GetWindow.argtypes = [w.HWND, w.UINT]; api.GetWindow.restype = w.HWND
    api.EnumWindows.argtypes = [callback, w.LPARAM]
    windows = []
    @callback
    def collect(hwnd, _):
        pid = w.DWORD(); api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == host['pid'] and api.IsWindowVisible(hwnd):
            owner = api.GetWindow(hwnd, 4)
            if not owner or not api.IsWindowVisible(owner):
                windows.append(hwnd)
        return True
    api.EnumWindows(collect, 0)
    # Never guess among several top-level frames or send into a modal dialog.
    if len(windows) != 1 or not api.IsWindowEnabled(windows[0]):
        raise ValueError('无法唯一定位原 Allegro 主窗口，请关闭其对话框后重试。')
    class CopyData(ctypes.Structure):
        _fields_ = [('tag', ctypes.c_size_t), ('size', w.DWORD), ('data', ctypes.c_void_p)]
    data = ctypes.create_string_buffer(('skill edakitDeliveryApplyFilms("'+nonce+'")').encode('ascii'))
    packet = CopyData(0x26297811, ctypes.sizeof(data), ctypes.cast(data, ctypes.c_void_p))
    api.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
    api.SendMessageTimeoutW.restype = w.LPARAM
    result = ctypes.c_size_t()
    if not api.SendMessageTimeoutW(windows[0], 0x4a, 0, ctypes.addressof(packet), 0x22, 5000, ctypes.byref(result)):
        raise TimeoutError('Allegro 未确认接收请求；处理结果待核实，请重新打开生产交付。')


def signature(records):
    return sorted((r['name'], bool(r.get('negative')), bool(r.get('mirror')), tuple(sorted(r['layers']))) for r in records)


def request_text(nonce, baseline, target, copper=None):
    rows = [['EDAKIT_FILM_APPLY', '1', nonce]]
    if not copper or len({layer['name'] for layer in copper}) != len(copper):
        raise ValueError('尚未读取实际 PCB 铜层，不能回写 Film')
    for layer in copper:
        if not layer['name'] or re.search(r'[\x00-\x1f\x7f]', layer['name']):
            raise ValueError('PCB 铜层名称无效')
        rows.append(['C', layer['name'], str(int(bool(layer.get('negative', False))))])
    original = {r['id']: r['name'] for r in baseline}
    original_names = {r['name']: r['name'] for r in baseline}
    for tag, records in (('B', baseline), ('F', target)):
        names = set()
        for r in records:
            if not gerber.valid_name(r['name']) or r['name'].casefold() in names or not r['layers'] or len(set(r['layers'])) != len(r['layers']):
                raise ValueError('Film 文件名、子层为空、重复或无效：'+r['name'])
            names.add(r['name'].casefold())
            values = [tag, r['name'], str(int(bool(r.get('negative')))), str(int(bool(r.get('mirror')))),
                      original.get(r['id'], original_names.get(r['name'], '*')), *r['layers']]
            if any(not v or re.search(r'[\x00-\x1f\x7f]', v) for v in values) or any('/' not in layer for layer in r['layers']):
                raise ValueError('Film 含无效字段或子层')
            rows.append(values)
    rows.append(['END', str(len(baseline)), str(len(target))])
    return '\n'.join('\t'.join(row) for row in rows)+'\n'


class FilmBridge:
    def __init__(self, session, source, *, sender=send, timeout=120):
        self.session = Path(session) if session else None
        self.source, self.sender, self.timeout = str(source), sender, timeout

    def available(self):
        return self.session is not None and Path(str(self.session)+'.host.json').is_file()

    def apply(self, baseline, target, *, copper=None):
        if not self.available():
            raise ValueError('当前窗口没有 PCB 回写连接，请安装新版后从 Allegro 重新打开生产交付。')
        base = str(self.session)
        if Path(base+'.uncertain').exists():
            raise ValueError('上次回写结果未确认，请从当前 PCB 重新打开生产交付后再操作。')
        info = json.loads(Path(base+'.host.json').read_text(encoding='utf-8'))
        if os.path.normcase(os.path.abspath(info['source'])) != os.path.normcase(os.path.abspath(self.source)):
            raise ValueError('Film 会话与当前 PCB 不一致')
        nonce = uuid.uuid4().hex
        text = request_text(nonce, baseline, target, copper)
        payload = text.encode('mbcs' if os.name == 'nt' else 'utf-8', errors='strict')
        lock = Path(base+'.pending')
        try:
            with lock.open('x') as stream:
                stream.write(nonce)
        except FileExistsError:
            raise ValueError('另一个 Film 回写请求尚未结束') from None
        receipt = Path(base+'.'+nonce+'.receipt')
        try:
            atomic_write(Path(base+'.request'), payload)
            # If send or receipt verification fails the native command might have
            # run. Mark uncertain instead of allowing an unverified export/retry.
            try:
                try:
                    self.sender(info['host'], nonce)
                except TimeoutError:
                    # WM_COPYDATA may have reached Allegro even if its UI thread
                    # did not return within five seconds. The receipt decides.
                    pass
                deadline = time.monotonic()+self.timeout
                parts = []
                while True:
                    if receipt.exists():
                        parts = receipt.read_text(encoding='ascii').splitlines()
                        if len(parts) == 3:
                            break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('等待 PCB 回写回执超时。请从当前 PCB 重新打开生产交付，勿使用旧快照导出。')
                    time.sleep(.1)
                if len(parts) != 3 or parts[0] != nonce:
                    raise ValueError('Film 回写回执不完整或不匹配')
                if parts[1] == 'ERROR':
                    # The callback has completed and explicitly verified rollback.
                    raise NativeRejected('Film 写入未完成，原 Film 已恢复。请查看 Allegro 命令日志；若叠层或配置已改变，请重新打开生产交付。\n'+parts[2])
                if parts[1] != 'OK':
                    raise ValueError('Film 回写结果不确定：'+parts[2])
                board = Path(base+'.'+nonce+'.brd')
                films = Path(base+'.'+nonce+'.films.tsv')
                records, known = gerber.read_film_records(films)
                if not board.is_file() or not board.stat().st_size or signature(records) != signature(target):
                    raise ValueError('PCB 快照或 Film 读回结果与提交配置不一致')
                return dict(board=board, records=records, known=known, target=copy.deepcopy(target))
            except NativeRejected:
                raise
            except Exception:
                atomic_write(Path(base+'.uncertain'), nonce)
                # A busy Allegro may not yet have read the queued request.
                # Invalidate it so a delayed callback cannot start a fresh write.
                atomic_write(Path(base+'.request'), b'EDAKIT_FILM_CANCELLED\n')
                raise
        finally:
            lock.unlink(missing_ok=True)


class NativeRejected(ValueError):
    pass


def copy_snapshot(args):
    """Only called by axlRunBatchDBProgram; never modifies the source PCB."""
    source, output = Path(args.board).resolve(), Path(args.output).resolve()
    if source == output or not source.is_file() or output.exists():
        raise ValueError('无效的 Film 快照目标')
    atomic_write(output, source.read_bytes())
    return 0

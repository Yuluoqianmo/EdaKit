"""Detached, cancellable Windows update assistant. Never terminates CAD processes."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from ..storage import atomic_write
from .updates import version


@contextmanager
def assistant_lock(root):
    """One assistant per installation in the interactive Windows session."""
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    api.CreateMutexW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    name = 'Local\\EdaKitUpdate-' + hashlib.sha256(str(root).lower().encode('utf-8')).hexdigest()[:24]
    ctypes.set_last_error(0)
    handle = api.CreateMutexW(None, False, name)
    if not handle:
        raise OSError('无法创建更新助手锁，未启动安装')
    existing = ctypes.get_last_error() == 183
    try:
        if existing:
            raise ValueError('已有更新助手正在运行，请先关闭旧助手')
        yield
    finally:
        api.CloseHandle(handle)


def blockers(root):
    """Fail closed on enumeration errors. Return CAD and install-dir processes."""
    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                    ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                    ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                    ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                    ('flags', wintypes.DWORD), ('name', wintypes.WCHAR * 260)]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError('无法检查运行中的程序')
    out = []
    try:
        entry = Entry(); entry.dwSize = ctypes.sizeof(entry)
        ok = api.Process32FirstW(snapshot, ctypes.byref(entry))
        if not ok:
            raise OSError('无法读取进程列表')
        while ok:
            name = entry.name.lower()
            if name in ('capture.exe', 'allegro.exe', 'allegro_free_viewer.exe'):
                out.append(entry.name)
            elif name in ('edakit.exe', 'edakit-cli.exe') and entry.pid != os.getpid():
                handle = api.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        buf, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
                        if not api.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                            out.append(entry.name)
                        elif Path(buf.value).resolve().parent == root:
                            out.append(entry.name)
                    finally:
                        api.CloseHandle(handle)
                elif ctypes.get_last_error() != 87:  # Process may have exited.
                    out.append(entry.name)
            ok = api.Process32NextW(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise OSError('读取进程列表失败，未启动安装')
    finally:
        api.CloseHandle(snapshot)
    return sorted(set(out))


def load_plan(path):
    path = Path(path).resolve()
    if path.name != 'plan.json' or not path.is_file():
        raise ValueError('更新计划无效')
    plan = json.loads(path.read_text(encoding='utf-8'))
    version(plan['version'])
    if plan.get('scope') not in ('currentuser', 'allusers'):
        raise ValueError('安装范围无效')
    package = Path(plan['path']).resolve()
    if package.parent != path.parent or package.name != 'EdaKit-' + plan['version'] + '-Setup.exe':
        raise ValueError('安装包路径无效')
    digest = hashlib.sha256()
    with package.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != plan['sha256']:
        raise ValueError('安装前 SHA-256 复核失败')
    root = Path(plan['root']).resolve()
    if root == path.parent or not (root / 'deployment.ini').is_file():
        raise ValueError('安装目录无效')
    if not (Path(plan['cadence']) / 'tools/capture/tclscripts').is_dir():
        raise ValueError('Cadence 目录无效')
    return plan


def _launch_setup(plan, log):
    """Windows elevation prompt belongs to the ordinary interactive installer."""
    class Execute(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('mask', wintypes.ULONG), ('hwnd', wintypes.HWND),
                    ('verb', wintypes.LPCWSTR), ('file', wintypes.LPCWSTR), ('parameters', wintypes.LPCWSTR),
                    ('directory', wintypes.LPCWSTR), ('show', ctypes.c_int), ('instance', wintypes.HINSTANCE),
                    ('idlist', ctypes.c_void_p), ('className', wintypes.LPCWSTR), ('classKey', wintypes.HKEY),
                    ('hotkey', wintypes.DWORD), ('icon', wintypes.HANDLE), ('process', wintypes.HANDLE)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(Execute)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    data = Execute(); data.size = ctypes.sizeof(data); data.mask = 0x40 | 0x100
    data.verb = 'runas' if plan['scope'] == 'allusers' else 'open'
    data.file = plan['path']; data.show = 1
    data.parameters = subprocess.list2cmdline(['/ALLUSERS' if plan['scope'] == 'allusers' else '/CURRENTUSER',
                                             '/DIR=' + plan['root'], '/CADENCEROOT=' + plan['cadence'], '/LOG=' + str(log)])
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetDllDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    api.SetDllDirectoryW.argtypes = [wintypes.LPCWSTR]
    previous = ctypes.create_unicode_buffer(32768)
    api.GetDllDirectoryW(len(previous), previous)
    # Do not pass PyInstaller's bundled DLL search directory to the installer.
    api.SetDllDirectoryW(None)
    try:
        launched = shell.ShellExecuteExW(ctypes.byref(data))
        launch_error = ctypes.get_last_error()
    finally:
        api.SetDllDirectoryW(previous.value or None)
    if not launched:
        raise OSError('安装未启动或权限确认已取消（错误 %s）' % launch_error)
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        while api.WaitForSingleObject(data.process, 1000) == 258:
            pass
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(data.process, ctypes.byref(code)) or code.value != 0:
            raise OSError('安装未完成，请查看安装日志（退出码 %s）' % code.value)
    finally:
        api.CloseHandle(data.process)
    actual = subprocess.check_output([str(Path(plan['root']) / 'edakit-cli.exe'), '--version'],
                                     timeout=90, creationflags=subprocess.CREATE_NO_WINDOW).decode('utf-8').strip()
    if actual != plan['version']:
        raise ValueError('安装后版本校验未通过，请查看安装日志')


def launch_setup(plan, log):
    # ShellExecuteEx may invoke COM shell extensions on this worker thread.
    ole = ctypes.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx(None, 2)
    try:
        return _launch_setup(plan, log)
    finally:
        ole.CoUninitialize()


def wait_for_exit(root, event, report, enumerate_processes=blockers, timeout=1800, interval=1, clock=time.monotonic):
    deadline, clear = clock() + timeout, 0
    while not event.is_set():
        names = enumerate_processes(root)
        clear = 0 if names else clear + 1
        if clear >= 2:
            return not event.is_set()
        report('请保存工程并退出：' + '、'.join(names) if names else '正在确认后台服务已退出…')
        if clock() > deadline:
            raise TimeoutError('等待超时，未启动安装，可关闭后重试')
        event.wait(interval)
    return False


def run(path):
    import tkinter as tk
    from tkinter import ttk
    path = Path(path).resolve()
    window = tk.Tk(); window.title('EdaKit 更新助手'); window.geometry('520x230'); window.minsize(440, 230)
    message = tk.StringVar(value='正在校验安装包…')
    ttk.Label(window, text='安装 EdaKit 更新', font=('Microsoft YaHei', 13, 'bold')).pack(anchor='w', padx=20, pady=(18, 8))
    label = ttk.Label(window, textvariable=message, wraplength=470)
    label.pack(fill='x', padx=20, pady=8)
    def resize(event):
        if event.widget is window:
            width = max(280, event.width - 40)
            if int(label.cget('wraplength')) != width:
                label.configure(wraplength=width)
    window.bind('<Configure>', resize)
    event = threading.Event()
    state_lock = threading.RLock()
    state = {'phase': 'waiting', 'message': '请保存工程并退出 Capture、Allegro，更新助手会等待程序和后台服务退出。'}
    def result(phase, text):
        with state_lock:
            if event.is_set() and phase != 'cancelled':
                return
            state.update(phase=phase, message=text)
            atomic_write(path.parent / 'result.json', json.dumps(state, ensure_ascii=False))
    def cancel():
        with state_lock:
            if state['phase'] == 'waiting':
                event.set()
                result('cancelled', '已取消安装；安装包保留，可稍后重试')
            if state['phase'] != 'installing':
                window.destroy()
    button = ttk.Button(window, text='取消更新', command=cancel); button.pack(side='bottom', anchor='e', padx=20, pady=16)
    window.protocol('WM_DELETE_WINDOW', cancel)
    def worker():
        try:
            plan = load_plan(path)
            with assistant_lock(Path(plan['root']).resolve()):
                if not wait_for_exit(Path(plan['root']).resolve(), event,
                                     lambda text: result('waiting', text)):
                    return
                load_plan(path)  # Revalidate immediately before executing downloaded code.
                with state_lock:
                    if event.is_set():
                        return
                    result('installing', '正在启动安装向导，请完成 Windows 权限确认和安装。')
                launch_setup(plan, path.parent / 'installation.log')
                result('completed', '更新已安装并验证版本，请重新打开 Capture 或 Allegro。')
        except Exception as exc:
            result('error', str(exc))
    def paint():
        message.set(state['message'])
        button.configure(state='disabled' if state['phase'] == 'installing' else 'normal',
                         text='关闭' if state['phase'] in ('completed', 'error') else '取消更新')
        window.after(300, paint)
    threading.Thread(target=worker, daemon=True).start()
    paint(); window.mainloop()
    return 0

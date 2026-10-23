"""Install only a marked Allegro startup block, preserving user script bytes."""
import re
import sys
from pathlib import Path
from ..storage import atomic_write
from ..config import app_dir
from .allegro_env import find_pcbenv

BEGIN = b'; >>> EdaKit iBOM begin'
END = b'; <<< EdaKit iBOM end'


def deploy(cadence_root, *, executable=None, pcbenv=None):
    root = Path(cadence_root).resolve()
    home = Path(pcbenv) if pcbenv else find_pcbenv(str(root))
    home.mkdir(parents=True, exist_ok=True)
    if executable:
        exe = Path(executable).resolve()
    elif getattr(sys, 'frozen', False):
        gui = Path(sys.executable).with_name('edakit.exe')
        exe = gui if gui.is_file() else Path(sys.executable)
    else:
        marker = app_dir() / 'exe_path.txt'
        if not marker.is_file():
            raise ValueError('源码模式请用 --executable 指定 EdaKit 程序')
        exe = Path(marker.read_text(encoding='utf-8-sig').strip()).resolve()
    if not exe.is_file() or not (root / 'tools/bin/ipc2581_out.exe').is_file():
        raise ValueError('缺少 EdaKit 程序或 Allegro IPC-2581 导出程序')
    def escape(p):
        text = str(p).replace('\\', '/')
        if any(c in text for c in '\r\n\x00"'):
            raise ValueError('安装路径含不支持字符')
        return text
    # Use ASCII source even for user profiles with non-ASCII path characters.
    # SKILL strings accept UTF-8 bytes only inconsistently across old releases;
    # executable and Cadence paths must therefore use an ASCII install location.
    source = (Path(__file__).parent / 'templates/ibom.il').read_text(encoding='ascii')
    source = source.replace('@EXE@', escape(exe)).replace('@ROOT@', escape(root))
    source.encode('ascii')
    target = home / 'edakit' / 'ibom.il'
    startup = home / 'allegro.ilinit'
    original = startup.read_bytes() if startup.exists() else b''
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError('Allegro 启动文件的 EdaKit 标记不完整，请检查后重试')
    body = re.sub(re.escape(BEGIN) + rb'.*?' + re.escape(END) + rb'\r?\n?', b'', original, flags=re.S)
    load_path = escape(target)
    # Cadence on Windows uses the system encoding for ilinit paths.
    block = BEGIN + b'\nload("' + load_path.encode('mbcs' if sys.platform == 'win32' else 'utf-8') + b'")\n' + END + b'\n'
    backup = startup.with_name('allegro.ilinit.edakit-ibom.bak')
    if startup.exists() and not backup.exists():
        atomic_write(backup, original)
    atomic_write(target, source)
    atomic_write(startup, body.rstrip(b'\r\n') + b'\n' + block)
    return {'startup': str(startup), 'skill': str(target), 'executable': str(exe)}


def undeploy(cadence_root=None, *, pcbenv=None):
    home = Path(pcbenv) if pcbenv else find_pcbenv(cadence_root)
    startup = home / 'allegro.ilinit'
    if startup.exists():
        body = startup.read_bytes()
        if body.count(BEGIN) != body.count(END) or body.count(BEGIN) > 1:
            raise ValueError('Allegro EdaKit 启动标记不完整，未修改启动文件')
        atomic_write(startup, re.sub(re.escape(BEGIN) + rb'.*?' + re.escape(END) + rb'\r?\n?', b'', body, flags=re.S))
    (home / 'edakit' / 'ibom.il').unlink(missing_ok=True)

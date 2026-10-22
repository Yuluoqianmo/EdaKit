"""Synchronize Capture's own Show Footprint search list without losing INI data."""
import codecs
import locale
import ntpath
import os
from pathlib import Path
import re
import shutil

from ..config import app_dir
from ..storage import atomic_write

BEGIN = '; >>> EdaKit footprint viewer'
END = '; <<< EdaKit footprint viewer'


def find_ini(cadence_root=None):
    marker = app_dir() / 'capture_ini_path.txt'
    try:
        path = Path(marker.read_text(encoding='utf-8').removeprefix('path=').strip())
        if path.is_absolute() and path.suffix.lower() == '.ini' and path.is_file():
            return path
    except OSError:
        pass
    if not cadence_root:
        return None
    root = Path(cadence_root)
    version = re.search(r'(\d+\.\d+)', root.name)
    if not version:
        return None
    homes = [root.parent / 'SPB_Data']
    if os.environ.get('APPDATA'):
        homes.append(Path(os.environ['APPDATA']) / 'SPB_Data')
    if os.environ.get('HOME'):
        homes.append(Path(os.environ['HOME']))
    for home in homes:
        candidate = home / 'cdssetup/OrCAD_Capture' / (version[1]+'.0') / 'Capture.ini'
        if candidate.is_file():
            return candidate
    return None


def updated_text(text, library):
    if not library or any(c in library for c in '\r\n\x00'):
        raise ValueError('Capture 封装库路径无效')
    newline = '\r\n' if '\r\n' in text else '\n'
    section = re.search(r'(?mi)^\[Allegro Footprints\][ \t]*\r?$', text)
    if section is None:
        prefix = text + (newline if text and not text.endswith(('\n', '\r')) else '')
        if not re.search(r'(?mi)^\[Footprint Viewer Type\][ \t]*\r?$', text):
            prefix += '[Footprint Viewer Type]' + newline + 'Type=Allegro' + newline
        return updated_text(prefix + '[Allegro Footprints]' + newline, library)
    start = section.end()
    if text[start:start+2] == '\r\n':
        start += 2
    elif text[start:start+1] == '\n':
        start += 1
    elif start == len(text):
        text += newline
        start = len(text)
    following = re.search(r'(?m)^\[', text[start:])
    end = start + following.start() if following else len(text)
    body = text[start:end]
    body = re.sub(r'(?ms)^' + re.escape(BEGIN) + r'\r?\n.*?^' + re.escape(END) + r'\r?\n?', '', body)
    entries = re.findall(r'(?mi)^[ \t]*Dir(\d+)[ \t]*=[ \t]*(.*?)\r?$', body)
    normalize = lambda value: ntpath.normcase(ntpath.normpath(value.strip().strip('"')))
    if any(normalize(value) == normalize(library) for _,value in entries):
        return text[:start] + body + text[end:]
    used = {int(key) for key,_ in entries}
    number = next(i for i in range(len(used)+1) if i not in used)
    block = newline.join((BEGIN, f'Dir{number}={library}', END, ''))
    return text[:start] + block + body + text[end:]


def configure(library, *, cadence_root=None, ini_path=None, dry_run=False):
    path = Path(ini_path) if ini_path is not None else find_ini(cadence_root)
    if path is None:
        return None
    original = path.read_bytes()
    bom = b''
    if original.startswith(codecs.BOM_UTF16_LE):
        bom, encoding = codecs.BOM_UTF16_LE, 'utf-16-le'
    elif original.startswith(codecs.BOM_UTF16_BE):
        bom, encoding = codecs.BOM_UTF16_BE, 'utf-16-be'
    elif original.startswith(codecs.BOM_UTF8):
        bom, encoding = codecs.BOM_UTF8, 'utf-8'
    else:
        try:
            original.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            encoding = locale.getpreferredencoding(False)
    updated = bom + updated_text(original[len(bom):].decode(encoding), str(library)).encode(encoding)
    if original != updated and not dry_run:
        backup = path.with_name(path.name+'.edakit-before-footprints.bak')
        if not backup.exists():
            shutil.copy2(path, backup)
        if path.read_bytes() != original:
            raise OSError('Capture 配置正在更新，请稍后重试')
        atomic_write(path, updated)
    return path

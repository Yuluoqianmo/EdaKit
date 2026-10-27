"""Bounded GitHub release checks and verified downloads, outside Capture's thread."""
import configparser
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

from .. import __version__
from ..config import app_dir
from ..storage import atomic_write

REPO = 'https://github.com/Yuluoqianmo/EdaKit'
LATEST = 'https://api.github.com/repos/Yuluoqianmo/EdaKit/releases/latest'
MAX_SETUP = 512 * 1024 * 1024
HOSTS = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise ValueError('版本格式不支持，请查看 Releases')
    return tuple(map(int, value.lstrip('v').split('.')))


def allowed_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443):
        raise ValueError('更新下载地址无效')
    return url


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    return urllib.request.build_opener(Redirects()).open(
        urllib.request.Request(allowed_url(url), headers={
            'User-Agent': 'EdaKit/' + __version__, 'Accept': 'application/vnd.github+json' if urlsplit(url).hostname == 'api.github.com' else 'application/octet-stream'}), timeout=15)


def read_url(url, limit=2 * 1024 * 1024):
    deadline = time.monotonic() + 45
    data = bytearray()
    with open_url(url) as response:
        allowed_url(response.geturl())
        while True:
            part = getattr(response, 'read1', response.read)(16384)
            data.extend(part)
            if len(data) > limit or time.monotonic() > deadline:
                raise ValueError('更新响应过大或读取超时')
            if not part:
                break
    return bytes(data)


def release_info(data):
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('未找到可用的正式版本')
    tag = data.get('tag_name')
    number = '.'.join(map(str, version(tag)))
    prefix = REPO + '/releases/download/' + tag + '/'
    name = 'EdaKit-' + number + '-Setup.exe'
    assets = data.get('assets', [])
    if not isinstance(assets, list):
        raise ValueError('发布附件无效')
    found = {}
    for a in assets:
        if not isinstance(a, dict) or a.get('name') not in (name, 'SHA256SUMS.txt'):
            continue
        url = a.get('browser_download_url', '')
        if url != prefix + a['name'] or a.get('state') != 'uploaded':
            raise ValueError('发布附件地址或状态无效')
        allowed_url(url)
        found[a['name']] = a
    asset = found.get(name)
    if not asset or type(asset.get('size')) is not int or not 0 < asset['size'] <= MAX_SETUP:
        raise ValueError('此 Release 缺少对应的 Windows 安装包')
    digest = asset.get('digest') or ''
    sha = digest[7:] if re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest) else ''
    checksum = found.get('SHA256SUMS.txt', {}).get('browser_download_url', '')
    if not sha and not checksum:
        raise ValueError('发布未提供 SHA-256 校验，禁止自动安装')
    return {'version': number, 'tag': tag, 'name': name, 'url': asset['browser_download_url'],
            'size': asset['size'], 'sha256': sha.lower(), 'checksum': checksum,
            'page': REPO + '/releases/tag/' + tag,
            'notes': str(data.get('body') or '')[:64000]}


def checksum_for(info):
    if info['sha256']:
        return info['sha256']
    text = read_url(info['checksum'], 65536).decode('utf-8-sig')
    for line in text.splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})\s+\*?(.+)', line.strip())
        if match and match[2] == info['name']:
            return match[1].lower()
    raise ValueError('校验文件中没有对应安装包')


def installation():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise ValueError('自动安装仅支持已安装的 Windows 程序')
    root = Path(sys.executable).resolve().parent
    ini = root / 'deployment.ini'
    if not ini.is_file() or not (root / 'edakit-cli.exe').is_file():
        raise ValueError('找不到安装记录，请从 Releases 手动安装')
    raw = ini.read_bytes()
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_string(raw.decode('utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'))
    cadence = cfg.get('Cadence', 'Root', fallback='')
    if not cadence or not (Path(cadence) / 'tools/capture/tclscripts').is_dir():
        raise ValueError('Cadence 安装记录无效，请手动安装')
    import winreg
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{8B3F2C1A-4E7D-4A9B-9C22-LCSC2CADENCE01}_is1'
    scopes = []
    for hive, scope in ((winreg.HKEY_CURRENT_USER, 'currentuser'), (winreg.HKEY_LOCAL_MACHINE, 'allusers')):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as registry:
                location = winreg.QueryValueEx(registry, 'InstallLocation')[0]
                if Path(location).resolve() == root:
                    scopes.append(scope)
        except FileNotFoundError:
            pass
    if len(scopes) != 1:
        raise ValueError('无法唯一确认安装范围，请从 Releases 手动安装')
    return root, cadence, scopes[0]


class Updater:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else app_dir() / 'updates'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.active = False
        self.helper = None
        self.helper_process = None
        try:
            self.saved = json.loads((self.directory / 'settings.json').read_text(encoding='utf-8'))
            if not isinstance(self.saved, dict):
                raise ValueError()
        except (OSError, ValueError):
            self.saved = {}
        for key in ('lastAttempt', 'lastChecked'):
            value = self.saved.get(key, 0)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                self.saved[key] = 0
        if type(self.saved.get('autoCheck', True)) is not bool:
            self.saved['autoCheck'] = True
        self.data = {'phase': 'idle', 'message': '尚未检查更新', 'release': None,
                     'downloaded': 0, 'size': 0, 'localVersion': __version__}
        self.package = None
        cached = self.saved.get('release')
        try:
            if isinstance(cached, dict):
                assets = [{'name': cached['name'], 'state': 'uploaded', 'size': cached['size'],
                           'browser_download_url': cached['url'], 'digest': 'sha256:' + cached['sha256']}]
                if cached.get('checksum'):
                    assets.append({'name': 'SHA256SUMS.txt', 'state': 'uploaded',
                                   'browser_download_url': cached['checksum']})
                info = release_info({'tag_name': cached['tag'], 'assets': assets, 'body': cached['notes']})
                newer = version(info['version']) > version(__version__)
                self.data.update(release=info, phase='available' if newer else 'current',
                                 message='发现新版本（上次检查结果）' if newer else '暂无更高正式版本（上次检查结果）')
                package = self.saved.get('package')
                if newer and isinstance(package, dict):
                    path = Path(package['path']).resolve()
                    if path.parent.parent == self.directory.resolve() and re.fullmatch('[a-f0-9]{32}', path.parent.name) and path.name == info['name'] and path.is_file() and package['version'] == info['version']:
                        self.package = package
                        self.data.update(phase='ready', message='上次下载的安装包已保留，安装前会重新校验')
        except (KeyError, ValueError, TypeError, OSError):
            pass

    def save(self):
        atomic_write(self.directory / 'settings.json', json.dumps(self.saved, ensure_ascii=False))

    def snapshot(self):
        with self.lock:
            result = json.loads(json.dumps(self.data))
            result.update(autoCheck=self.saved.get('autoCheck', True), lastChecked=self.saved.get('lastChecked', 0))
            result['canDownload'] = bool(result['release'] and version(result['release']['version']) > version(__version__))
            if self.helper:
                try:
                    state = json.loads((self.helper / 'result.json').read_text(encoding='utf-8'))
                    if not isinstance(state, dict):
                        raise ValueError('Invalid helper result')
                    result['installation'] = state
                    if state.get('phase') in ('cancelled', 'error'):
                        self.helper = None
                        self.data.update(phase='ready', message=state.get('message', '可重新安装'))
                        result.update(phase='ready', message=self.data['message'])
                except (OSError, ValueError):
                    pass
                if self.helper and self.helper_process and self.helper_process.poll() is not None:
                    self.helper = None
                    self.data.update(phase='ready', message='更新助手已退出；可重试，或从 Releases 手动安装')
                    result.update(phase='ready', message=self.data['message'])
            return result

    def start(self, action):
        with self.lock:
            if self.active or self.helper:
                raise ValueError('已有更新任务正在进行')
            self.active = True
            self.cancelled = threading.Event()
            self.data.update(phase='checking' if action == 'check' else 'downloading',
                             message='正在检查 GitHub 正式版本…' if action == 'check' else '正在下载…')
            if action == 'download':
                self.data.update(downloaded=0, size=self.data['release']['size'])
        def run():
            try:
                getattr(self, '_' + action)()
            except Exception as exc:
                with self.lock:
                    self.data.update(phase='cancelled' if self.cancelled.is_set() else 'error',
                                     message='已取消下载' if self.cancelled.is_set() else str(exc))
            finally:
                with self.lock:
                    self.active = False
        threading.Thread(target=run, daemon=True).start()
        return self.snapshot()

    def auto(self):
        if self.saved.get('autoCheck', True) and time.time() - self.saved.get('lastAttempt', 0) >= 86400:
            self.start('check')

    def _check(self):
        with self.lock:
            self.saved['lastAttempt'] = time.time()
            self.save()
        info = release_info(json.loads(read_url(LATEST)))
        newer = version(info['version']) > version(__version__)
        with self.lock:
            self.saved['lastChecked'] = time.time()
            self.saved['latestVersion'] = info['version']
            self.saved['release'] = info
            self.save()
            self.data.update(release=info, phase='available' if newer else 'current',
                             message='发现新版本 ' + info['version'] if newer else '当前没有更高的正式版本')

    def download(self):
        with self.lock:
            info = self.data.get('release')
            if not info or version(info['version']) <= version(__version__):
                raise ValueError('请先检查并选择更高版本')
            if self.package and self.package['version'] == info['version'] and (not info['sha256'] or self.package['sha256'] == info['sha256']):
                self.data.update(phase='ready', message='安装包已就绪')
                return self.snapshot()
            return self.start('download')

    def _download(self):
        info = dict(self.data['release'])
        sha = checksum_for(info)
        job = self.directory / uuid.uuid4().hex
        job.mkdir()
        part, target = job / 'setup.part', job / info['name']
        digest, count = hashlib.sha256(), 0
        deadline = time.monotonic() + 1800
        try:
            with open_url(info['url']) as response, part.open('xb') as output:
                allowed_url(response.geturl())
                while True:
                    if self.cancelled.is_set():
                        raise ValueError('cancelled')
                    chunk = getattr(response, 'read1', response.read)(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > info['size'] or time.monotonic() > deadline:
                        raise ValueError('下载大小异常或超时')
                    output.write(chunk)
                    digest.update(chunk)
                    with self.lock:
                        self.data.update(downloaded=count, size=info['size'])
            if self.cancelled.is_set():
                raise ValueError('cancelled')
            if count != info['size'] or digest.hexdigest() != sha:
                raise ValueError('安装包大小或 SHA-256 校验失败，请重新下载')
            with part.open('rb') as stream:
                if stream.read(2) != b'MZ':
                    raise ValueError('下载文件不是 Windows 安装程序')
            part.replace(target)
            with self.lock:
                self.package = dict(version=info['version'], path=str(target), sha256=sha)
                self.saved['package'] = self.package
                self.save()
                self.data.update(phase='ready', message='下载及 SHA-256 校验通过，可安装更新')
        finally:
            part.unlink(missing_ok=True)

    def install(self):
        with self.lock:
            if self.active or self.helper or self.data['phase'] != 'ready' or not self.package:
                raise ValueError('请先完成安装包下载与校验')
            if self.helper_process and self.helper_process.poll() is None:
                raise ValueError('请关闭旧更新助手，并等待其完全退出后重试')
            root, cadence, scope = installation()
            package = dict(self.package)
            job = Path(package['path']).parent
            if job.resolve().is_relative_to(root):
                raise ValueError('更新缓存与安装目录重合，请手动安装')
            helper = job / 'edakit-update-helper.exe'
            # The helper lives outside the installation directory, so replacing
            # the old program does not replace the executable doing the waiting.
            shutil.copy2(root / 'edakit-cli.exe', helper)
            plan = dict(package, root=str(root), cadence=cadence, scope=scope)
            atomic_write(job / 'plan.json', json.dumps(plan, ensure_ascii=False))
            (job / 'result.json').unlink(missing_ok=True)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            self.helper_process = subprocess.Popen([str(helper), 'update-install', '--plan', str(job / 'plan.json')],
                             cwd=str(job), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, creationflags=flags, close_fds=True,
                             env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
            self.helper = job
            self.data.update(phase='waiting', message='更新助手已打开，请保存工程并退出 Capture、Allegro')
            return self.snapshot()

    def command(self, body):
        action = body.get('action')
        if action == 'check':
            return self.start('check')
        if action == 'download':
            return self.download()
        if action == 'install':
            return self.install()
        if action == 'cancel':
            with self.lock:
                if self.active and self.data['phase'] == 'downloading':
                    self.cancelled.set()
                    self.data.update(message='正在取消下载…')
                else:
                    raise ValueError('当前没有可取消的下载')
            return self.snapshot()
        if action == 'settings' and type(body.get('autoCheck')) is bool:
            with self.lock:
                self.saved['autoCheck'] = body['autoCheck']
                self.save()
            return self.snapshot()
        raise ValueError('Invalid update action')


_manager = None
_manager_lock = threading.Lock()


def manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = Updater()
        return _manager

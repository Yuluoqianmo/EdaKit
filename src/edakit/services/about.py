"""Fixed public project destinations for the workbench About dialog."""
import webbrowser
import os
from ..config import app_dir

LINKS = {
    'github': 'https://github.com/Yuluoqianmo/EdaKit',
    'releases': 'https://github.com/Yuluoqianmo/EdaKit/releases',
    'issues': 'https://github.com/Yuluoqianmo/EdaKit/issues',
}


def open_link(body):
    key = body.get('link')
    if not isinstance(key, str) or key not in LINKS:
        raise ValueError('Unknown project link')
    url = LINKS[key]
    if not webbrowser.open(url, new=2):
        raise ValueError('Cannot open browser; copy the project link instead')
    return {'opened': True, 'url': url}


def open_logs():
    path = app_dir()
    opener = getattr(os, 'startfile', None)
    if opener is None:
        raise ValueError('当前系统不支持打开文件夹：' + str(path))
    try:
        opener(str(path))
    except OSError as exc:
        raise ValueError('无法打开日志目录：' + str(path)) from exc
    return {'opened': True, 'path': str(path)}

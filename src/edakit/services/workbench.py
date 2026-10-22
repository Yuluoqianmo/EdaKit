"""Read native menu navigation as data; never reload a live workbench for a tab."""
import re
from ..bridge.queue import app_dir, _load_kv


def navigation(session):
    if not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', session):
        raise ValueError('Invalid Capture session')
    path = app_dir() / 'workbench' / (session + '.nav')
    if not path.exists():
        return {'revision': '', 'tab': '', 'scope': 'design'}
    if path.stat().st_size > 4096:
        raise ValueError('Invalid navigation frame')
    data = _load_kv(path.read_text(encoding='utf-8-sig'))
    if data.get('tab') not in ('mall', 'properties', 'bom') or data.get('scope') not in ('design', 'selected', 'page'):
        raise ValueError('Invalid workbench navigation')
    return {k: data.get(k, '') for k in ('revision', 'tab', 'scope')}

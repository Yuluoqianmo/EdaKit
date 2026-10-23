"""Session-bound property workbench bridge. UTF-8 hex values are data, never Tcl code."""
import json
import re
import time
import uuid
from .queue import app_dir, _load_kv
from .sessions import resolve_target
from ..storage import atomic_write

LOCKED = {'reference', 'part reference', 'id', 'path', 'occurrence', 'page', 'schematic', 'design', 'source library', 'source package', 'source part'}

def directory():
    path = app_dir() / 'properties'
    path.mkdir(parents=True, exist_ok=True)
    return path

def wire_bytes(value):
    # Tcl 8.5 uses UTF-16 code units in its UTF-8 conversion (CESU-8).
    text = str(value)
    units = text.encode('utf-16-le', errors='surrogatepass')
    return ''.join(chr(int.from_bytes(units[i:i + 2], 'little')) for i in range(0, len(units), 2)).encode('utf-8', errors='surrogatepass')

def encode(data):
    return ''.join(str(k) + '=' + wire_bytes(v).hex() + '\n' for k, v in data.items())

def decode(path):
    return {k: bytes.fromhex(v).decode('utf-8', errors='surrogatepass').encode('utf-16-le', errors='surrogatepass').decode('utf-16-le') for k, v in _load_kv(path.read_text(encoding='ascii')).items()}

def valid_name(name):
    return isinstance(name, str) and 0 < len(name) <= 128 and name == name.strip() and not any(ord(c) < 32 for c in name)

def layout(data=None):
    path = app_dir() / 'properties-layout.json'
    if data is None:
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'templates': {}, 'columns': ['Reference', 'Value', 'PCB Footprint', 'Manufacturer', 'Part Number'], 'widths': {}}
    columns = data.get('columns')
    templates = data.get('templates', {})
    widths = data.get('widths', {})
    if not isinstance(columns, list) or len(columns) > 100 or not all(valid_name(x) for x in columns) or len(set(x.lower() for x in columns)) != len(columns):
        raise ValueError('Invalid property columns')
    if not isinstance(templates, dict) or len(templates) > 30 or not all(valid_name(k) and isinstance(v, list) and len(v) <= 100 and all(valid_name(n) for n in v) for k, v in templates.items()):
        raise ValueError('Invalid templates')
    if not isinstance(widths, dict) or len(widths) > 200 or not all(valid_name(k) and isinstance(v, int) and 80 <= v <= 600 for k, v in widths.items()):
        raise ValueError('Invalid column widths')
    result = {'columns': columns, 'templates': templates, 'widths': widths}
    atomic_write(path, json.dumps(result, ensure_ascii=False))
    return result

def submit(body):
    session = resolve_target(body.get('session', ''))
    if not session:
        raise ValueError('Capture is not connected; open Properties from EdaKit in Capture')
    action = body.get('action', 'snapshot')
    if action not in ('snapshot', 'apply', 'locate'):
        raise ValueError('Invalid property action')
    data = {'session': session, 'action': action, 'expires': int(time.time()) + 120, 'scope': body.get('scope', 'design')}
    if data['scope'] not in ('design', 'selected', 'page'):
        raise ValueError('Invalid scope')
    if action != 'snapshot':
        old = status(body.get('snapshot', ''), session)
        if old.get('state') != 'done' or not old.get('snapshot'):
            raise ValueError('Refresh the component table first')
        snap = old['snapshot']
        data.update(design=snap['design'], root=snap['root'], snapshot=body['snapshot'])
        rows = {r['id']: r for r in snap['rows']}
        changes = body.get('changes', []) if action == 'apply' else [{'id': body.get('id')}]
        if not isinstance(changes, list) or not 0 < len(changes) <= 2000:
            raise ValueError('Select 1 to 2000 cells')
        seen = set()
        for i, change in enumerate(changes):
            if not isinstance(change, dict):
                raise ValueError('Invalid change')
            row = rows.get(change.get('id'))
            if row is None:
                raise ValueError('Unknown component')
            data[f'{i}.id'] = row['id']
            data[f'{i}.reference'] = row['reference']
            if action == 'apply':
                name, value = change.get('name'), change.get('value')
                if not valid_name(name) or name.lower() in LOCKED or row['readonly'].get(name, False):
                    raise ValueError('Property is read-only or invalid: ' + str(name))
                if any(n.lower() == name.lower() and n != name for n in row['props']):
                    raise ValueError('Use the original property name and letter case')
                if not isinstance(value, str) or len(value) > 32768 or '\x00' in value:
                    raise ValueError('Invalid property value')
                key = (row['id'], name.lower())
                if key in seen:
                    raise ValueError('Duplicate property change')
                seen.add(key)
                data.update({f'{i}.name': name, f'{i}.value': value, f'{i}.exists': int(name in row['props']), f'{i}.old': row['props'].get(name, '')})
        data['count'] = len(changes)
    for stale in directory().glob('*.owner'):
        try:
            if re.fullmatch('[a-f0-9]{32}', stale.stem) and time.time() - stale.stat().st_mtime > 7 * 86400:
                for suffix in ('.req', '.req.work', '.resp', '.owner'):
                    stale.with_suffix(suffix).unlink(missing_ok=True)
        except OSError:
            pass  # Another request can prune the same expired receipt.
    job = uuid.uuid4().hex
    atomic_write(directory() / (job + '.owner'), session)
    atomic_write(directory() / (job + '.req'), encode(data))
    return {'job': job, 'state': 'pending'}

def status(job, session):
    if not isinstance(job, str) or not re.fullmatch('[a-f0-9]{32}', job):
        raise ValueError('Invalid property job')
    owner = directory() / (job + '.owner')
    if not owner.exists() or owner.read_text(encoding='utf-8') != session:
        raise ValueError('Property job belongs to another Capture session')
    response = directory() / (job + '.resp')
    if not response.exists():
        # Never replay an interrupted write. Its outcome must be inspected in Capture.
        if time.time() - owner.stat().st_mtime > 125:
            return {'state': 'error', 'message': 'Capture did not finish the request; refresh and verify before retrying'}
        return {'state': 'pending'}
    data = decode(response)
    if data.get('ok') != '1':
        return {'state': 'error', 'message': data.get('message', 'Capture request failed')}
    if data.get('action') == 'snapshot':
        rows = []
        for i in range(int(data['rows'])):
            props, readonly = {}, {}
            for j in range(int(data[f'{i}.props'])):
                key = f'{i}.{j}.'
                name = data[key + 'name']
                props[name] = data[key + 'value']
                readonly[name] = data.get(key + 'readonly') == '1' or name.lower() in LOCKED
            rows.append({'id': data[f'{i}.id'], 'reference': data[f'{i}.reference'], 'path': data[f'{i}.path'], 'props': props, 'readonly': readonly})
        return {'state': 'done', 'snapshot': {'design': data['design'], 'root': data['root'], 'rows': rows}}
    return {'state': 'done', 'results': [{'id': data[f'{i}.id'], 'name': data.get(f'{i}.name', ''), 'state': data[f'{i}.state'], 'message': data.get(f'{i}.message', ''), 'value': data.get(f'{i}.value', '')} for i in range(int(data.get('count', 0)))]}

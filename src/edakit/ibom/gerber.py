"""Gerber configuration drafts; independent of the source PCB database."""
import copy
import difflib
import hashlib
import os
import re
import subprocess
import uuid
from pathlib import Path

from ..config import app_dir

ROLES = {'outline': '板框', 'copper': '铜层', 'mask': '阻焊', 'silk': '丝印', 'paste': '锡膏', 'custom': '自定义'}


def outline_choices(candidates=(), known=(), records=()):
    """Offer native board layers even when geometry heuristics miss them."""
    layers = set(candidates)
    layers.update(known)
    layers.update(layer for record in records for layer in record.get('layers', []))
    layers = {s for s in layers if '/' in s and s.split('/', 1)[0] in ('BOARD GEOMETRY', 'MANUFACTURING') and s.rsplit('/', 1)[-1].upper() != 'CUTOUT'}
    return sorted(layers, key=lambda s: (s != 'BOARD GEOMETRY/OUTLINE', s != 'BOARD GEOMETRY/DESIGN_OUTLINE', s))


def preferred_outline(layers):
    """Prefer standard outer-board names; leave custom layers to the user."""
    for subclass in ('OUTLINE', 'DESIGN_OUTLINE'):
        matches = [s for s in layers if '/' in s and s.rsplit('/', 1)[-1].upper().replace(' ', '_') == subclass]
        if matches:
            return min(matches, key=lambda s: (not s.startswith('BOARD GEOMETRY/'), s))
    return ''


def film_changes(baseline, current):
    """Compare by stable native ID so a rename remains one modification."""
    before = {file['id']: file for file in baseline}
    after = {file['id']: file for file in current}
    def lines(file):
        return [file['name']+'.art', '极性：'+('负片' if file.get('negative') else '正片'),
                '镜像：'+('是' if file.get('mirror') else '否'), *file['layers']]
    changes = []
    for fid in dict.fromkeys([*before, *after]):
        old, new = before.get(fid), after.get(fid)
        if old is not None and new is not None and lines(old) == lines(new):
            continue
        kind = '新增' if old is None else '删除' if new is None else '修改'
        diff = '\n'.join(difflib.unified_diff(lines(old) if old else [], lines(new) if new else [],
                         fromfile='PCB / '+old['name'] if old else 'PCB / 无',
                         tofile='待写入 / '+new['name'] if new else '待写入 / 已删除', lineterm=''))
        changes.append(dict(id=fid, kind=kind, old=old, new=new, diff=diff))
    return changes


def inline_layer_rows(before, after):
    """Display-only union; indices always address their own source list."""
    rows = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for kind, a, b, c, d in matcher.get_opcodes():
        if kind in ('delete', 'replace'):
            rows.extend(dict(layer=before[i], index=i, removed=True, added=False) for i in range(a, b))
        if kind in ('equal', 'insert', 'replace'):
            rows.extend(dict(layer=after[i], index=i, removed=False, added=kind != 'equal') for i in range(c, d))
    return rows


def valid_name(name):
    return bool(name and len(name) <= 64 and not re.search(r'[<>:"/\\|?*\x00-\x1f]', name) and not re.search(r'[. ]$', name) and not re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I))


def film_sort_key(name):
    """Natural ascending order: 1, 2, 10, independent of Artwork output order."""
    return tuple((1, int(part), len(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r'(\d+)', name))


def read_films(board, cadence_root, runner=subprocess.run):
    if not Path(board).is_file():
        raise ValueError('PCB 快照不存在，无法读取 Film 清单')
    folder = app_dir()/'delivery'/'films'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    path = folder/'films.txt'
    root = Path(cadence_root)
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with path.open('wb') as stream:
        result = runner([str(root/'tools/bin/artwork.exe'), '-l', str(Path(board).resolve())], cwd=folder,
                        env=dict(os.environ, CDSROOT=str(root), ALLEGRO_ROOT=str(root)),
                        stdout=stream, stderr=subprocess.STDOUT, timeout=120, **flags)
    names = [line.strip() for line in path.read_text(errors='replace').splitlines() if line.strip()]
    if result.returncode or not names or any(not valid_name(name) for name in names) or len(names) != len(set(names)):
        raise ValueError('未能读取有效 Film 清单，日志：'+str(path))
    return sorted(names, key=film_sort_key)


def read_film_records(path):
    """Read a complete invocation-time SKILL snapshot, never infer mappings from filenames."""
    data = Path(path).read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('mbcs' if os.name == 'nt' else 'gb18030')
    rows = [line.split('\t') for line in text.splitlines()]
    if not rows or rows[0] != ['EDAKIT_FILMS', '1'] or len(rows[-1]) != 2 or rows[-1][0] != 'END':
        raise ValueError('Film 映射读取不完整，请重新从 Allegro 打开生产交付。')
    records, known, names = [], [], {}
    for row in rows[1:-1]:
        if len(row) == 4 and row[0] == 'F' and valid_name(row[1]) and row[2] in ('0', '1') and row[3] in ('0', '1'):
            name = row[1]
            if name.casefold() in names:
                raise ValueError('Film 映射含重复文件名：'+name)
            record = dict(id='existing-'+hashlib.sha256(name.encode()).hexdigest()[:20], name=name,
                          layers=[], negative=row[2] == '1', mirror=row[3] == '1',
                          role='custom', enabled=True, modified=False, origin='pcb')
            names[name.casefold()] = record; records.append(record)
        elif len(row) == 3 and row[0] == 'L' and row[1].casefold() in names and '/' in row[2]:
            names[row[1].casefold()]['layers'].append(row[2])
        elif len(row) == 2 and row[0] == 'K' and '/' in row[1]:
            known.append(row[1])
        elif len(row) == 3 and row[0] == 'P' and row[1] and row[2] in ('0', '1'):
            pass  # read separately without changing the two-value reader API
        else:
            raise ValueError('Film 映射格式无效，请重新从 Allegro 读取。')
    if rows[-1][1] != str(len(records)):
        raise ValueError('Film 映射记录数量不完整。')
    return sorted(records, key=lambda f: film_sort_key(f['name'])), list(dict.fromkeys(known))


def read_layer_polarities(path):
    read_film_records(path)  # reject incomplete sidecars before accepting polarity
    data = Path(path).read_bytes()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('mbcs' if os.name == 'nt' else 'gb18030')
    result = {}
    for row in (line.split('\t') for line in text.splitlines()):
        if row[0] == 'P':
            if row[1] in result:
                raise ValueError('铜层极性记录重复：'+row[1])
            result[row[1]] = row[2] == '1'
    return result


def recommended(copper, outline, known_layers=None):
    if len(copper) < 2 or len(copper) > 64 or len({layer['name'] for layer in copper}) != len(copper):
        raise ValueError('请先读取 PCB 实际叠层；不能根据手填层数生成 Film。')
    if any(layer['kind'] != 'CONDUCTOR' and not isinstance(layer.get('negative'), bool) for layer in copper):
        raise ValueError('叠层含平面层或混合铜层，极性需人工确认；请使用工程已有 Film。')
    if not outline or '/' not in outline or outline.endswith('/CUTOUT'):
        raise ValueError('请先选择完整板框层，CUTOUT 不能单独作为外板框。')
    result = []
    def add(key, name, role, layers, source=''):
        if known_layers is not None:
            layers = [layer for layer in layers if layer in known_layers]
            if not layers:
                return
        result.append(dict(id=key, name=name, role=role, layers=layers, source=source, enabled=True, negative=False, mirror=False, modified=False))
    if known_layers is not None and (outline not in known_layers or any('ETCH/'+c['name'] not in known_layers for c in copper)):
        raise ValueError('PCB 可用层与实际叠层或板框不一致，请重新读取工程。')
    add('outline', '01_OUTLINE', 'outline', [outline])
    for index, layer in enumerate(copper, 2):
        side = layer['name']
        # Number output names; preserve the actual engineering names in layers.
        add('copper-'+side, f'{index:02d}_{side}', 'copper', [group+'/'+side for group in ('ETCH', 'PIN', 'VIA CLASS')], side)
        result[-1]['negative'] = bool(layer.get('negative', False))
    for role, suffix, groups in (
        ('mask', 'SOLDERMASK', ('BOARD GEOMETRY', 'PACKAGE GEOMETRY', 'PIN', 'VIA CLASS')),
        ('silk', 'SILKSCREEN', ('BOARD GEOMETRY', 'PACKAGE GEOMETRY', 'REF DES')),
        ('paste', 'PASTEMASK', ('PIN', 'PACKAGE GEOMETRY')),
    ):
        for side in ('TOP', 'BOTTOM'):
            prefix = {'mask': 'SOLDER', 'silk': 'SILK', 'paste': 'PASTE'}[role]
            add(role+'-'+side, f'{len(result)+1:02d}_{prefix}_{side}', role, [group+'/'+suffix+'_'+side for group in groups], side)
    return result


def identify_records(records, expected):
    """Attach a role by actual member layers; retain names, polarity, and extra members."""
    result = copy.deepcopy(records)
    for file in result:
        matches = []
        for candidate in expected:
            if candidate['role'] == 'copper':
                anchors = ['ETCH/'+candidate['source']]
            elif candidate['role'] == 'outline':
                anchors = candidate['layers']
            else:
                anchors = candidate['layers']
            if any(layer in file['layers'] for layer in anchors):
                matches.append(candidate)
        # Additional outline lines in a copper Film do not make it an outline Film.
        if len(matches) > 1:
            matches = [candidate for candidate in matches if candidate['role'] != 'outline']
        if len(matches) > 1:
            raise ValueError('已有 Film 混合了多个制板用途，不能自动补齐：'+file['name'])
        if len(matches) == 1:
            candidate = matches[0]
            file.update(role=candidate['role'], source=candidate.get('source', ''), match=candidate['id'])
    return result


def merge(files, expected, replace=False):
    if replace:
        return copy.deepcopy(expected), [f['name']+'.art' for f in expected], [], []
    result, added, fixed, kept = copy.deepcopy(files), [], [], []
    for candidate in expected:
        matches = [f for f in result if f.get('match', f['id']) == candidate['id']]
        if len(matches) > 1:
            raise ValueError('多个已有 Film 对应同一用途，请人工核对：'+', '.join(f['name'] for f in matches))
        existing = matches[0] if matches else None
        if existing is None:
            new = copy.deepcopy(candidate)
            if any(f['name'].casefold() == new['name'].casefold() for f in result):
                serial = 1
                while any(f['name'].casefold() == (candidate['name']+'_'+str(serial)).casefold() for f in result):
                    serial += 1
                new['name'] += '_'+str(serial)
            result.append(new); added.append(new['name']+'.art')
        elif existing.get('modified'):
            kept.append(existing['name']+'.art')
        else:
            missing = [layer for layer in candidate['layers'] if layer not in existing['layers']]
            if missing:
                existing['layers'] += missing; fixed.append(existing['name']+'：'+', '.join(missing))
    order = {f['id']: i for i, f in enumerate(expected)}
    result.sort(key=lambda f: order.get(f.get('match', f['id']), len(expected)))
    return result, added, fixed, kept


def configuration_base(records, draft, expected):
    """Rebase edits on actual Film records; drop obsolete automatically generated drafts."""
    result = identify_records(records, expected)
    for file in identify_records(draft, expected):
        target = next((i for i, actual in enumerate(result)
                       if actual['id'] == file['id'] or actual.get('match') and actual.get('match') == file.get('match')), None)
        if target is not None:
            if file.get('modified'):
                result[target] = file
            elif 'enabled' in file:
                result[target]['enabled'] = file['enabled']
        elif file.get('modified'):
            result.append(file)
    return result


def review(files, copper, outline, known_layers=(), *, full_inventory=False):
    issues, names, enabled = [], set(), [f for f in files if f.get('enabled', True)]
    def add(level, text, file=None, index=None):
        issues.append(dict(level=level, text=text, file=file, index=index))
    if not enabled:
        add('错误', '未勾选任何 Film。')
    for file in enabled:
        fid, name, layers = file['id'], file['name'], file['layers']
        if not valid_name(name) or name.casefold() in names:
            add('错误', '文件名无效或重复：'+name, fid)
        names.add(name.casefold())
        if not layers:
            add('错误', '文件未包含子层。', fid)
        for index, layer in enumerate(layers):
            if '/' not in layer or layer in layers[:index]:
                add('错误', '子层格式无效或重复：'+layer, fid, index)
            if full_inventory and layer not in known_layers:
                add('错误', '当前 PCB 中不存在此子层：'+layer, fid, index)
            if layer.startswith(('ETCH/', 'PIN/', 'VIA CLASS/')) and layer.split('/', 1)[1] not in {c['name'] for c in copper} and not any(x in layer for x in ('MASK_', 'SCREEN_')):
                add('错误', '铜层不在当前叠层中：'+layer, fid, index)
        if file.get('role') == 'copper':
            source = file.get('source') or next((x.split('/', 1)[1] for x in layers if x.startswith('ETCH/')), '')
            for group in ('ETCH', 'PIN', 'VIA CLASS'):
                if (not full_inventory or group+'/'+source in known_layers) and group+'/'+source not in layers:
                    add('错误', '铜层缺少 '+group+'/'+source, fid)
        if file.get('mirror') or file.get('negative'):
            add('提示', '已设置镜像或负片，请人工确认。', fid)
    for layer in copper:
        if not any(f.get('role') == 'copper' and 'ETCH/'+layer['name'] in f['layers'] for f in enabled):
            add('错误', '缺少铜层输出：'+layer['name'])
    if not outline or not any(f.get('role') == 'outline' and outline in f['layers'] for f in enabled):
        add('错误', '缺少选定板框输出。')
    if not any(i['level'] == '错误' for i in issues):
        add('通过', '配置结构检查通过。')
    add('人工核对', '结构核对不等同于制造几何检查；极性、板框闭合、钻孔与原点需核对实际工程。')
    return issues

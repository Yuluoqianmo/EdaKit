"""Production export on a private board snapshot; publish only a complete run."""
import io
import hashlib
import math
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from defusedxml.minidom import parseString

from ..config import app_dir
from ..services import bom as xlsx
from . import exporter, manufacturing


def output_directory(source):
    parent = Path(source).resolve().parent
    return next((p for p in parent.iterdir() if p.is_dir() and p.name.casefold() == 'output files'), parent / 'Output files')


def builtin_template():
    return Path(__file__).with_name('templates')/'production.xlsx'


def manufacturing_parameters(source, destination):
    """Find saved settings for this board without asking for another output path."""
    source = Path(source).resolve()
    folders = [source.parent, Path(destination), output_directory(source)]
    candidates = []
    for folder in folders:
        if not folder.is_dir():
            continue
        candidates.append(folder)
        children = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name.casefold())
        preferred = {source.stem.casefold()+suffix for suffix in ('_art', '_gerber', '-gerber')}
        candidates.extend(p for p in children if p.name.casefold() in preferred)
        candidates.extend(p for p in children if p.name.casefold() == 'gerber')
    seen = set()
    for candidate in candidates:
        key = str(candidate.resolve()).casefold()
        if key in seen:
            continue
        seen.add(key)
        if all((candidate/name).is_file() for name in ('art_param.txt', 'nc_param.txt')):
            return candidate
    # Historical projects may use a custom name for their manufacturing folder.
    matches = {}
    for folder in folders:
        if folder.is_dir():
            for candidate in folder.iterdir():
                if candidate.is_dir() and all((candidate/name).is_file() for name in ('art_param.txt', 'nc_param.txt')):
                    matches[str(candidate.resolve()).casefold()] = candidate
    if len(matches) == 1:
        return next(iter(matches.values()))
    if matches:
        raise ValueError('发现多套制造参数，无法确认当前 PCB 使用哪一套。请将当前工程的 art_param.txt 和 nc_param.txt 保存到 PCB 所在目录。')
    raise ValueError('未找到当前工程的 art_param.txt 和 nc_param.txt。请先在 Allegro 中保存 Artwork 和 NC Drill 参数到 PCB 所在目录或 Output files 下。')


def initial_values(fields, source, template_data, saved):
    previous = saved.get('boards', {}).get(exporter.board_key(source), {})
    values = previous.get('values', {}) if previous.get('templateHash') == hashlib.sha256(template_data).hexdigest() else {}
    result = []
    for field in fields:
        key, label = field['sheet']+'!'+field['ref'], field['label']
        value = values.get(key, '')
        # Older versions saved PCB stackup references as order selections.
        if label in manufacturing.REFERENCE_ONLY and previous.get('autoValues', {}).get(key) == value:
            value = ''
        fallback = Path(source).stem if label == '型号' else manufacturing.default_value(field['sheet'], label)
        use_default = not value and key not in previous.get('clearedDefaults', [])
        item = dict(field, value=fallback if use_default else value)
        if use_default and field['sheet'] == 'PCB说明' and label in manufacturing.DEFAULT_PARTS:
            item['spec'] = dict(manufacturing.DEFAULT_PARTS[label])
        result.append(item)
    return result


def remember_values(saved, source, template_data, fields, output=None):
    previous = saved.setdefault('boards', {}).setdefault(exporter.board_key(source), {})
    previous.update({
        'templateHash': hashlib.sha256(template_data).hexdigest(),
        'values': {f['sheet']+'!'+f['ref']: f['value'] for f in fields},
        'clearedDefaults': [f['sheet']+'!'+f['ref'] for f in fields
                            if not f['value'] and manufacturing.default_value(f['sheet'], f['label'])],
    })
    if output is not None:
        previous['outputFolder'] = str(output)


def template_fields(data):
    fields = []
    with xlsx.workbook(data) as z:
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(n.itertext()) for n in xlsx.xml(z.read('xl/sharedStrings.xml'))]
        for title, path in xlsx.sheets(z):
            if title not in ('PCB说明', '钢网'):
                continue
            sheet = xlsx.xml(z.read(path))
            cells = {}
            for c in sheet.iter(xlsx.tag('c')):
                v = c.find(xlsx.tag('v'))
                value = v.text or '' if v is not None else ''.join(c.find(xlsx.tag('is')).itertext()) if c.find(xlsx.tag('is')) is not None else ''
                cells[c.get('r')] = strings[int(value)] if c.get('t') == 's' else value
            choices = {}
            for validation in sheet.iter(xlsx.tag('dataValidation')):
                f = validation.find(xlsx.tag('formula1'))
                m = re.fullmatch(r'\$?([A-Z]+)\$?(\d+):\$?\1\$?(\d+)', f.text or '') if f is not None else None
                if m:
                    values = [cells.get(m[1]+str(i), '') for i in range(int(m[2]), int(m[3])+1)]
                    for ref in validation.get('sqref', '').split():
                        choices[ref] = values
            for row in sheet.findall(xlsx.tag('sheetData')+'/'+xlsx.tag('row')):
                number = row.get('r')
                label = cells.get('B'+number, '')
                if label:
                    if title == 'PCB说明' and label in manufacturing.REMOVED:
                        continue
                    label = '板框层' if label == '切边层' else label
                    ref = 'C'+number
                    options = choices.get(ref, [])
                    if title == '钢网' and label == '钢网尺寸':
                        options = list(manufacturing.STENCIL_SIZES)
                    if title == '钢网' and label == '数量':
                        options = ['1', '2', '3', '4', '5', '10']
                    fields.append(dict(sheet=title, path=path, ref=ref, label=label, value=cells.get(ref, ''), choices=options))
    if {f['sheet'] for f in fields} != {'PCB说明', '钢网'}:
        raise ValueError('模板需要包含 PCB说明、钢网工作表及 B 列字段、C 列内容')
    return fields


def fill_template(data, fields):
    # Patch only the destination cells. Preserve validations, printing and styles.
    output = io.BytesIO()
    with xlsx.workbook(data) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        pcb_path = next((path for title, path in xlsx.sheets(source) if title == 'PCB说明'), None)
        strings = xlsx.xml(source.read('xl/sharedStrings.xml')) if 'xl/sharedStrings.xml' in source.namelist() else []
        for item in source.infolist():
            content = source.read(item.filename)
            edits = [f for f in fields if f['path'] == item.filename]
            if edits:
                # DOM retains namespace declarations referenced by mc:Ignorable
                # and extension attributes even when no element uses the prefix.
                root = parseString(content, forbid_dtd=True, forbid_entities=True, forbid_external=True)
                cells = root.getElementsByTagNameNS(xlsx.NS, 'c')
                prefix = root.documentElement.prefix
                def element(name, root=root, prefix=prefix):
                    return root.createElementNS(xlsx.NS, (prefix + ':' if prefix else '') + name)
                # Retain workbook formatting while hiding removed manufacturing rows
                # and clearing their old example values from the delivered workbook.
                for row in root.getElementsByTagNameNS(xlsx.NS, 'row'):
                    label_cell = next((c for c in row.getElementsByTagNameNS(xlsx.NS, 'c') if c.getAttribute('r') == 'B'+row.getAttribute('r')), None)
                    if label_cell is None:
                        continue
                    texts = ''.join(n.firstChild.data for n in label_cell.getElementsByTagNameNS(xlsx.NS, 't') if n.firstChild)
                    if label_cell.getAttribute('t') == 's':
                        index = label_cell.getElementsByTagNameNS(xlsx.NS, 'v')[0].firstChild.data
                        texts = ''.join(list(strings)[int(index)].itertext())
                    if texts in manufacturing.DELETED and item.filename == pcb_path:
                        row.parentNode.removeChild(row)
                        continue
                    if texts in manufacturing.REMOVED:
                        row.setAttribute('hidden', '1')
                        for c in row.getElementsByTagNameNS(xlsx.NS, 'c'):
                            if c.getAttribute('r') == 'C'+row.getAttribute('r'):
                                for child in list(c.childNodes):
                                    c.removeChild(child)
                                if c.hasAttribute('t'):
                                    c.removeAttribute('t')
                    elif texts == '切边层':
                        for child in list(label_cell.childNodes):
                            label_cell.removeChild(child)
                        label_cell.setAttribute('t', 'inlineStr')
                        inline, text = element('is'), element('t')
                        text.appendChild(root.createTextNode('板框层'))
                        inline.appendChild(text); label_cell.appendChild(inline)
                for field in edits:
                    if field.get('sheet') == 'PCB说明' and field.get('label') in manufacturing.DELETED:
                        continue
                    ref = field['ref']
                    cell = next((c for c in cells if c.getAttribute('r') == ref), None)
                    if cell is None:
                        row = next(r for r in root.getElementsByTagNameNS(xlsx.NS, 'row') if r.getAttribute('r') == ref[1:])
                        cell = element('c'); cell.setAttribute('r', ref)
                        after = next((c for c in row.childNodes if c.nodeType == c.ELEMENT_NODE and c.localName == 'c' and (len(c.getAttribute('r').rstrip('0123456789')), c.getAttribute('r').rstrip('0123456789')) > (1, 'C')), None)
                        row.insertBefore(cell, after)
                    for child in list(cell.childNodes):
                        cell.removeChild(child)
                    cell.setAttribute('t', 'inlineStr')
                    inline, text = element('is'), element('t')
                    text.setAttribute('xml:space', 'preserve')
                    text.appendChild(root.createTextNode(str(field['value'])))
                    inline.appendChild(text); cell.appendChild(inline)
                content = root.toxml(encoding='utf-8')
                root.unlink()
            target.writestr(item, content)
    return output.getvalue()


def placements(text, detailed=False):
    lines = text.splitlines()
    header = next(l.split('!')[1:-1] for l in lines if l.startswith('A!'))
    info = next(l.split('!') for l in lines if l.startswith('J!'))
    factors = {'mils': .0254, 'millimeters': 1.0, 'inches': 25.4}
    if len(info) < 9 or info[8].lower() not in factors:
        raise ValueError('无法确认原生坐标单位')
    scale = factors[info[8].lower()]
    rows, seen = [], set()
    for line in lines:
        if not line.startswith('S!'):
            continue
        r = dict(zip(header, line.split('!')[1:-1]))
        ref = r['REFDES']
        if not ref or ref in seen or r['SYM_MIRROR'] not in ('YES', 'NO'):
            raise ValueError('器件位号重复、为空或板面未知')
        seen.add(ref)
        x, y, angle = (float(r[k]) for k in ('SYM_X', 'SYM_Y', 'SYM_ROTATE'))
        if not all(math.isfinite(v) for v in (x, y, angle)):
            raise ValueError('器件坐标或角度无效：'+ref)
        values = [round(x*scale, 6), round(y*scale, 6), angle, 'B' if r['SYM_MIRROR'] == 'YES' else 'T']
        rows.append([ref] + ([r.get(k, '') for k in ('COMP_DEVICE_TYPE', 'COMP_VALUE', 'COMP_TOL', 'COMP_PACKAGE')] if detailed else []) + values)
    if not rows:
        raise ValueError('没有已放置器件')
    return sorted(rows, key=lambda r: xlsx.natural(r[0]))


def coordinate_book(rows, metadata=None):
    from ..services import report_template
    expanded = [r if len(r) == 9 else [r[0], '', '', '', '', *r[1:]] for r in rows]
    return report_template.fill(report_template.path('coordinates').read_bytes(), expanded,
        dict({'date': __import__('datetime').date.today().isoformat()}, **(metadata or {}), kind='坐标文件'), numeric=(5, 6, 7))


OUTPUTS = ('gerber', 'coordinates', 'instructions', 'ibom')


def run(board, source, cadence_root, parameters=None, template=None, fields=None, *, output=None, labels=None, overwrite=False, outputs=None, ibom_bom=None, ibom_use_board=True, film_names=None, gerber_board=None, report_metadata=None, progress=lambda s: None, runner=subprocess.run):
    source, root = Path(source).resolve(), Path(cadence_root)
    destination = output_directory(source) if output is None else Path(output).expanduser()
    if not destination.is_absolute():
        raise ValueError('请选择完整的输出目录')
    destination = destination.resolve()
    if destination.exists() and not destination.is_dir():
        raise ValueError('输出路径必须是文件夹')
    selected = set(OUTPUTS if outputs is None else outputs)
    if not selected or selected.difference(OUTPUTS):
        raise ValueError('请至少选择一种有效的输出内容')
    if 'ibom' in selected and not ibom_use_board and (not ibom_bom or not Path(ibom_bom).is_file()):
        raise ValueError('请选择存在的最终 BOM 文件')
    if 'gerber' in selected:
        parameters = Path(parameters) if parameters is not None else manufacturing_parameters(source, destination)
        for name in ('art_param.txt', 'nc_param.txt'):
            if not (parameters/name).is_file():
                raise ValueError('制造参数目录缺少 '+name)
    if 'instructions' in selected:
        data = Path(template if template is not None else builtin_template()).read_bytes()
        if fields is None:
            fields = initial_values(template_fields(data), source, data, {})
        errors = manufacturing.validate(fields)
        if errors:
            raise ValueError('\n'.join(errors))
    job = app_dir()/'delivery'/uuid.uuid4().hex
    work, stage = job/'work', job/'stage'
    work.mkdir(parents=True); stage.mkdir()
    if selected.intersection(('gerber', 'coordinates', 'ibom')):
        shutil.copy2(board, work/'board.brd')
    artwork_board = 'board.brd'
    if 'gerber' in selected and gerber_board is not None:
        if not Path(gerber_board).is_file() or not Path(gerber_board).stat().st_size:
            raise ValueError('核验后的 Gerber PCB 快照缺失，未执行导出')
        artwork_board = 'gerber.brd'
        shutil.copy2(gerber_board, work/artwork_board)
    if 'gerber' in selected:
        for name in ('art_param.txt', 'nc_param.txt', 'art_aper.txt', 'ncroutebits.txt'):
            if (parameters/name).is_file():
                shutil.copy2(parameters/name, work/name)
        # NC parameter paths override command-line names on Cadence 17.2.
        # Rewrite only the private copy, never a saved project parameter file.
        nc = work/'nc_param.txt'
        content = nc.read_bytes()
        for key, name in ((b'TAPE-FILE', 'board.drl'), (b'ROUTE-FILE', 'route.rou')):
            content = re.sub(rb'(?im)^[ \t]*' + key + rb'\b[^\r\n]*(?:\r?\n|$)', b'', content)
            content += b'\n' + key + b' ' + (work/name).as_posix().encode('utf-8') + b'\n'
        nc.write_bytes(content)
    env = dict(os.environ, CDSROOT=str(root), ALLEGRO_ROOT=str(root), NCDPATH=str(work))
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    def execute(exe, arguments, log, allowed=(0,)):
        with (work/log).open('wb') as f:
            r = runner([str(root/'tools/bin'/exe), *arguments], cwd=work, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=300, **flags)
        if r.returncode not in allowed:
            raise ValueError(exe+' 执行失败，日志：'+str(work/log))
    log, rows = '', []
    if 'gerber' in selected:
        progress('正在生成 Gerber 与钻孔文件')
        execute('artwork.exe', ['-l', artwork_board], 'films.txt')
        films = [s.strip() for s in (work/'films.txt').read_text(errors='replace').splitlines() if s.strip()]
        if not films or any(re.search(r'[<>:"/\\|?*]', f) or f in ('.', '..') for f in films):
            raise ValueError('未找到有效的 Artwork Film 定义')
        if film_names is not None:
            if not film_names or len(film_names) != len(set(film_names)) or set(film_names).difference(films):
                raise ValueError('所选 Film 已不存在或未勾选任何文件，请重新读取工程配置')
            films = list(film_names)
        execute('artwork.exe', [part for name in films for part in ('-f', name)]+[artwork_board], 'artwork-command.log', (0, 1))
        log = (work/'photoplot.log').read_text(errors='replace')
        if re.search(r'^\s*(?:ERROR\b|FATAL\b)', log, re.M | re.I):
            raise ValueError('Gerber 日志存在错误（请检查动态铜皮等），未写入交付目录。日志：'+str(work/'photoplot.log'))
        execute('nctape.exe', ['-n', str(work/'board.drl'), artwork_board], 'drill-command.log')
        execute('ncroute.exe', ['-o', str(work/'route.rou'), artwork_board], 'route-command.log')
        for name in ('ncdrill.log', 'ncroute.log'):
            detail = (work/name).read_text(errors='replace')
            if re.search(r'^\s*(?:ERROR\b|FATAL\b)', detail, re.M | re.I):
                raise ValueError('钻孔或槽铣日志存在错误：'+str(work/name))
            log += '\n'+detail
        gerbers, drills = list(work.glob('*.art')), list(work.glob('*.drl'))
        routes = list(work.glob('*.rou'))
        if {p.stem.casefold() for p in gerbers} != {f.casefold() for f in films}:
            raise ValueError('Gerber 输出与工程 Film 定义不完整对应')
        if not gerbers or not drills or any(p.stat().st_size == 0 for p in gerbers+drills+routes):
            raise ValueError('Gerber 或钻孔文件缺失、为空')
        (stage/'Gerber').mkdir()
        for p in gerbers+drills+routes:
            name = source.stem+p.name[len('board'):] if p.suffix == '.drl' and p.stem.split('-')[0] == 'board' else source.stem+p.name[len('route'):] if p.suffix == '.rou' and p.name.startswith('route') else p.name
            shutil.copy2(p, stage/'Gerber'/name)
    if 'coordinates' in selected:
        progress('正在读取器件坐标并生成 Excel')
        command = work/'coordinates.txt'
        command.write_text('COMPONENT\nREFDES\nCOMP_DEVICE_TYPE\nCOMP_VALUE\nCOMP_TOL\nCOMP_PACKAGE\nSYM_X\nSYM_Y\nSYM_ROTATE\nSYM_MIRROR\n', encoding='ascii')
        execute('extracta.exe', ['board.brd', str(command), 'components.txt'], 'extract-command.log')
        rows = placements((work/'components.txt').read_text(errors='replace'), detailed=True)
        (stage/(source.stem+'-坐标文件.xlsx')).write_bytes(coordinate_book(rows, dict(report_metadata or {}, title=source.stem)))
    if 'instructions' in selected:
        progress('正在生成制板说明 Excel')
        (stage/(source.stem+'-加工说明.xlsx')).write_bytes(fill_template(data, fields))
    if 'ibom' in selected:
        progress('正在生成交互式 BOM')
        receipt = exporter.generate(work/'board.brd', source=source, output=job/'ibom', cadence_root=root, use_board=ibom_use_board, bom=ibom_bom, labels=labels, progress=progress)
        shutil.copy2(receipt['html'], stage/(source.stem+'-iBOM.html'))
    files = [p.relative_to(stage) for p in stage.rglob('*') if p.is_file()]
    (work/'manufacturing.log').write_text(log, encoding='utf-8')
    destination.mkdir(parents=True, exist_ok=True)
    collisions = [str(p) for p in files if (destination/p).exists()]
    if collisions and not overwrite:
        raise ValueError('同名文件已存在，请勾选确认覆盖后重新导出：'+', '.join(collisions))
    # Back up only the exact files being replaced; rollback a partial publish.
    backup = job/'backup'; backup.mkdir()
    written = []
    try:
        for rel in files:
            target = destination/rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                (backup/rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup/rel)
            if overwrite:
                written.append(rel)
                shutil.copy2(stage/rel, target)
            else:
                with target.open('xb') as output, (stage/rel).open('rb') as input_file:
                    written.append(rel)
                    shutil.copyfileobj(input_file, output)
    except Exception:
        for rel in reversed(written):
            if (backup/rel).exists():
                shutil.copy2(backup/rel, destination/rel)
            else:
                (destination/rel).unlink(missing_ok=True)
        raise
    warnings = 'WARNING' in log.upper()
    return dict(folder=str(destination), files=len(files), components=len(rows), warnings=warnings, log=str(work/'manufacturing.log'))

"""Read-only Capture BOM projection and dependency-free OOXML interchange.

The runtime exporter rebuilds the workbook package, retaining template cell
styles/widths but never its old BOM data, macros, formulas or external links.
"""
from __future__ import annotations

import base64
import copy
import csv
import datetime
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from ..bridge.queue import app_dir
from ..bridge.properties import status
from ..storage import atomic_write

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
HEADERS = ['序号', '类型', '描述', '位号', '值', '封装', '数量', '厂家', '厂家型号', '物料编码']
FIELDS = {'描述': 'Description', '值': 'Value', '封装': 'PCB Footprint', '厂家': 'Manufacturer'}
TYPES = ['测试点', '电容', '二极管', '电感', '晶体管', '电阻', '电源变压器', '功能芯片', '电源管理芯片', '通用处理器', '晶振']
ET.register_namespace('', NS)


def tag(name):
    return '{' + NS + '}' + name


def directory():
    p = app_dir() / 'bom'
    p.mkdir(parents=True, exist_ok=True)
    return p


def natural(value):
    return [(0, int(x)) if x.isdigit() else (1, x.casefold()) for x in re.split(r'(\d+)', value)]


def normalized(value):
    # Preserve punctuation and internal whitespace: these can identify a variant.
    return str(value).strip().casefold()


def xml(data):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('不支持包含 XML 实体的工作簿')
    return ET.fromstring(data)


def workbook(data):
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if len(z.infolist()) > 2000 or sum(x.file_size for x in z.infolist()) > 40_000_000:
            raise ValueError('工作簿解压大小超过限制')
        return z
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError('请选择有效的 .xlsx 文件') from exc


def sheets(z):
    rels = xml(z.read('xl/_rels/workbook.xml.rels'))
    targets = {x.get('Id'): x.get('Target', '') for x in rels}
    out = []
    for sheet in xml(z.read('xl/workbook.xml')).find(tag('sheets')):
        target = targets[sheet.get('{' + REL + '}id')]
        path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        if '..' in path.split('/') or path not in z.namelist():
            raise ValueError('工作表路径无效')
        out.append((sheet.get('name'), path))
    return out


def cells(z, path):
    strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        strings = [''.join(n.itertext()) if not list(n) else ''.join(t.text or '' for t in n.iter(tag('t'))) for n in xml(z.read('xl/sharedStrings.xml'))]
    result = []
    for row in xml(z.read(path)).findall('.//' + tag('sheetData') + '/' + tag('row')):
        number = int(row.get('r', str(len(result) + 1)))
        if number > 100000 or number < len(result) + 1:
            raise ValueError('编码表行号无效或超过 100000 行')
        while len(result) < number - 1:
            result.append({})
        values = {}
        for c in row:
            col = re.sub(r'\d', '', c.get('r', ''))
            value = c.findtext(tag('v'), '')
            if c.get('t') == 's':
                value = strings[int(value)] if value else ''
            elif c.get('t') == 'inlineStr':
                value = ''.join(t.text or '' for t in c.iter(tag('t')))
            values[col] = value
        result.append(values)
    return result


def table(data, name, sheet=''):
    if name.lower().endswith('.csv'):
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = data.decode('gb18030')
        lines = list(csv.reader(io.StringIO(text)))
        return [{str(i): v for i, v in enumerate(line)} for line in lines]
    with workbook(data) as z:
        available = sheets(z)
        selected = [s for s in available if s[0] == sheet] if sheet else available[:1]
        if not selected:
            raise ValueError('找不到所选工作表')
        return cells(z, selected[0][1])


def config():
    p = directory() / 'settings.json'
    data = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    data.setdefault('mapping', dict(FIELDS))
    data.setdefault('typeProperty', 'Type')
    data['template'] = (directory() / 'template.xlsx').exists()
    data.setdefault('templateName', '默认中文 BOM 布局')
    return data


def settings(body):
    mapping = body.get('mapping', FIELDS)
    if not isinstance(mapping, dict) or set(mapping) != set(FIELDS) or not all(isinstance(v, str) and 0 < len(v.strip()) <= 128 for v in mapping.values()):
        raise ValueError('属性映射无效')
    prop = body.get('typeProperty', 'Type')
    if not isinstance(prop, str) or not 0 < len(prop.strip()) <= 128:
        raise ValueError('类型属性名称无效')
    old = config()
    old.update(mapping=mapping, typeProperty=prop.strip())
    atomic_write(directory() / 'settings.json', json.dumps(old, ensure_ascii=False))
    return config()


def upload(body):
    try:
        return _upload(body)
    except (KeyError, IndexError, ET.ParseError, UnicodeError) as exc:
        raise ValueError('文件结构或编码无效，请在 Excel 中检查后另存为 .xlsx 或 CSV') from exc


def _upload(body):
    try:
        data = base64.b64decode(body.get('data', ''), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('文件数据无效') from exc
    if not data or len(data) > 8_000_000:
        raise ValueError('请选择小于 8 MB 的文件')
    name = str(body.get('name', ''))
    kind = body.get('kind')
    if kind == 'template':
        with workbook(data) as z:
            available = sheets(z)
            if len(available) != 1:
                raise ValueError('模板须为单工作表，第二行须包含十列中文表头')
            if 'xl/styles.xml' not in z.namelist():
                raise ValueError('模板缺少单元格样式，请在 Excel 中重新保存')
            rows = cells(z, available[0][1])
            if len(rows) < 3 or [rows[1].get(chr(65 + i), '') for i in range(10)] != HEADERS:
                raise ValueError('模板第二行须依次为：' + '、'.join(HEADERS))
        atomic_write(directory() / 'template.xlsx', data)
        c = config()
        c['templateName'] = name
        atomic_write(directory() / 'settings.json', json.dumps(c, ensure_ascii=False))
        return config()
    if kind != 'codes' or not name.lower().endswith(('.xlsx', '.csv')):
        raise ValueError('编码表支持 .xlsx 或 .csv')
    rows = table(data, name, body.get('sheet', ''))
    # Preview columns first. Import is explicit so arbitrary table names are supported.
    header_index = body.get('headerRow', 1)
    if not isinstance(header_index, int) or not 1 <= header_index <= min(100, len(rows)):
        raise ValueError('表头行无效')
    header = rows[header_index - 1]
    if not body.get('pnColumn') or not body.get('codeColumn'):
        return {'columns': header, 'sheets': [s[0] for s in sheets(workbook(data))] if name.lower().endswith('.xlsx') else [], 'rows': len(rows) - header_index}
    pn, code, typ = body['pnColumn'], body['codeColumn'], body.get('typeColumn', '')
    if pn not in header or code not in header or pn == code or (typ and typ not in header):
        raise ValueError('请选择有效的型号、物料编码和类型列')
    records = defaultdict(set)
    for r in rows[header_index:]:
        key, value = normalized(r.get(pn, '')), r.get(code, '').strip()
        if key:
            records[key].add((value, r.get(typ, '').strip() if typ else ''))
    output = {k: sorted(v) for k, v in records.items()}
    atomic_write(directory() / 'codes.json', json.dumps({'name': name, 'records': output}, ensure_ascii=False))
    return {'name': name, 'models': len(output), 'conflicts': sum(len(v) > 1 for v in output.values())}


def classify(reference, props, description, type_property):
    explicit = props.get(type_property, '').strip()
    if explicit:
        return explicit, 'Capture ' + type_property
    prefix = re.match(r'[A-Za-z]+', reference)
    kind = {'C': '电容', 'R': '电阻', 'L': '电感', 'D': '二极管', 'Q': '晶体管', 'Y': '晶振'}.get(prefix[0].upper() if prefix else '')
    if kind:
        return kind, '位号规则'
    if re.search(r'变压器|transformer', description, re.I):
        return '电源变压器', '描述规则'
    if re.search(r'微控制器|微处理器|\bMCU\b|microcontroller|microprocessor', description, re.I):
        return '通用处理器', '描述规则'
    if re.search(r'电源管理|稳压器|DC[ -]?DC|LDO|voltage regulator|buck converter|boost converter', description, re.I):
        return '电源管理芯片', '描述规则'
    if re.search(r'运放|运算放大器|模拟开关|电平转换|监控电路|参考电压|温度传感器|接口集成电路|\bADC\b|\bDAC\b|operational amplifier', description, re.I):
        return '功能芯片', '描述规则'
    return '待分类', '未命中规则'


def preview(snapshot, cfg=None, codes=None, overrides=None, manual_codes=None):
    cfg = cfg or config()
    if codes is None:
        p = directory() / 'codes.json'
        codes = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'name': '', 'records': {}}
    overrides = overrides or {}
    if not isinstance(overrides, dict) or len(overrides) > 20000:
        raise ValueError('类型设置无效')
    manual_codes = manual_codes or {}
    if not isinstance(manual_codes, dict) or len(manual_codes) > 20000 or not all(isinstance(v, str) and len(v) <= 128 and not any(ord(c) < 32 for c in v) for v in manual_codes.values()):
        raise ValueError('手动物料编码无效')
    packages = defaultdict(list)
    for r in snapshot['rows']:
        ref = r['reference']
        key = (r['id'].rsplit('/', 1)[0], ref) if re.fullmatch(r'[^?]+[0-9]+', ref) else (r['id'], ref)
        packages[key].append(r)
    groups = {}
    for key, units in packages.items():
        ref = units[0]['reference']
        props = units[0]['props']
        names = dict(cfg['mapping'], 厂家型号='Manufacturer_PN')
        values, issues = {}, []
        for label, native in names.items():
            unique = {u['props'].get(native, '').strip() for u in units}
            values[label] = next(iter(unique)) if len(unique) == 1 else ''
            if len(unique) > 1:
                issues.append('多单元属性不一致：' + label)
        testpoint = normalized(values['封装']) in ('tp', 'testcoupf')
        if not testpoint and not re.fullmatch(r'[^?]+[0-9]+', ref):
            issues.append('位号未标注：' + (ref or '(空)'))
        pn = values['厂家型号']
        matches = codes.get('records', {}).get(normalized(pn), []) if pn else []
        material_code, company_type = '', ''
        if not pn:
            issues.append('缺少 Manufacturer_PN')
        elif len(matches) > 1:
            issues.append('物料编码表型号重复且结果冲突')
        elif matches:
            material_code, company_type = matches[0]
            if not material_code:
                issues.append('编码表中的物料编码为空')
        else:
            issues.append('物料编码未匹配')
        typ, source = classify(ref, props, values['描述'], cfg.get('typeProperty', 'Type'))
        if len({u['props'].get(cfg.get('typeProperty', 'Type'), '') for u in units}) > 1:
            typ, source = '待分类', '多单元类型属性不一致'
            issues.append(source)
        if company_type:
            typ, source = company_type, '物料编码表'
        if testpoint:
            typ, source = '测试点', '封装规则'
            issues = [v for v in issues if v not in ('缺少 Manufacturer_PN', '物料编码未匹配', '编码表中的物料编码为空')]
        values.update(类型=typ, 物料编码=material_code)
        # All output material attributes participate; no accidental merging of variants.
        identity = json.dumps(values, sort_keys=True, ensure_ascii=False)
        import hashlib
        gid = hashlib.sha256(identity.encode()).hexdigest()[:24]
        edit_id = hashlib.sha256(json.dumps({k: values[k] for k in names}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
        if gid not in groups:
            groups[gid] = dict(values, id=gid, editId=edit_id, refs=[], paths=[], issues=[], typeSource=source, codeEditable=not material_code and len(matches) <= 1, testpoint=testpoint)
        g = groups[gid]
        g['refs'].append(ref)
        g['paths'].append(units[0]['path'])
        g['issues'].extend(issues)
    out = sorted(groups.values(), key=lambda g: natural(sorted(g['refs'], key=natural)[0]))
    for i, g in enumerate(out, 1):
        g['序号'] = i
        g['数量'] = len(g['refs'])
        g['位号'] = ', '.join(sorted(g['refs'], key=natural))
        manual = manual_codes.get(g['editId'], '').strip()
        if manual and g['codeEditable']:
            g['物料编码'] = manual
            g['issues'] = [v for v in g['issues'] if v not in ('缺少 Manufacturer_PN', '物料编码未匹配', '编码表中的物料编码为空')]
        type_key = g['editId'] if g['editId'] in overrides else g['id']
        if type_key in overrides:
            choice = overrides[type_key]
            if not isinstance(choice, str) or not 0 < len(choice.strip()) <= 80:
                raise ValueError('类型名称无效')
            g['类型'], g['typeSource'] = choice.strip(), '本次 BOM 手动分类'
        if g['类型'] == '待分类':
            g['issues'].append('类型待分类')
        g['issues'] = sorted(set(g['issues']))
    return {'rows': out, 'packages': len(packages), 'units': len(snapshot['rows']), 'design': snapshot['design'], 'codeTable': codes.get('name', ''), 'headers': HEADERS, 'types': TYPES}


def from_request(body):
    result = status(body.get('snapshot', ''), body.get('session', ''))
    if result.get('state') != 'done' or 'snapshot' not in result:
        raise ValueError('请先读取整个工程的器件')
    projected = preview(result['snapshot'], overrides=body.get('types', {}), manual_codes=body.get('codes', {}))
    return adjustments(projected, body)


def adjustments(result, body):
    """BOM-only additions and exclusions; original Capture snapshot is untouched."""
    excluded, added = body.get('excluded', []), body.get('added', [])
    if not isinstance(excluded, list) or len(excluded) > 20000 or not all(isinstance(x, str) and len(x) <= 100 for x in excluded):
        raise ValueError('排除物料设置无效')
    if not isinstance(added, list) or len(added) > 2000:
        raise ValueError('手动物料数量不能超过 2000 行')
    seen = set()
    for record in added:
        if not isinstance(record, dict) or not re.fullmatch(r'manual-[a-z0-9-]{1,80}', str(record.get('id', ''))) or record['id'] in seen:
            raise ValueError('手动物料标识无效或重复')
        seen.add(record['id'])
        values = {}
        for name in HEADERS[1:]:
            value = record.get(name, '')
            if name == '数量':
                if value != '' and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1_000_000_000):
                    raise ValueError('手动物料数量必须为大于零的数字')
            elif not isinstance(value, str) or len(value) > 32768 or '\x00' in value:
                raise ValueError('手动物料字段无效：' + name)
            values[name] = value.strip() if isinstance(value, str) else value
        issues = []
        if not any(values[n] for n in ('描述', '值', '厂家型号')):
            issues.append('请填写描述、值或厂家型号')
        if not values['类型']:
            issues.append('类型待分类')
        if not values['物料编码'] and values['类型'] != '测试点':
            issues.append('物料编码未匹配')
        result['rows'].append(dict(values, id=record['id'], editId=record['id'], manual=True, refs=[], paths=[], issues=issues, typeSource='手动物料', codeEditable=True, testpoint=values['类型'] == '测试点'))
    sequence = 0
    for r in result['rows']:
        r['included'] = r['editId'] not in excluded
        if r['included']:
            sequence += 1
        r['序号'] = sequence if r['included'] else '—'
    result['exportRows'] = sequence
    result['exportQuantity'] = sum((r['数量'] or 0) for r in result['rows'] if r['included'])
    return result


def cell(ref, value, style='0', numeric=False):
    c = ET.Element(tag('c'), r=ref, s=style, t='n' if numeric else 'inlineStr')
    if numeric:
        ET.SubElement(c, tag('v')).text = str(value)
    else:
        t = ET.SubElement(ET.SubElement(c, tag('is')), tag('t'))
        t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        # XML 1.0 cannot encode these control characters.
        t.text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
    return c


def export_bytes(result, metadata, template=None):
    """Build a standalone .xlsx; template style IDs remain valid and unchanged."""
    root = ET.Element(tag('worksheet'))
    styles = b'<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="' + NS.encode() + b'"><fonts count="1"><font><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="1"><xf fontId="0" fillId="0" borderId="0" numFmtId="0" applyAlignment="1"><alignment wrapText="1" vertical="center"/></xf></cellXfs></styleSheet>'
    theme = None
    style_ids = {}
    if template:
        with workbook(template) as z:
            source = xml(z.read(sheets(z)[0][1]))
            styles = z.read('xl/styles.xml')
            if 'xl/theme/theme1.xml' in z.namelist():
                theme = z.read('xl/theme/theme1.xml')
            for c in source.findall('.//' + tag('c')):
                style_ids[c.get('r')] = c.get('s', '0')
            for name in ('sheetFormatPr', 'cols'):
                child = source.find(tag(name))
                if child is not None:
                    root.append(copy.deepcopy(child))
    if root.find(tag('cols')) is None:
        cols = ET.SubElement(root, tag('cols'))
        for i, width in enumerate([8, 18, 42, 36, 22, 24, 8, 20, 32, 24], 1):
            ET.SubElement(cols, tag('col'), min=str(i), max=str(i), width=str(width), customWidth='1')
    sheet_data = ET.SubElement(root, tag('sheetData'))
    title = ET.SubElement(sheet_data, tag('row'), r='1', ht='48', customHeight='1')
    title.append(cell('A1', metadata['title'], style_ids.get('A1', '0')))
    title.append(cell('I1', '制表人：' + metadata.get('author', '') + '\n日期：' + metadata['date'], style_ids.get('I1', '0')))
    header = ET.SubElement(sheet_data, tag('row'), r='2', ht='30', customHeight='1')
    for i, name in enumerate(HEADERS):
        ref = chr(65 + i) + '2'
        header.append(cell(ref, name, style_ids.get(ref, '0')))
    for ri, record in enumerate(result['rows'], 3):
        # Conservative wrapped-text row estimate; no fixed short row clipping.
        widths = [8, 18, 35, 32, 18, 22, 8, 18, 26, 22]
        lines = max(sum(max(1, (sum(2 if ord(ch) > 255 else 1 for ch in line) + widths[i] - 1) // widths[i]) for line in str(record[name]).split('\n')) for i, name in enumerate(HEADERS))
        row = ET.SubElement(sheet_data, tag('row'), r=str(ri), ht=str(min(409, max(30, lines * 16 + 8))), customHeight='1')
        for ci, name in enumerate(HEADERS):
            col = chr(65 + ci)
            row.append(cell(col + str(ri), record[name], style_ids.get(col + '3', '0'), name in ('序号', '数量') and record[name] != ''))
    merges = ET.SubElement(root, tag('mergeCells'), count='2')
    for ref in ('A1:H1', 'I1:J1'):
        ET.SubElement(merges, tag('mergeCell'), ref=ref)
    ET.SubElement(root, tag('pageMargins'), left='0.3', right='0.3', top='0.5', bottom='0.5', header='0.2', footer='0.2')
    ET.SubElement(root, tag('pageSetup'), orientation='landscape', paperSize='9', fitToWidth='1', fitToHeight='0')
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ('<Override PartName="/xl/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>' if theme else '') + '</Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + REL + '/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<workbook xmlns="' + NS + '" xmlns:r="' + REL + '"><sheets><sheet name="单板物料清单" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + REL + '/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="' + REL + '/styles" Target="styles.xml"/>' + ('<Relationship Id="rId3" Type="' + REL + '/theme" Target="theme/theme1.xml"/>' if theme else '') + '</Relationships>',
        'xl/styles.xml': styles,
        'xl/worksheets/sheet1.xml': ET.tostring(root, encoding='utf-8', xml_declaration=True),
    }
    if theme:
        files['xl/theme/theme1.xml'] = theme
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return output.getvalue()


def export(body):
    result = from_request(body)
    result['rows'] = [r for r in result['rows'] if r.get('included', True)]
    result['packages'] = sum((r['数量'] or 0) for r in result['rows'])
    if not result['rows']:
        raise ValueError('没有可导出的器件')
    meta = body.get('metadata', {})
    if not isinstance(meta, dict) or not all(isinstance(meta.get(k, ''), str) and len(meta.get(k, '')) <= 300 for k in ('title', 'author', 'date')):
        raise ValueError('BOM 抬头字段无效')
    meta = {k: meta.get(k, '') for k in ('title', 'author', 'date')}
    if meta['date']:
        try:
            datetime.date.fromisoformat(meta['date'].replace('.', '-'))
        except ValueError as exc:
            raise ValueError('日期无效') from exc
    folder = Path(body.get('folder', ''))
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError('请选择有效的导出文件夹')
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', (meta['title'] or 'BOM')).strip(' .')[:120]
    if not filename or filename.upper().split('.')[0] in ('CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))):
        raise ValueError('BOM 名称不能作为文件名')
    template = directory() / 'template.xlsx'
    data = export_bytes(result, meta, template.read_bytes() if template.exists() else None)
    # Exclusive create protects existing engineering outputs; no overwrite prompt needed.
    target = folder / (filename + '_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.xlsx')
    with target.open('xb') as f:
        f.write(data)
    return {'path': str(target), 'rows': len(result['rows']), 'packages': result['packages']}

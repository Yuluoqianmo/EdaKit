import base64
import io
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from edakit.services import bom


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))


def row(ref='R1', identity='0/1', **props):
    return {'reference': ref, 'id': identity, 'path': identity, 'props': {'Value': '1K', 'Manufacturer_PN': 'RC-001', 'PCB Footprint': 'R0805', 'Description': 'resistor', 'Manufacturer': 'Yageo', **props}}


def snapshot(*rows):
    return {'design': 'native|E:/demo.dsn', 'rows': list(rows), 'root': 'root'}


def codes(**records):
    return {'name': '物料编码.csv', 'records': records}


def test_physical_multiunit_hierarchy_and_variants():
    rows = [row('U1', '0/1', Description='ADC'), row('U1', '0/2', Description='ADC'), row('U1', '0/3/4', Description='ADC'), row('U2', '0/5', Description='ADC'), row('U3', '0/6', Description='ADC', Value='other')]
    result = bom.preview(snapshot(*rows), codes=codes(**{'rc-001': [['0000123', '功能芯片']]}))
    assert result['units'] == 5
    assert result['packages'] == 4
    assert len(result['rows']) == 2
    assert result['rows'][0]['数量'] == 3
    assert result['rows'][0]['位号'] == 'U1, U1, U2'
    assert result['rows'][0]['物料编码'] == '0000123'


def test_pn_has_no_alias_fallback_and_nc_is_included():
    r = row(Value='NC', Manufacturer_PN='', MPN='RC-001', **{'Part Number': 'RC-001'})
    result = bom.preview(snapshot(r), codes=codes(**{'rc-001': [['123', '电阻']]}))['rows'][0]
    assert result['厂家型号'] == ''
    assert result['数量'] == 1
    assert '缺少 Manufacturer_PN' in result['issues']


def test_native_fields_mapping_and_natural_order():
    cfg = {'mapping': {**bom.FIELDS, '描述': 'Comment'}, 'typeProperty': 'Category'}
    result = bom.preview(snapshot(row('R10', '0/1', Comment='原生描述', Category='自定义类型'), row('R2', '0/2', Comment='other')), cfg=cfg, codes=codes())
    assert result['rows'][0]['位号'] == 'R2'
    assert result['rows'][1]['描述'] == '原生描述'
    assert result['rows'][1]['类型'] == '自定义类型'


def test_unit_conflicts_are_visible_never_arbitrarily_selected():
    result = bom.preview(snapshot(row('U1', '0/1'), row('U1', '0/2', Manufacturer_PN='OTHER')), codes=codes())['rows'][0]
    assert result['厂家型号'] == ''
    assert '多单元属性不一致：厂家型号' in result['issues']


@pytest.mark.parametrize('description,expected', [('MCU', '通用处理器'), ('电源管理IC', '电源管理芯片'), ('监控电路', '功能芯片'), ('未知IC', '待分类')])
def test_u_classification_requires_description(description, expected):
    r = bom.preview(snapshot(row('U1', Description=description)), codes=codes())['rows'][0]
    assert r['类型'] == expected


def test_company_type_precedence_and_manual_unknown():
    snap = snapshot(row('U1', Description='unknown'))
    first = bom.preview(snap, codes=codes())['rows'][0]
    result = bom.preview(snap, codes=codes(), overrides={first['id']: '连接器'})['rows'][0]
    assert result['类型'] == '连接器'
    assert '类型待分类' not in result['issues']
    matched = bom.preview(snap, codes=codes(**{'rc-001': [['123', '公司类型']]}))['rows'][0]
    assert matched['类型'] == '公司类型'


def test_import_csv_columns_and_duplicate_conflicts():
    text = '型号,编码,类型\n RC-001 ,00123,电阻\nrc-001,00123,电阻\nRC-002,00124,电容\nrc-002,00125,电容\n'
    body = {'kind': 'codes', 'name': 'codes.csv', 'data': base64.b64encode(text.encode('utf-8-sig')).decode()}
    assert bom.upload(body)['columns']['0'] == '型号'
    result = bom.upload(dict(body, pnColumn='0', codeColumn='1', typeColumn='2'))
    assert result['models'] == 2
    assert result['conflicts'] == 1
    record = bom.preview(snapshot(row(Manufacturer_PN='RC-002')))['rows'][0]
    assert '冲突' in ' '.join(record['issues'])
    record = bom.preview(snapshot(row(Manufacturer_PN='rc-001')))['rows'][0]
    assert record['物料编码'] == '00123'
    assert not record['issues']


def test_pn_punctuation_and_internal_spaces_are_significant():
    assert bom.normalized(' RC-001 ') == 'rc-001'
    assert bom.normalized('RC001') != bom.normalized('RC-001')
    assert bom.normalized('RC 001') != bom.normalized('RC001')


def test_export_standalone_strings_numeric_counts_and_template_styles():
    result = bom.preview(snapshot(row(Value='=HYPERLINK("x")')), codes=codes(**{'rc-001': [['0001', '电阻']]}))
    meta = {'title': '新 BOM', 'date': '2026-10-22', 'author': '张三'}
    original = bom.export_bytes(result, {'title': 'OLD PRIVATE', 'date': '2020-01-01'})
    data = bom.export_bytes(result, meta, original)
    with bom.workbook(data) as z:
        rows = bom.cells(z, 'xl/worksheets/sheet1.xml')
        assert rows[0]['A'] == '新 BOM'
        assert rows[2]['J'] == '0001'
        assert rows[2]['E'] == '=HYPERLINK("x")'
        assert rows[2]['G'] == '1'
        assert not any('external' in n or 'sharedStrings' in n for n in z.namelist())
        assert not any(b'OLD PRIVATE' in z.read(n) for n in z.namelist())
        sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        assert not sheet.findall('.//' + bom.tag('f'))
        assert sheet.find('.//' + bom.tag('c') + '[@r="E3"]').get('t') == 'inlineStr'


def test_template_upload_validates_headers_and_clears_source_data_on_export():
    result = bom.preview(snapshot(row()), codes=codes())
    data = bom.export_bytes(result, {'title': 'source title', 'date': '2020-01-01'})
    bom.upload({'kind': 'template', 'name': 'template.xlsx', 'data': base64.b64encode(data).decode()})
    assert bom.config()['template']
    assert bom.config()['templateName'] == 'template.xlsx'
    with pytest.raises(ValueError):
        bom.upload({'kind': 'template', 'data': 'bad base64'})


def test_export_gate_session_and_no_overwrite(tmp_path, monkeypatch):
    snap = snapshot(row())
    monkeypatch.setattr(bom, 'status', lambda job, session: {'state': 'done', 'snapshot': snap} if session == 'owner' else (_ for _ in ()).throw(ValueError('owner')))
    body = {'snapshot': 'id', 'session': 'other', 'metadata': {'title': 'BOM', 'author': '', 'date': '2026-10-22'}, 'folder': str(tmp_path)}
    with pytest.raises(ValueError, match='owner'):
        bom.export(body)
    body['session'] = 'owner'
    assert bom.export(body)['packages'] == 1
    (bom.directory() / 'codes.json').write_text(json.dumps(codes(**{'rc-001': [['0001', '电阻']]})), encoding='utf-8')
    a, b = bom.export(body), bom.export(body)
    assert a['path'] != b['path']
    assert a['packages'] == 1
    body['metadata']['date'] = '2026-02-31'
    with pytest.raises(ValueError, match='日期'):
        bom.export(body)


def test_xlsx_code_import_with_second_row_header():
    result = bom.preview(snapshot(row()), codes=codes(**{'rc-001': [['00100', '电阻']]}))
    data = bom.export_bytes(result, {'title': 'BOM', 'date': '2026-10-22'})
    body = {'kind': 'codes', 'name': 'source.xlsx', 'data': base64.b64encode(data).decode(), 'headerRow': 2, 'pnColumn': 'I', 'codeColumn': 'J', 'typeColumn': 'B'}
    assert bom.upload(body)['models'] == 1
    assert bom.preview(snapshot(row()))['rows'][0]['物料编码'] == '00100'


def test_missing_model_and_code_do_not_block_export(tmp_path, monkeypatch):
    snap = snapshot(row())
    monkeypatch.setattr(bom, 'status', lambda *a: {'state': 'done', 'snapshot': snap})
    body = {'allowEmptyCodes': True, 'folder': str(tmp_path), 'metadata': {'title': 'BOM', 'date': '2026-10-22'}}
    assert bom.export(body)['packages'] == 1
    snap['rows'][0]['props']['Manufacturer_PN'] = ''
    assert bom.export(body)['packages'] == 1


def test_manual_type_can_correct_automatic_result():
    snap = snapshot(row())
    first = bom.preview(snap, codes=codes())['rows'][0]
    assert first['类型'] == '电阻'
    assert bom.preview(snap, codes=codes(), overrides={first['id']: '排阻'})['rows'][0]['类型'] == '排阻'


def test_sparse_excel_rows_keep_physical_header_number():
    root = ET.Element(bom.tag('worksheet'))
    sheet = ET.SubElement(root, bom.tag('sheetData'))
    row = ET.SubElement(sheet, bom.tag('row'), r='3')
    row.append(bom.cell('A3', '型号'))
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('sheet.xml', ET.tostring(root))
    with zipfile.ZipFile(io.BytesIO(out.getvalue())) as z:
        assert bom.cells(z, 'sheet.xml') == [{}, {}, {'A': '型号'}]


@pytest.mark.parametrize('footprint', ['TP', ' tp ', 'testcoupf', 'TESTCOUPF'])
def test_testpoints_accept_nonnumeric_reference_and_no_purchasing_fields(footprint):
    r = row('GX', Manufacturer_PN='', Type='other', **{'PCB Footprint': footprint})
    result = bom.preview(snapshot(r), codes=codes())['rows'][0]
    assert result['类型'] == '测试点'
    assert result['issues'] == []
    assert result['数量'] == 1


def test_manual_missing_codes_persist_through_match_changes_but_do_not_replace_matches():
    snap = snapshot(row())
    first = bom.preview(snap, codes=codes())['rows'][0]
    manual = {first['editId']: '0000234'}
    filled = bom.preview(snap, codes=codes(), manual_codes=manual)['rows'][0]
    assert filled['物料编码'] == '0000234'
    assert filled['issues'] == []
    matched = bom.preview(snap, codes=codes(**{'rc-001': [['00999', '排阻']]}), manual_codes=manual)['rows'][0]
    assert matched['editId'] == first['editId']
    assert matched['物料编码'] == '00999'
    assert not matched['codeEditable']
    conflict = bom.preview(snap, codes=codes(**{'rc-001': [['A', ''], ['B', '']]}), manual_codes=manual)['rows'][0]
    assert conflict['物料编码'] == ''
    assert conflict['issues']
    with pytest.raises(ValueError):
        bom.preview(snap, codes=codes(), manual_codes={first['editId']: 'a\nb'})


def test_manual_codes_used_by_export_without_capture_write(tmp_path, monkeypatch):
    snap = snapshot(row())
    monkeypatch.setattr(bom, 'status', lambda *args: {'state': 'done', 'snapshot': snap})
    first = bom.preview(snap, codes=codes())['rows'][0]
    exported = bom.export({'codes': {first['editId']: '00123'}, 'folder': str(tmp_path), 'metadata': {'title': 'BOM', 'date': '2026-10-22'}})
    from pathlib import Path
    with bom.workbook(Path(exported['path']).read_bytes()) as z:
        assert bom.cells(z, 'xl/worksheets/sheet1.xml')[2]['J'] == '00123'
    assert '物料编码' not in snap['rows'][0]['props']


def test_bom_add_exclude_and_export_resequence(tmp_path, monkeypatch):
    snap = snapshot(row(), row('R2', '0/2', Manufacturer_PN='unmatched'))
    monkeypatch.setattr(bom, 'status', lambda *args: {'state': 'done', 'snapshot': snap})
    base = bom.from_request({})
    extra = {'id': 'manual-screws', '类型': '结构件', '描述': 'M3 螺钉', '数量': 4, '物料编码': '000009'}
    body = {'excluded': [r['editId'] for r in base['rows']], 'added': [extra]}
    result = bom.from_request(body)
    assert result['exportRows'] == 1
    assert result['exportQuantity'] == 4
    assert result['rows'][-1]['序号'] == 1
    assert result['rows'][0]['序号'] == '—'
    exported = bom.export(dict(body, folder=str(tmp_path), metadata={'title': 'manual BOM', 'date': '2026-10-22'}))
    from pathlib import Path
    with bom.workbook(Path(exported['path']).read_bytes()) as z:
        cells = bom.cells(z, 'xl/worksheets/sheet1.xml')
    assert len(cells) == 3
    assert cells[2]['C'] == 'M3 螺钉'
    assert cells[2]['G'] == '4'
    assert cells[2]['J'] == '000009'
    assert len(snap['rows']) == 2
    # Restoring incomplete rows is allowed and includes them in the export.
    assert bom.export(dict(body, excluded=[], folder=str(tmp_path), metadata={'title': 'BOM', 'date': '2026-10-22'}))['rows'] == 3


@pytest.mark.parametrize('quantity', [0, -1, True, float('nan'), float('inf'), '2'])
def test_manual_row_quantity_validation(quantity):
    with pytest.raises(ValueError):
        bom.adjustments({'rows': []}, {'added': [{'id': 'manual-bad', '数量': quantity}]})


def test_optional_fields_conflicts_and_blank_manual_quantity_export(tmp_path, monkeypatch):
    snap = snapshot(row('J?', Manufacturer_PN=''))
    monkeypatch.setattr(bom, 'status', lambda *args: {'state': 'done', 'snapshot': snap})
    body = {'folder': str(tmp_path), 'metadata': {}, 'added': [{'id': 'manual-blank', '数量': ''}]}
    exported = bom.export(body)
    from pathlib import Path
    assert Path(exported['path']).name.startswith('BOM_')
    with bom.workbook(Path(exported['path']).read_bytes()) as z:
        rows = bom.cells(z, 'xl/worksheets/sheet1.xml')
    assert len(rows) == 4
    assert rows[0]['A'] == ''
    assert rows[3]['G'] == ''


def test_exclude_everything_rejected_and_manual_row_missing_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(bom, 'status', lambda *args: {'state': 'done', 'snapshot': snapshot()})
    with pytest.raises(ValueError, match='没有'):
        bom.export({'added': [], 'folder': str(tmp_path)})
    extra = {'id': 'manual-blank', '数量': 1}
    result = bom.from_request({'added': [extra]})
    assert len(result['rows'][0]['issues']) == 3
    with pytest.raises(ValueError):
        bom.from_request({'added': [extra, extra]})

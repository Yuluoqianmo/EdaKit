import io
import zipfile

from edakit.ibom.delivery import coordinate_book, placements
from edakit.services import bom, report_template


def test_coordinate_report_nine_columns_and_numeric_positions():
    text = 'A!REFDES!COMP_DEVICE_TYPE!COMP_VALUE!COMP_TOL!COMP_PACKAGE!SYM_X!SYM_Y!SYM_ROTATE!SYM_MIRROR!\nJ!board!date!0!0!10!10!.001!mils!\nS!C6!CAP!1uF!10%!C0603!100!200!270!YES!\n'
    rows = placements(text, detailed=True)
    assert rows == [['C6', 'CAP', '1uF', '10%', 'C0603', 2.54, 5.08, 270, 'B']]
    data = coordinate_book(rows, {'title': 'NEW_BOARD', 'author': '测试', 'date': '2026-11-06'})
    with bom.workbook(data) as z:
        sheets = bom.sheets(z)
        assert len(sheets) == 2
        assert 'NEW_BOARD' in bom.cells(z, sheets[0][1])[0]['A']
        cover = bom.cells(z, sheets[0][1])
        assert cover[26]['A'] == '版  本'
        assert cover[26]['D'] == '编  制' and cover[26]['E'] == '测试'
        assert cover[26]['G'] == '审  核' and cover[26]['J'] == '批  准'
        assert cover[27]['A'] == '日  期' and cover[27]['B'] == '2026-11-06'
        assert cover[28]['A'] == '更改项：'
        cells = bom.cells(z, sheets[1][1])
        assert len(cells) == 3
        assert cells[2]['F'] == '2.54' and cells[2]['I'] == 'B'
        assert cells[2]['E'] == 'C0603'
        root = bom.xml(z.read(sheets[1][1]))
        assert root.find('.//'+bom.tag('c')+'[@r="F3"]').get('t') == 'n'


def test_builtin_reports_have_no_original_project_or_material_values():
    for kind in ('bom', 'coordinates'):
        with zipfile.ZipFile(report_template.path(kind)) as z:
            assert not any('externalLinks' in n for n in z.namelist())
            content = b''.join(z.read(n) for n in z.namelist() if n.endswith('.xml'))
            for value in ('ABM100_MCBTX_MAIN', 'GCJ188R91H104KA01D', '周晋', '崔秦溶'):
                assert value.encode() not in content


def test_cover_and_styles_survive_bom_export_and_values_are_literal():
    record = dict.fromkeys(bom.HEADERS, '')
    record.update({'序号': 1, '数量': 2, '值': '=1+1', '物料编码': '00123'})
    data = bom.export_bytes({'rows': [record]}, {'title': 'NEW', 'author': '张三', 'date': '2026-11-06'})
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.read('xl/styles.xml') == zipfile.ZipFile(report_template.path('bom')).read('xl/styles.xml')
        rows = bom.cells(z, bom.sheets(z)[1][1])
        assert rows[2]['E'] == '=1+1' and rows[2]['J'] == '00123'


def test_legacy_saved_single_sheet_template_is_upgraded_with_cover():
    # Minimal old saved layout; no first-sheet cover exists.
    old = io.BytesIO()
    with zipfile.ZipFile(old, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="'+bom.NS+'" xmlns:r="'+bom.REL+'"><sheets><sheet name="old" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="'+bom.NS+'"><sheetData/></worksheet>')
    record = dict.fromkeys(bom.HEADERS, '')
    record.update({'序号': 1, '数量': 3, '物料编码': '00123'})
    data = bom.export_bytes({'rows': [record]}, {'title': '迁移测试', 'author': '编制人', 'date': '2026-11-06'}, old.getvalue())
    with bom.workbook(data) as z:
        sheets = bom.sheets(z)
        assert len(sheets) == 2
        cover = bom.cells(z, sheets[0][1])
        assert '迁移测试' in cover[0]['A']
        assert cover[26]['E'] == '编制人'
        assert bom.cells(z, sheets[1][1])[2]['J'] == '00123'


def test_cover_rich_text_layout_and_report_metadata():
    values = {'title': 'PROJECT_单板物料清单', 'version': 'A/1', 'documentNumber': 'DOC-001',
              'author': '编制人', 'reviewer': '审核人', 'approver': '批准人',
              'date': '2026-11-06', 'changes': '修订说明', 'documentStatus': '临时'}
    data = report_template.fill(report_template.path('bom').read_bytes(), [], values)
    with bom.workbook(data) as z:
        root = bom.xml(z.read(bom.sheets(z)[0][1]))
        cover = bom.cells(z, bom.sheets(z)[0][1])
        assert cover[26]['B'] == 'A/1' and cover[26]['H'] == '审核人'
        assert cover[26]['K'] == '批准人' and cover[28]['A'] == '更改项：修订说明'
        runs = root.find('.//'+bom.tag('c')+'[@r="A1"]').findall(bom.tag('is')+'/'+bom.tag('r'))
        title = [r for r in runs if r.find(bom.tag('rPr')+'/'+bom.tag('sz')) is not None and r.find(bom.tag('rPr')+'/'+bom.tag('sz')).get('val') == '48']
        assert len(title) == 1 and title[0].find(bom.tag('t')).text == 'PROJECT\n'
        assert 'DOC-001' in cover[0]['A']
        checks = [r.find(bom.tag('t')).text for r in runs if r.find(bom.tag('rPr')+'/'+bom.tag('rFont')) is not None and r.find(bom.tag('rPr')+'/'+bom.tag('rFont')).get('val') == 'Wingdings 2']
        assert checks == ['R', '£']


def test_coordinate_date_defaults_to_local_today():
    import datetime
    with bom.workbook(coordinate_book([['C1', 1, 2, 90, 'T']])) as z:
        cover = bom.cells(z, bom.sheets(z)[0][1])
        assert cover[27]['B'] == datetime.date.today().isoformat()

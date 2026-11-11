import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from edakit.ibom import delivery as d


def template():
    buffer = io.BytesIO()
    ns = d.xlsx.NS
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="{d.xlsx.REL}"><sheets><sheet name="PCB说明" r:id="a"/><sheet name="钢网" r:id="b"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="a" Target="worksheets/sheet1.xml"/><Relationship Id="b" Target="worksheets/sheet2.xml"/></Relationships>')
        for i in (1, 2):
            z.writestr(f'xl/worksheets/sheet{i}.xml', f'''<worksheet xmlns="{ns}"><sheetData><row r="1"><c r="B1" t="inlineStr"><is><t>型号</t></is></c><c r="C1" s="4" t="inlineStr"><is><t>old</t></is></c><c r="I1" t="inlineStr"><is><t>option</t></is></c></row></sheetData><dataValidations count="1"><dataValidation type="list" sqref="C1"><formula1>$I$1:$I$1</formula1></dataValidation></dataValidations><pageSetup orientation="landscape"/></worksheet>''')
        z.writestr('unchanged.bin', b'preserved')
    return buffer.getvalue()


def extracted(mirror='YES', unit='mils'):
    return f'A!REFDES!SYM_X!SYM_Y!SYM_ROTATE!SYM_MIRROR!\nJ!board!date!0!0!10!10!.001!{unit}!\nS!C6!100!200!90!{mirror}!\n'


def test_template_preserves_options_printing_style_and_other_parts():
    data = template()
    fields = d.template_fields(data)
    assert len(fields) == 2 and fields[0]['choices'] == ['option']
    for field in fields:
        field['value'] = 'new <board> & values'
    result = d.fill_template(data, fields)
    assert all(f['value'] == 'new <board> & values' for f in d.template_fields(result))
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        assert z.read('unchanged.bin') == b'preserved'
        root = d.xlsx.xml(z.read('xl/worksheets/sheet1.xml'))
        assert root.find(d.xlsx.tag('pageSetup')).get('orientation') == 'landscape'
        assert next(c for c in root.iter(d.xlsx.tag('c')) if c.get('r') == 'C1').get('s') == '4'


def test_simplified_production_fields_and_export_keep_workbook_layout():
    data = d.builtin_template().read_bytes()
    fields = d.template_fields(data)
    assert len(fields) == 25
    assert not d.manufacturing.REMOVED.intersection(f['label'] for f in fields)
    assert any(f['label'] == '板框层' for f in fields)
    assert not any(f['label'] == '切边层' for f in fields)
    steel = {f['label']: f for f in fields if f['sheet'] == '钢网'}
    assert '58.4×58.4 cm' in steel['钢网尺寸']['choices']
    assert steel['制作要求']['choices'] and steel['数量']['choices']
    result = d.fill_template(data, fields)
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(io.BytesIO(result)) as generated:
        assert original.read('xl/styles.xml') == generated.read('xl/styles.xml')
        rows = d.xlsx.xml(generated.read('xl/worksheets/sheet1.xml')).findall('.//'+d.xlsx.tag('row'))
        assert not {'19', '20'}.intersection(r.get('r') for r in rows)
        labels = [''.join(c.itertext()) for r in rows for c in r if c.get('r') == 'B'+r.get('r')]
        assert not d.manufacturing.DELETED.intersection(labels)
        assert len([r for r in rows if r.get('hidden') == '1']) == 3
        for row in rows:
            if row.get('hidden') == '1':
                cell = next(c for c in row if c.get('r') == 'C'+row.get('r'))
                assert not list(cell)
    assert next(f for f in d.template_fields(result) if f['label'] == '板框层')


def test_coordinates_keep_bottom_angle_and_do_not_mirror_xy():
    rows = d.placements(extracted())
    assert rows == [['C6', 2.54, 5.08, 90.0, 'B']]
    assert d.placements(extracted('NO', 'millimeters')) == [['C6', 100.0, 200.0, 90.0, 'T']]
    with zipfile.ZipFile(io.BytesIO(d.coordinate_book(rows))) as z:
        sheet = d.xlsx.xml(z.read('xl/worksheets/sheet2.xml'))
        cells = {c.get('r'): c for c in sheet.iter(d.xlsx.tag('c'))}
        assert cells['F3'].find(d.xlsx.tag('v')).text == '2.54'
        assert ''.join(cells['I3'].itertext()) == 'B'


def test_template_keeps_namespace_prefixes_referenced_by_compatibility_attributes():
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template())) as source, zipfile.ZipFile(output, 'w') as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename.endswith('sheet1.xml'):
                data = data.replace(b'<worksheet ', b'<worksheet xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" mc:Ignorable="x14ac" ')
            target.writestr(item, data)
    data = output.getvalue()
    fields = d.template_fields(data)
    fields[0]['value'] = '  text & <values>  '
    result = d.fill_template(data, fields)
    with zipfile.ZipFile(io.BytesIO(result)) as z:
        content = z.read('xl/worksheets/sheet1.xml')
        assert b'xmlns:x14ac=' in content and b'mc:Ignorable="x14ac"' in content
    assert d.template_fields(result)[0]['value'] == '  text & <values>  '


def test_values_are_saved_per_board_and_template_without_reusing_old_project_defaults(tmp_path):
    data = template(); fields = d.template_fields(data)
    source = tmp_path/'new.brd'; other = tmp_path/'other.brd'
    initial = d.initial_values(fields, source, data, {})
    assert all(f['value'] == 'new' for f in initial)
    for field in initial:
        field['value'] = 'confirmed'
    saved = {}
    d.remember_values(saved, source, data, initial)
    assert all(f['value'] == 'confirmed' for f in d.initial_values(fields, source, data, saved))
    assert all(f['value'] == 'other' for f in d.initial_values(fields, other, data, saved))
    assert all(f['value'] == 'new' for f in d.initial_values(fields, source, data+b'changed', saved))


@pytest.mark.parametrize('text', [extracted('UNKNOWN'), extracted(unit='unknown'), extracted().replace('100!', 'nan!'), extracted() + 'S!C6!1!2!0!NO!\n'])
def test_bad_coordinates_block_export(text):
    with pytest.raises(ValueError):
        d.placements(text)


@pytest.fixture
def job(tmp_path, monkeypatch):
    board = tmp_path/'design.brd'
    board.write_bytes(b'original board')
    params = tmp_path/'params'; params.mkdir()
    for name in ('art_param.txt', 'nc_param.txt'):
        (params/name).write_text('settings')
    tpl = tmp_path/'template.xlsx'; tpl.write_bytes(template())
    monkeypatch.setattr(d, 'app_dir', lambda: tmp_path/'private')
    def generate(*args, **kw):
        html = tmp_path/'ibom.html'; html.write_text('offline ibom')
        return {'html': str(html)}
    monkeypatch.setattr(d.exporter, 'generate', generate)
    def runner(cmd, cwd, stdout, **kwargs):
        exe = Path(cmd[0]).name
        if exe == 'artwork.exe' and '-l' in cmd:
            stdout.write(b'TOP\nBOTTOM\n')
        elif exe == 'artwork.exe':
            (cwd/'photoplot.log').write_text('completed')
            for name in ('TOP.art', 'BOTTOM.art'):
                (cwd/name).write_text('gerber data')
        elif exe == 'nctape.exe':
            nc = (cwd/'nc_param.txt').read_text()
            assert 'old-computer' not in nc
            assert (cwd/'board.drl').as_posix() in nc
            (cwd/'ncdrill.log').write_text('completed')
            (cwd/'board-1-2.drl').write_text('drill data')
        elif exe == 'ncroute.exe':
            (cwd/'ncroute.log').write_text('WARNING: no routing required')
        elif exe == 'extracta.exe':
            (cwd/'components.txt').write_text(extracted())
        return SimpleNamespace(returncode=0)
    return dict(board=board, source=board, cadence_root=tmp_path/'cadence', parameters=params, template=tpl, fields=d.template_fields(tpl.read_bytes()), runner=runner)


def test_drill_path_rewrites_indented_case_insensitive_parameters_only_in_private_copy(job):
    parameter = job['parameters']/'nc_param.txt'
    original = b'  tape-file C:/old-computer/old.drl\r\n\troute-file C:/old-computer/old.rou\r\nOUTPUT-UNITS ENGLISH\r\n'
    parameter.write_bytes(original)
    d.run(**job)
    assert parameter.read_bytes() == original


def test_film_selection_is_passed_to_artwork_and_validated_against_board(job, tmp_path):
    original = job['runner']
    calls = []
    def runner(cmd, cwd, **kwargs):
        calls.append(cmd)
        if Path(cmd[0]).name == 'artwork.exe' and '-l' not in cmd:
            (cwd/'photoplot.log').write_text('completed')
            assert cmd[1:] == ['-f', 'BOTTOM', 'board.brd']
            (cwd/'BOTTOM.art').write_text('selected film')
            return SimpleNamespace(returncode=0)
        return original(cmd, cwd=cwd, **kwargs)
    result = d.run(**dict(job, runner=runner), outputs=['gerber'], film_names=['BOTTOM'], output=tmp_path/'subset')
    assert result['files'] == 2
    assert (tmp_path/'subset/design_art/BOTTOM.art').is_file()
    assert not (tmp_path/'subset/design_art/TOP.art').exists()
    for invalid in ([], ['MISSING'], ['TOP', 'TOP']):
        with pytest.raises(ValueError, match='Film'):
            d.run(**dict(job, runner=runner), outputs=['gerber'], film_names=invalid, output=tmp_path/'invalid')


def test_gerber_uses_written_snapshot_while_coordinates_keep_original(job, tmp_path):
    fresh = tmp_path/'fresh.brd'; fresh.write_bytes(b'newly-written-films')
    original = job['runner']
    checked = []
    def runner(cmd, cwd, **kwargs):
        exe = Path(cmd[0]).name
        if exe in ('artwork.exe', 'nctape.exe', 'ncroute.exe'):
            assert cmd[-1] == 'gerber.brd'
            assert (cwd/'gerber.brd').read_bytes() == b'newly-written-films'
            checked.append(exe)
        elif exe == 'extracta.exe':
            assert cmd[1] == 'board.brd'
            assert (cwd/'board.brd').read_bytes() == b'original board'
            checked.append(exe)
        return original(cmd, cwd=cwd, **kwargs)
    result = d.run(**dict(job, runner=runner), outputs=['gerber', 'coordinates'], gerber_board=fresh, output=tmp_path/'export')
    assert result['files'] == 4
    assert checked == ['artwork.exe', 'artwork.exe', 'nctape.exe', 'ncroute.exe', 'extracta.exe']
    assert job['board'].read_bytes() == b'original board'
    with pytest.raises(ValueError, match='快照缺失'):
        d.run(**job, outputs=['gerber'], gerber_board=tmp_path/'absent.brd', output=tmp_path/'bad')


def test_ibom_source_is_explicit_and_only_ibom_needs_no_manufacturing_inputs(job, tmp_path, monkeypatch):
    calls = []
    final = tmp_path/'final.csv'; final.write_text('refdes,value\nR1,1k')
    def generate(*args, **kwargs):
        calls.append(kwargs)
        html = tmp_path/'result.html'; html.write_text('ibom')
        return dict(html=str(html))
    monkeypatch.setattr(d.exporter, 'generate', generate)
    params = dict(job, parameters=None, template=None, fields=None)
    d.run(**params, outputs=['ibom'], ibom_use_board=False, ibom_bom=final, output=tmp_path/'final-output')
    assert calls[-1]['bom'] == final and calls[-1]['use_board'] is False
    d.run(**params, outputs=['ibom'], output=tmp_path/'pcb-output')
    assert calls[-1]['use_board'] is True and calls[-1]['bom'] is None
    with pytest.raises(ValueError, match='BOM'):
        d.run(**params, outputs=['ibom'], ibom_use_board=False, output=tmp_path/'bad')


def test_complete_export_reuses_directory_and_preserves_other_files(job):
    dest = job['source'].parent/'Output Files'; dest.mkdir()
    (dest/'keep.txt').write_text('keep')
    result = d.run(**job)
    assert result['folder'] == str(dest) and result['components'] == 1
    assert result['files'] == 6 and result['warnings']
    assert 'no routing required' in Path(result['log']).read_text()
    assert (dest/'design_art/design-1-2.drl').is_file()
    assert (dest/'keep.txt').read_text() == 'keep'

    assert job['board'].read_bytes() == b'original board'
    (dest/'design-iBOM.html').write_text('previous')
    with pytest.raises(ValueError, match='同名'):
        d.run(**job)
    assert (dest/'design-iBOM.html').read_text() == 'previous'
    d.run(**job, overwrite=True)
    assert (dest/'design-iBOM.html').read_text() == 'offline ibom'
    assert (dest/'keep.txt').read_text() == 'keep'


def test_gerber_folder_uses_original_board_name_without_zip(job):
    job['source'] = job['source'].with_name('BZ_Convert_PWR.brd')
    result = d.run(**job, outputs=['gerber'])
    destination = Path(result['folder'])
    assert (destination/'BZ_Convert_PWR_art/TOP.art').is_file()
    assert (destination/'BZ_Convert_PWR_art/BZ_Convert_PWR-1-2.drl').is_file()
    assert not (destination/'Gerber').exists()
    assert not list(destination.glob('*.zip'))


def test_manufacturing_error_does_not_publish_partial_outputs(job):
    original = job['runner']
    def runner(cmd, **kwargs):
        result = original(cmd, **kwargs)
        if Path(cmd[0]).name == 'artwork.exe' and '-l' not in cmd:
            (kwargs['cwd']/'photoplot.log').write_text('ERROR: Dynamic Shapes are out of date')
        return result
    job['runner'] = runner
    with pytest.raises(ValueError, match='Gerber 日志存在错误'):
        d.run(**job)
    assert not d.output_directory(job['source']).exists()


def test_publication_failure_rolls_back_existing_files(job, monkeypatch):
    dest = d.output_directory(job['source']); dest.mkdir()
    (dest/'design-iBOM.html').write_text('old')
    copy = d.shutil.copy2
    def fail(src, target, *args, **kwargs):
        if Path(target) == dest/'design_art/TOP.art':
            raise OSError('disk full')
        return copy(src, target, *args, **kwargs)
    monkeypatch.setattr(d.shutil, 'copy2', fail)
    with pytest.raises(OSError, match='disk full'):
        d.run(**job, overwrite=True)
    assert (dest/'design-iBOM.html').read_text() == 'old'
    assert not (dest/'design-坐标文件.xlsx').exists()


def test_custom_output_uses_builtin_template_and_automatically_finds_project_parameters(job):
    original = job['parameters']
    default = d.output_directory(job['source'])
    params = default/'design_art'; params.mkdir(parents=True)
    for p in original.iterdir():
        d.shutil.copy2(p, params/p.name)
    job.pop('parameters'); job.pop('template'); job.pop('fields')
    destination = job['source'].parent/'custom destination'
    result = d.run(**job, output=destination)
    assert result['folder'] == str(destination)
    assert (destination/'design_art/design-1-2.drl').is_file()
    assert (destination/'design-iBOM.html').is_file()
    assert (destination/'design-坐标文件.xlsx').is_file()
    fields = d.template_fields((destination/'design-加工说明.xlsx').read_bytes())
    assert {f['sheet'] for f in fields} == {'PCB说明', '钢网'}
    assert len(fields) >= 20 and any(f['choices'] for f in fields)
    assert not (default/'design-加工说明.xlsx').exists()


def test_manufacturing_discovery_prefers_board_named_folder_and_blocks_ambiguity(tmp_path):
    board = tmp_path/'design.brd'
    output = tmp_path/'Output files'; output.mkdir()
    for name in ('other_art', 'another_art'):
        folder = output/name; folder.mkdir()
        for filename in ('art_param.txt', 'nc_param.txt'):
            (folder/filename).write_text('settings')
    with pytest.raises(ValueError, match='多套制造参数'):
        d.manufacturing_parameters(board, output)
    matching = output/'design_art'; matching.mkdir()
    for filename in ('art_param.txt', 'nc_param.txt'):
        (matching/filename).write_text('settings')
    assert d.manufacturing_parameters(board, tmp_path/'new output') == matching


def test_output_path_rejects_relative_paths_before_export(job):
    with pytest.raises(ValueError, match='完整的输出目录'):
        d.run(**job, output='relative')


def test_backend_blocks_incompatible_order_before_writing_outputs(job):
    job['fields'] += [dict(sheet='PCB说明', label='PCB层数', value='6'), dict(sheet='PCB说明', label='表面处理', value='有铅喷锡')]
    with pytest.raises(ValueError, match='不能选择喷锡'):
        d.run(**job)
    assert not d.output_directory(job['source']).exists()


@pytest.mark.parametrize('mask', range(1, 16))
def test_selected_outputs_only_run_requested_steps(job, monkeypatch, mask):
    selected = [key for i, key in enumerate(d.OUTPUTS) if mask & (1 << i)]
    commands, ibom_calls = [], []
    original = job['runner']
    def runner(cmd, **kw):
        commands.append(Path(cmd[0]).name)
        return original(cmd, **kw)
    job['runner'] = runner
    original_ibom = d.exporter.generate
    def ibom(*args, **kw):
        ibom_calls.append(True)
        return original_ibom(*args, **kw)
    monkeypatch.setattr(d.exporter, 'generate', ibom)
    if 'gerber' not in selected:
        job['parameters'] = job['source'].parent/'missing parameters'
        monkeypatch.setattr(d, 'manufacturing_parameters', lambda *a: pytest.fail('Unrequested manufacturing discovery'))
    if 'instructions' not in selected:
        job['template'] = job['source'].parent/'missing.xlsx'
        job['fields'] += [dict(sheet='PCB说明', label='PCB层数', value='6'), dict(sheet='PCB说明', label='表面处理', value='有铅喷锡')]
    result = d.run(**job, outputs=selected)
    destination = Path(result['folder'])
    assert (destination/'design_art').exists() == ('gerber' in selected)
    for key, suffix in [('coordinates', '-坐标文件.xlsx'), ('instructions', '-加工说明.xlsx'), ('ibom', '-iBOM.html')]:
        assert (destination/('design'+suffix)).exists() == (key in selected)
    assert ('artwork.exe' in commands) == ('gerber' in selected)
    assert ('extracta.exe' in commands) == ('coordinates' in selected)
    assert bool(ibom_calls) == ('ibom' in selected)
    assert result['files'] == (3 if 'gerber' in selected else 0)+len(set(selected)-{'gerber'})


@pytest.mark.parametrize('selected', [[], ['invalid']])
def test_empty_or_invalid_output_selection_writes_nothing(job, selected):
    with pytest.raises(ValueError, match='输出内容'):
        d.run(**job, outputs=selected)
    assert not d.output_directory(job['source']).exists()


def test_unselected_existing_files_are_not_overwritten(job):
    destination = d.output_directory(job['source']); destination.mkdir()
    original = destination/'design-iBOM.html'; original.write_text('keep existing')
    d.run(**job, outputs=['instructions'], overwrite=True)
    assert original.read_text() == 'keep existing'
    assert len(list(destination.iterdir())) == 2


@pytest.mark.skipif(d.os.name != 'nt' and not d.os.environ.get('DISPLAY'), reason='Tk requires a display')
def test_window_loads_builtin_form_and_exports_to_selected_directory(tmp_path, monkeypatch):
    import json
    import tkinter as tk
    from tkinter import ttk, filedialog
    from edakit.ibom import delivery_window as window
    monkeypatch.setattr(window, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(window.threading, 'Thread', lambda target, daemon: SimpleNamespace(start=target))
    selected = tmp_path/'selected output'
    monkeypatch.setattr(filedialog, 'askdirectory', lambda **kw: str(selected))
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs)
        return dict(files=16, components=126, warnings=False)
    monkeypatch.setattr(d, 'run', generate)
    monkeypatch.setattr(window.board_metadata, 'read', lambda *a: dict(values={'PCB层数': '4'}, sources={'PCB层数': 'PCB 导电叠层'}, warnings=[]))
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    def mainloop(root):
        try:
            root.update()
            widgets = list(descendants(root))
            view = root.delivery_view
            assert set(view.pages) == {'PCB 参数', 'Gerber / 光绘', '钢网参数', '交互式 iBOM', '输出文件'}
            assert len(view.entries) == len(view.fields) == 25
            buttons = [w for w in widgets if isinstance(w, ttk.Button)]
            choose = [w for w in buttons if w.cget('text') == '浏览…']
            assert len(choose) == 1
            output_entry = next(w for w in widgets if isinstance(w, ttk.Entry) and w.get() == str(tmp_path/'Output files'))
            assert not output_entry.instate(['disabled', 'readonly'])
            choose[0].invoke()
            assert output_entry.get() == str(selected)
            thickness_entry = next(w for f, v, w in view.entries if f['label'] == '厚度')
            thickness_entry.variables['成品板厚'].set('1.6 mm')
            mask_editor = next(w for f, v, w in view.entries if f['label'] == '阻焊要求')
            mask_editor.variables['过孔'].set('按Gerber文件')
            view.selected_outputs['gerber'].set(False)
            view.selected_outputs['ibom'].set(False)
            next(w for w in buttons if str(w.cget('text')).startswith('生成所选')).invoke()
        finally:
            root.destroy()
    monkeypatch.setattr(tk.Tk, 'mainloop', mainloop)
    window.show(SimpleNamespace(board=str(tmp_path/'snapshot.brd'), source=str(tmp_path/'design.brd'), cadence_root='D:/Cadence/SPB_17.2'))
    assert len(calls) == 1 and calls[0]['output'] == selected
    assert calls[0]['outputs'] == ['coordinates', 'instructions']
    assert len(calls[0]['fields']) >= 20
    assert next(f['value'] for f in calls[0]['fields'] if f['label'] == 'PCB层数') == '4'
    assert 'template' not in calls[0] and 'parameters' not in calls[0]
    saved = json.loads((tmp_path/'private/delivery/settings.json').read_text(encoding='utf-8'))
    assert saved['boards'][d.exporter.board_key(tmp_path/'design.brd')]['outputFolder'] == str(selected)
    monkeypatch.setattr(window.board_metadata, 'read', lambda *a: dict(values={'PCB层数': '6', '厚度': '0.26416 mm'}, sources={'PCB层数': 'PCB 导电叠层', '厚度': 'PCB 叠层值'}, warnings=[]))
    def reopen(root):
        try:
            root.update()
            next(w for w in descendants(root) if isinstance(w, ttk.Button) and str(w.cget('text')).startswith('生成所选')).invoke()
        finally:
            root.destroy()
    monkeypatch.setattr(tk.Tk, 'mainloop', reopen)
    window.show(SimpleNamespace(board=str(tmp_path/'snapshot.brd'), source=str(tmp_path/'design.brd'), cadence_root='D:/Cadence/SPB_17.2'))
    assert next(f['value'] for f in calls[1]['fields'] if f['label'] == 'PCB层数') == '6'
    assert next(f['value'] for f in calls[1]['fields'] if f['label'] == '厚度') == '1.6 mm'
    assert calls[1]['outputs'] == ['coordinates', 'instructions']


@pytest.mark.skipif(d.os.name != 'nt' and not d.os.environ.get('DISPLAY'), reason='Tk requires a display')
def test_manufacturing_migration_layer_conflicts_and_compound_values(tmp_path, monkeypatch):
    import json
    import tkinter as tk
    from tkinter import ttk, messagebox
    from edakit.ibom import delivery_window as window
    from edakit.ibom.manufacturing_form import Editor
    source = tmp_path/'design.brd'
    data = d.builtin_template().read_bytes()
    fields = d.initial_values(d.template_fields(data), source, data, {})
    for f in fields:
        f['value'] = {'厚度': '0.26416 mm', '铜箔厚度': 'TOP: 30.48 μm', '阻焊要求': '原有手工油墨要求'}.get(f['label'], f['value'])
    saved = {}
    d.remember_values(saved, source, data, fields)
    saved['boards'][d.exporter.board_key(source)]['autoValues'] = {f['sheet']+'!'+f['ref']: f['value'] for f in fields if f['label'] in ('厚度', '铜箔厚度')}
    private = tmp_path/'private'; (private/'delivery').mkdir(parents=True)
    (private/'delivery/settings.json').write_text(json.dumps(saved), encoding='utf8')
    monkeypatch.setattr(window, 'app_dir', lambda: private)
    monkeypatch.setattr(window.threading, 'Thread', lambda target, daemon: SimpleNamespace(start=target))
    monkeypatch.setattr(window.board_metadata, 'read', lambda *a: dict(values={'PCB层数': '2', '厚度': '0.26416 mm', '板材': 'FR-4'}, sources={'PCB层数': 'PCB叠层'}, warnings=[]))
    calls, errors = [], []
    monkeypatch.setattr(d, 'run', lambda *a, **kw: (calls.append(kw) or dict(files=16, components=126, warnings=False)))
    monkeypatch.setattr(messagebox, 'showerror', lambda *a, **kw: errors.append(a))
    def descendants(w):
        for child in w.winfo_children():
            yield child
            yield from descendants(child)
    def mainloop(root):
        try:
            root.update()
            widgets = list(descendants(root))
            editors = {w.field['label']: w for w in widgets if isinstance(w, Editor)}
            assert editors['厚度'].variable.get() == '1.6 mm'
            assert editors['铜箔厚度'].variable.get() == '外层：1 oz'
            assert editors['板材'].variable.get() == '类别：FR-4'
            assert editors['阻焊要求'].snapshot()['补充要求'] == '原有手工油墨要求'
            assert any('0.26416 mm' in str(w.cget('text')) for w in widgets if isinstance(w, ttk.Label))
            for key, variable in root.delivery_view.selected_outputs.items():
                variable.set(key == 'instructions')
            editors['厚度'].variables['成品板厚'].set('1.6 mm')
            editors['铜箔厚度'].variables['外层'].set('1 oz')
            editors['表面处理'].variables['工艺'].set('有铅喷锡')
            layer_entry = next(w for f, v, w in root.delivery_view.entries if f['label'] == 'PCB层数')
            layer_entry.delete(0, 'end'); layer_entry.insert(0, '6')
            assert editors['表面处理'].variable.get() == '有铅喷锡'
            assert '有铅喷锡' not in dict(editors['表面处理'].definitions)['工艺']
            assert any(isinstance(w, ttk.Radiobutton) for w in editors['表面处理'].widgets['工艺'][0].winfo_children())
            widgets = list(descendants(root))
            button = next(w for w in widgets if isinstance(w, ttk.Button) and str(w.cget('text')).startswith('生成所选'))
            button.invoke()
            assert errors and not calls
            editors['表面处理'].variables['工艺'].set('沉金')
            editors['铜箔厚度'].variables['内层'].set('0.5 oz')
            button.invoke(); root.update()
            assert len(calls) == 1
            assert all(not w.instate(['disabled']) for w in editors['厚度'].widgets['成品板厚'][0].winfo_children())
        finally:
            root.destroy()
    monkeypatch.setattr(tk.Tk, 'mainloop', mainloop)
    window.show(SimpleNamespace(board=str(tmp_path/'snapshot.brd'), source=str(source), cadence_root='D:/Cadence/SPB_17.2'))
    copper = next(f for f in calls[0]['fields'] if f['label'] == '铜箔厚度')
    assert copper['value'] == '外层：1 oz；内层：0.5 oz'
    exported = d.template_fields(d.fill_template(data, calls[0]['fields']))
    assert next(f['value'] for f in exported if f['label'] == '铜箔厚度') == copper['value']
    saved = json.loads((private/'delivery/settings.json').read_text(encoding='utf8'))
    record = saved['boards'][d.exporter.board_key(source)]
    assert record['specValues'][copper['sheet']+'!'+copper['ref']]['parts'] == copper['spec']
    assert all('0.26416' not in v for v in record['values'].values())

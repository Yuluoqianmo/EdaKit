from types import SimpleNamespace

from edakit.ibom import delivery as d, manufacturing as m


def test_screenshot_defaults_do_not_reuse_template_board_data(tmp_path):
    data = d.builtin_template().read_bytes()
    fields = d.initial_values(d.template_fields(data), tmp_path/'new.brd', data, {})
    values = {(f['sheet'], f['label']): f['value'] for f in fields}
    for label in m.DEFAULT_PARTS:
        assert values['PCB说明', label] == m.default_value('PCB说明', label)
    for label, value in m.STENCIL_DEFAULTS.items():
        assert values['钢网', label] == value
    for key in (('PCB说明', 'PCB尺寸'), ('钢网', '钢网尺寸'), ('钢网', '制作要求')):
        assert values[key] == ''
    assert ('PCB说明', '设计人员电话') not in values
    assert ('PCB说明', '其他') not in values
    assert values['PCB说明', '型号'] == values['钢网', '型号'] == 'new'
    assert next(f['spec'] for f in fields if f['label'] == '板材') == {'类别': 'FR-4'}


def test_saved_choices_win_and_explicit_clear_survives_reopen(tmp_path):
    data = d.builtin_template().read_bytes()
    source = tmp_path/'new.brd'
    fields = d.initial_values(d.template_fields(data), source, data, {})
    for f in fields:
        if f['label'] == '厚度':
            f['value'] = '2.0 mm'
        elif f['label'] == '表面处理':
            f['value'] = ''
    saved = {}
    d.remember_values(saved, source, data, fields)
    reopened = d.initial_values(d.template_fields(data), source, data, saved)
    assert next(f['value'] for f in reopened if f['label'] == '厚度') == '2.0 mm'
    assert next(f['value'] for f in reopened if f['label'] == '表面处理') == ''
    # Existing pre-default releases saved empty fields without clear markers.
    record = saved['boards'][d.exporter.board_key(source)]
    record.pop('clearedDefaults')
    assert next(f['value'] for f in d.initial_values(d.template_fields(data), source, data, saved) if f['label'] == '表面处理') == '沉金'


def test_material_old_model_migrates_losslessly_to_editable_requirement():
    old = {'类别': 'FR-4', '品牌/型号/TG': 'KB-6165F TG155'}
    restored = m.restore('板材', m.compose('板材', old), old)
    assert restored == {'类别': 'FR-4', 'TG要求': 'KB-6165F TG155'}


def test_window_defaults_manual_tg_and_export_roundtrip(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    from edakit.ibom import delivery_window as w
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    root = tk.Tk()
    view = w.DeliveryWindow(root, SimpleNamespace(source=str(tmp_path/'new.brd'), board=str(tmp_path/'copy.brd')))
    try:
        root.update()
        material = next(widget for field, _, widget in view.entries if field['label'] == '板材')
        tg = material.widgets['TG要求'][0]
        assert isinstance(tg, ttk.Entry) and not isinstance(tg, ttk.Combobox)
        assert material.variables['类别'].get() == 'FR-4' and tg.get() == ''
        tg.insert(0, 'TG≥155℃')
        view.apply_metadata({'values': {'PCB层数': '2', '厚度': '0.26416 mm', '板材': 'FR-4'}, 'warnings': []})
        assert material.variables['TG要求'].get() == 'TG≥155℃'
        assert view.value('PCB说明', '厚度') == '1.6 mm'
        material.configure(state='disabled')
        assert tg.instate(['disabled'])
        material.configure(state='normal')
        assert not tg.instate(['readonly'])
        fields = [dict(f, value=v.get()) for f, v, _ in view.entries]
        exported = d.template_fields(d.fill_template(view.loaded_data, fields))
        assert next(f['value'] for f in exported if f['label'] == '板材') == '类别：FR-4；TG要求：TG≥155℃'
        assert view.value('钢网', 'MARK点') == '不需要'
        assert view.value('钢网', '数量') == '1'
    finally:
        view.stop_polling()
        root.destroy()


def test_legacy_material_can_be_saved_without_editing_and_reopened():
    import tkinter as tk
    from edakit.ibom.manufacturing_form import Editor
    root = tk.Tk()
    old = {'类别': 'FR-4', '品牌/型号/TG': 'KB-6165F TG155'}
    variable = tk.StringVar(root, value=m.compose('板材', old))
    try:
        editor = Editor(root, {'label': '板材'}, variable, 2, old)
        parts = editor.snapshot()
        assert variable.get() == m.compose('板材', parts)
        assert m.restore('板材', variable.get(), parts) == {'类别': 'FR-4', 'TG要求': 'KB-6165F TG155'}
    finally:
        root.destroy()

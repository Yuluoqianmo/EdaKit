import json
import tkinter as tk
from types import SimpleNamespace

from edakit.ibom import delivery_window as w, manufacturing as m


def test_material_requirements_switch_export_and_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(w.delivery.exporter, 'settings', lambda: {})
    args = SimpleNamespace(source=str(tmp_path/'pcb.brd'), board=str(tmp_path/'copy.brd'))
    root = tk.Tk()
    view = w.DeliveryWindow(root, args)
    try:
        editor = next(widget for f, _, widget in view.entries if f['label'] == '板材')
        editor.variables['TG要求'].set('TG≥155℃')
        editor.category.set('铝基板')
        assert 'TG要求' not in editor.variables
        assert 'TG' not in editor.variable.get()
        editor.variables['导热系数要求'].set('≥2 W/m·K')
        assert '导热系数要求：≥2 W/m·K' in editor.variable.get()
        editor.category.set('FPC软板')
        editor.variables['基材/型号'].set('PI')
        editor.category.set('FR-4')
        assert editor.variables['TG要求'].get() == 'TG≥155℃'
        assert '导热系数要求' not in editor.snapshot()
        editor.category.set('铝基板')
        view.save_settings()
        saved = json.loads(view.config.read_text(encoding='utf-8'))
        record = saved['boards'][w.delivery.exporter.board_key(args.source)]
        spec = next(v for v in record['specValues'].values() if 'materialDrafts' in v)
        assert spec['parts'] == {'类别': '铝基板', '导热系数要求': '≥2 W/m·K'}
        assert spec['materialDrafts']['FR-4']['TG要求'] == 'TG≥155℃'
        exported = w.delivery.template_fields(w.delivery.fill_template(view.loaded_data, view.field_values()))
        value = next(f['value'] for f in exported if f['label'] == '板材')
        assert 'TG' not in value and '≥2 W/m·K' in value
    finally:
        view.stop_polling(); root.destroy()
    root = tk.Tk()
    view = w.DeliveryWindow(root, args)
    try:
        editor = next(widget for f, _, widget in view.entries if f['label'] == '板材')
        assert editor.category.get() == '铝基板'
        assert editor.variables['导热系数要求'].get() == '≥2 W/m·K'
        editor.category.set('FR-4')
        assert editor.variables['TG要求'].get() == 'TG≥155℃'
        editor.category.set('FPC软板')
        assert editor.variables['基材/型号'].get() == 'PI'
    finally:
        view.stop_polling(); root.destroy()


def test_old_high_frequency_requirement_is_preserved_without_tg_relabel():
    from edakit.ibom.manufacturing_form import MaterialEditor
    root = tk.Tk()
    try:
        saved = {'类别': '罗杰斯高频板', 'TG要求': 'RO4350B'}
        variable = tk.StringVar(root, value=m.compose('板材', saved))
        editor = MaterialEditor(root, {'label': '板材'}, variable, 4, saved)
        assert editor.category.get() == '高频板'
        assert 'RO4350B' in editor.extra.get()
        assert 'TG要求' not in editor.variables
    finally:
        root.destroy()

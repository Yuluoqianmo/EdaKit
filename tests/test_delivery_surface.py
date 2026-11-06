"""Full-page rendering, model/export parity and temporary native editor lifecycle."""
import json
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from edakit.ibom import delivery_window as w
from edakit.ibom.delivery_widgets import FormViewport


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(w.delivery.exporter, 'settings', lambda: {})
    root = tk.Tk()
    view = w.DeliveryWindow(root, SimpleNamespace(source=str(tmp_path/'pcb.brd'), board=str(tmp_path/'copy.brd')))
    root.geometry('1220x850')
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    view.reading = False
    view.apply_metadata(dict(values={'PCB层数': '6', 'PCB尺寸': '199.746 × 54.746 mm'},
                             copper_layers=[dict(name=n, kind='CONDUCTOR') for n in ('TOP', 'I1', 'I2', 'I3', 'I4', 'BOTTOM')],
                             choices={'板框层': ['BOARD GEOMETRY/OUTLINE', 'BOARD GEOMETRY/DESIGN_OUTLINE']}))
    view.set_busy(False)
    root.update()
    yield root, view, view.canvases['PCB 参数'].surface, errors
    view.stop_polling()
    root.destroy()
    assert not errors


def field(view, label):
    return next(editor for f, _, editor in view.entries if f['sheet'] == 'PCB说明' and f['label'] == label)


def region(surface, widget):
    return next(box for candidate, box in surface.regions if candidate is widget)


def invoke(root, surface, widget):
    x, y, width, height = region(surface, widget)
    surface.yview_moveto(max(0, y-45)/surface._height)
    root.update()
    surface.event_generate('<Button-1>', x=round(x+width/2),
                           y=round(y-surface.canvasy(0)+height/2))
    root.update()
    if surface.active and isinstance(surface.active[0], ttk.Combobox):
        root.tk.call('ttk::combobox::Unpost', str(surface.active[0]))
        root.update()


def write(root, surface, widget, text):
    invoke(root, surface, widget)
    editor = surface.active[0]
    editor.delete(0, 'end')
    editor.insert(0, text)
    root.update()
    surface.finish()
    root.update()


@pytest.mark.parametrize('scaling', [96/72, 120/72, 144/72])
@pytest.mark.parametrize('size', ['980x650', '1220x850'])
def test_scroll_resize_pages_and_layers_keep_stationary_backing(window, scaling, size):
    root, view, surface, _ = window
    root.tk.call('tk', 'scaling', scaling)
    surface._theme_changed()
    root.geometry(size)
    root.update()
    viewport = view.canvases['PCB 参数']
    for name in ('pcb_design', 'pcb_order'):
        view.collapsibles[name][0].invoke()
    root.update()
    for count in (2, 4, 6, 8):
        next(v for f, v, _ in view.entries if f['sheet'] == 'PCB说明' and f['label'] == 'PCB层数').set(str(count))
        root.update()
        assert ('内层' in field(view, '铜箔厚度').variables) == (count > 2)
    baseline = view.field_values()
    with patch('edakit.ibom.delivery_widgets.repaint_children') as paint:
        for title in tuple(view.pages)*2:
            view.page.set(title)
            view.change_page()
            root.update()
            if title == 'PCB 参数':
                for fraction in (0, .25, .75, 1, .5, 0):
                    viewport.yview_moveto(fraction)
                    root.update()
                    assert viewport.coords(viewport._window) == [0, 0]
                viewport.yview_scroll(100, 'pages')
                root.update()
                assert viewport.yview()[1] == 1
        assert paint.call_count == 0
    assert view.field_values() == baseline
    assert surface.source.winfo_width() == viewport.winfo_width()
    assert all(widget.winfo_width() > 1 for widget, _ in surface.regions)
    assert all(canvas.surface is None for title, canvas in view.canvases.items() if title != 'PCB 参数')


def test_material_drafts_save_reopen_and_workbook_match(window):
    root, view, surface, _ = window
    material = field(view, '板材')
    expected = {}
    for category in w.manufacturing.MATERIALS:
        button = next(b for b in material.choices.buttons if str(b.cget('value')) == category)
        invoke(root, surface, button)
        for key, _ in w.manufacturing.MATERIAL_FIELDS[category]:
            text = category+' 中文规格 ≥ 170℃ '+key
            write(root, surface, material.widgets[key][0], text)
            expected.setdefault(category, {})[key] = text
    for category in reversed(w.manufacturing.MATERIALS):
        material.category.set(category)
        root.update()
        assert {key: material.variables[key].get() for key in expected[category]} == expected[category]
    view.save_settings()
    record = json.loads(view.config.read_text(encoding='utf-8'))['boards'][w.delivery.exporter.board_key(view.source)]
    spec = next(v for v in record['specValues'].values() if 'materialDrafts' in v)
    assert spec['materialDrafts'] == expected
    exported = w.delivery.template_fields(w.delivery.fill_template(view.loaded_data, view.field_values()))
    assert next(f['value'] for f in exported if f['label'] == '板材') == material.variable.get()
    second = tk.Toplevel(root)
    # A real reopen starts a new interpreter; this test shares the existing theme.
    with patch.object(w, 'configure_style', lambda root: None):
        reopened = w.DeliveryWindow(second, view.args)
    try:
        second.update()
        restored = field(reopened, '板材')
        for category in w.manufacturing.MATERIALS:
            restored.category.set(category)
            second.update()
            assert all(restored.variables[key].get() == value for key, value in expected[category].items())
    finally:
        reopened.stop_polling()
        second.destroy()


def test_native_editor_unicode_cancel_clipboard_and_focus_out(window):
    root, view, surface, _ = window
    source = field(view, '板材').widgets['TG要求'][0]
    write(root, surface, source, 'TG≥170℃；中文输入')
    invoke(root, surface, source)
    editor = surface.active[0]
    editor.focus_force()
    editor.insert('end', '取消这段')
    editor.event_generate('<Escape>')
    root.update()
    assert surface.active is None and source.get() == 'TG≥170℃；中文输入'
    invoke(root, surface, source)
    editor = surface.active[0]
    editor.focus_force()
    root.update()
    # Paste exercises Tk native editor handling; composition via a real IME is manual QA.
    # Supply the clipboard through this interpreter's selection helper so QA
    # never overwrites the user's real Windows clipboard (including images).
    root.tk.call('rename', '::tk::GetSelection', '::edakit_test_GetSelection')
    try:
        root.tk.eval('proc ::tk::GetSelection {w selection} {if {$selection eq "CLIPBOARD"} {return "；粘贴规范"}; return [::edakit_test_GetSelection $w $selection]}')
        editor.icursor('end')
        editor.event_generate('<<Paste>>')
        root.update()
        assert source.get().endswith('；粘贴规范')
    finally:
        root.tk.call('rename', '::tk::GetSelection', '')
        root.tk.call('rename', '::edakit_test_GetSelection', '::tk::GetSelection')
    root.focus_force()
    root.update()
    assert surface.active is None


def test_real_combobox_popup_selection_syncs_gerber_outline(window):
    root, view, surface, _ = window
    source = field(view, '板框层')
    invoke(root, surface, source)
    combo = surface.active[0]
    root.tk.call('ttk::combobox::Post', str(combo))
    root.update()
    popdown = root.tk.call('ttk::combobox::PopdownWindow', str(combo))
    assert int(root.tk.call('winfo', 'ismapped', popdown))
    assert surface.active[0] is combo  # Posting must not be mistaken for focus leaving.
    combo.current(2)
    root.tk.call('ttk::combobox::Unpost', str(combo))
    combo.event_generate('<<ComboboxSelected>>')
    root.update()
    assert surface.active is None
    assert view.value('PCB说明', '板框层') == 'BOARD GEOMETRY/DESIGN_OUTLINE'
    assert view.gerber.outline.get() == source.get()


def test_tab_space_shift_tab_and_scroll_endpoints(window):
    root, view, surface, _ = window
    choices = field(view, '板材').choices.buttons
    invoke(root, surface, choices[0])
    surface._tab()
    root.update()
    assert surface.focus_source is choices[1]
    surface.focus_force()
    surface.event_generate('<space>')
    root.update()
    assert field(view, '板材').category.get() == 'FPC软板'
    surface._arrow(-1)
    root.update()
    assert field(view, '板材').category.get() == 'FR-4'
    surface._arrow(1)
    root.update()
    surface._tab(direction=-1)
    root.update()
    assert surface.focus_source is choices[0]
    viewport = view.canvases['PCB 参数']
    viewport.yview('moveto', 1)
    root.update()
    assert viewport.yview()[1] == 1
    viewport.yview_scroll(-100, 'pages')
    root.update()
    assert viewport.yview()[0] == 0
    source = field(view, '板材').widgets['基材/型号'][0]
    invoke(root, surface, source)
    surface.active[0].insert('end', 'PI')
    surface.active[0].event_generate('<MouseWheel>', delta=-120)
    root.update()
    assert surface.active is None and source.get().endswith('PI')


def test_save_busy_page_switch_and_external_updates_close_editor(window):
    root, view, surface, _ = window
    source = field(view, '板材').widgets['TG要求'][0]
    for operation in ('save', 'busy', 'page'):
        invoke(root, surface, source)
        surface.active[0].insert('end', operation)
        if operation == 'save':
            view.save_settings()
        elif operation == 'busy':
            view.set_busy(True)
        else:
            view.page.set('Gerber / 光绘')
            view.change_page()
        root.update()
        assert surface.active is None and source.get().endswith(operation)
        if operation == 'busy':
            before = source.get()
            surface._invoke(source, region(surface, source))
            assert surface.active is None and source.get() == before
            view.set_busy(False)
        view.page.set('PCB 参数')
        view.change_page()
        root.update()
    label = view.summary
    label.configure(text='元数据更新：8 层')
    surface.invalidate()
    root.update()
    assert '元数据更新：8 层' in [surface.itemcget(item, 'text') for item in surface.find_all() if surface.type(item) == 'text']


def test_traces_jobs_and_bindings_removed_when_surface_destroyed():
    root = tk.Tk()
    try:
        viewport = FormViewport(root)
        viewport.pack(fill='both', expand=True)
        form = ttk.Frame(viewport)
        value = tk.StringVar(root, value='独立保留')
        ttk.Entry(form, textvariable=value).pack()
        viewport.attach(form)
        surface = viewport.enable_surface()
        root.update()
        trace = surface._trace
        assert trace in str(root.tk.call('trace', 'info', 'variable', str(value)))
        surface.invalidate()
        surface.destroy()
        root.update()
        assert trace not in str(root.tk.call('trace', 'info', 'variable', str(value)))
        value.set('关闭后仍可更新')
        root.update()
        assert surface._job is None
    finally:
        root.destroy()


def test_external_variable_updates_and_scroll_do_not_rebuild_scene(window):
    root, view, surface, _ = window
    material = field(view, '板材')
    material.variables['TG要求'].set('外部更新的 TG170')
    root.update()
    texts = [surface.itemcget(item, 'text') for item in surface.find_all() if surface.type(item) == 'text']
    assert '外部更新的 TG170' in texts
    with patch.object(surface, '_redraw', wraps=surface._redraw) as redraw:
        for fraction in (0, .1, .5, 1, .6, 0):
            surface.yview_moveto(fraction)
            root.update()
        assert redraw.call_count == 0


def test_long_entry_is_single_line_and_first_click_opens_dropdown(window):
    root, view, surface, _ = window
    material = field(view, '板材')
    material.variables['TG要求'].set('很长的中文规格要求'*40)
    root.update()
    texts = [surface.itemcget(item, 'text') for item in surface.find_all() if surface.type(item) == 'text']
    assert any(text.startswith('很长的中文规格') and text.endswith('…') for text in texts)
    combo = field(view, '板框层')
    x, y, width, height = region(surface, combo)
    surface.yview_moveto(0)
    root.update()
    surface.event_generate('<Button-1>', x=round(x+width-12), y=round(y-surface.canvasy(0)+height/2))
    root.update()
    editor = surface.active[0]
    popdown = root.tk.call('ttk::combobox::PopdownWindow', str(editor))
    assert int(root.tk.call('winfo', 'ismapped', popdown))
    root.tk.call('ttk::combobox::Unpost', str(editor))
    surface.finish()

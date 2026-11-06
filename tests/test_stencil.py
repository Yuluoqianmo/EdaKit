import pytest

from edakit.ibom import stencil as s


def test_catalogue_units_and_legacy_values():
    assert len(s.CATALOGUE) == 12
    for spec in s.CATALOGUE:
        assert s.lookup(spec.value) is spec
        assert s.lookup(spec.label) is spec
        assert s.lookup(s.dimensions(spec.outer)) is spec
        assert all(a < b for a, b in zip(spec.effective, spec.outer))
    assert s.lookup('37×47 cm').effective == (200, 300)
    assert s.lookup('自定义 37×47 cm') is None
    for value in ('', '200×300', '0×10 mm', '-1×2 mm', 'nan×2 mm'):
        assert s.parse_dimensions(value) is None


def test_fit_rotation_and_small_clearance():
    board = (199.746, 54.746)
    fit = s.fit(s.lookup('37×47 cm'), board)
    assert fit['fits'] and not fit['rotated']
    assert min(fit['margin']) == pytest.approx(.127)
    fit = s.fit(s.lookup('30×40 cm'), board)
    assert fit['fits'] and fit['rotated']
    assert not s.fit(s.lookup('30×40 cm'), (300, 300))['fits']
    assert s.fit(None, board) is None
    assert not s.fit(s.lookup('30×40 cm'), board, 0)['fits']
    assert s.fit(s.lookup('30×40 cm'), board, 90)['fits']
    assert s.fit(s.lookup('37×47 cm'), board, 90)['margin'] == pytest.approx((72.627, 50.127))


def test_modern_window_navigation_preview_and_busy_state(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    from types import SimpleNamespace
    from edakit.ibom import delivery_window as w
    from edakit.ibom.manufacturing_form import Editor, StencilSize
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    root = tk.Tk()
    view = w.DeliveryWindow(root, SimpleNamespace(source=str(tmp_path/'design.brd'), board=str(tmp_path/'snapshot.brd')))
    def entry(sheet, label):
        return next((v, widget) for f, v, widget in view.entries if f['sheet'] == sheet and f['label'] == label)
    try:
        # User-approved order defaults are separate from PCB stackup references.
        assert view.value('PCB说明', '板材') == '类别：FR-4'
        entry('PCB说明', 'PCB尺寸')[0].set('199.746 × 54.746 mm')
        entry('钢网', 'PCB尺寸')[0].set('199.746 × 54.746 mm')
        size, selector = entry('钢网', '钢网尺寸')
        assert isinstance(selector, StencilSize)
        size.set('37×47 cm')
        view.page.set('钢网参数'); view.change_page(); root.update()
        assert '有效' in selector.get() and size.get() == '37×47 cm'
        assert '200 × 300 mm' in view.preview_dimensions.cget('text')
        assert '0.127' in view.fit_hint.cget('text')
        selector.set(s.lookup('30×40 cm').label)
        assert size.get() == '30×40 cm'
        assert '90°' in view.orientation_buttons[1].cget('text')
        view.angle.set(90); view.update_preview()
        assert '90°' in view.fit_hint.cget('text')
        size.set('定制钢网')
        assert selector.get() == '定制钢网'
        assert '待确认' in view.preview_dimensions.cget('text')
        # All pages retain their values, and late PCB reads preserve manual edits.
        entry('PCB说明', 'PCB尺寸')[0].set('100 × 50 mm')
        view.apply_metadata(dict(values={'PCB尺寸': '20 × 10 mm', '板材': 'FR-4'}, warnings=[]))
        assert view.value('PCB说明', 'PCB尺寸') == '100 × 50 mm'
        assert view.value('PCB说明', '板材') == '类别：FR-4'
        for geometry in ('980x650', '1220x850'):
            root.geometry(geometry)
            for title in view.pages:
                view.page.set(title); view.change_page(); root.update()
                assert view.button.winfo_rootx()+view.button.winfo_width() <= root.winfo_rootx()+root.winfo_width()
                assert view.button.winfo_rooty()+view.button.winfo_height() <= root.winfo_rooty()+root.winfo_height()
                canvas = view.canvases[title]
                assert canvas.winfo_width() >= 430
                assert canvas.winfo_height() >= 300
                # Native Notebook maps the selected page; widgets are retained.
                assert view.pages[title].winfo_ismapped()
                assert view.notebook.tab(view.notebook.select(), 'text') == title
                for field, _, widget in view.entries:
                    if widget.winfo_ismapped():
                        assert widget.winfo_height() >= 28, field['label']
                        assert widget.winfo_rootx()+widget.winfo_width() <= canvas.winfo_rootx()+canvas.winfo_width(), field['label']
                drawing = view.diagram.find_all()
                view.update_preview()
                assert view.diagram.find_all() == drawing
        entry('PCB说明', 'PCB尺寸')[0].set('80 × 40 mm')
        assert '80 × 40 mm' in view.pcb_info.cget('text')
        view.reading = False
        entry('PCB说明', 'PCB层数')[0].set('2')
        view.set_busy(True)
        assert selector.instate(['disabled'])
        editor = entry('PCB说明', '厚度')[1]
        assert isinstance(editor, Editor)
        assert all(b.instate(['disabled']) for b in editor.widgets['成品板厚'][0].buttons)
        view.set_busy(False)
        assert selector.instate(['readonly'])
        assert all(not b.instate(['disabled']) for b in editor.widgets['成品板厚'][0].buttons)
        for variable in view.selected_outputs.values():
            variable.set(False)
        assert view.button.instate(['disabled'])
        view.selected_outputs['instructions'].set(True)
        assert not view.button.instate(['disabled'])
        assert '1 项' in view.button.cget('text')
    finally:
        view.stop_polling(); root.destroy()


@pytest.mark.parametrize('scaling', [1.0, 1.5, 2.0])
def test_choice_text_fits_at_font_scalings(scaling):
    import tkinter as tk
    from tkinter import ttk
    from tkinter.font import Font
    from edakit.ibom.delivery_window import configure_style
    from edakit.ibom.manufacturing_form import Choices
    root = tk.Tk()
    root.tk.call('tk', 'scaling', scaling)
    configure_style(root)
    root.geometry('430x600')
    variable = tk.StringVar(root, value='过孔塞树脂＋电镀盖帽')
    choices = Choices(root, variable, ['按Gerber文件', '过孔盖油', '过孔塞树脂＋电镀盖帽', 'HDI盲埋孔板'])
    choices.pack(fill='x')
    try:
        root.update()
        font = Font(root, font=('Microsoft YaHei UI', 10))
        for button in choices.buttons:
            lines = button.cget('text').split('\n')
            assert button.winfo_height() >= len(lines)*font.metrics('linespace')+10
            assert button.winfo_width() >= max(font.measure(line) for line in lines)+20
            assert button.winfo_y()+button.winfo_height() <= choices.winfo_height()
        assert choices.buttons[2].instate(['selected'])
        assert not choices.buttons[0].instate(['selected'])
        from edakit.ibom.delivery_theme import PANEL
        assert ttk.Style(root).lookup('ED.Choice.TRadiobutton', 'background', ('selected',)) == '#dfeaf5'
        assert ttk.Style(root).lookup('ED.Choice.TRadiobutton', 'bordercolor', ('selected',)) == '#245885'
        variable.set('HDI盲埋孔板'); root.update()
        assert choices.buttons[3].instate(['selected'])
        assert not choices.buttons[2].instate(['selected'])
    finally:
        root.destroy()

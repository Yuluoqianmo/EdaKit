import tkinter as tk
from tkinter import ttk
from tkinter.font import Font

import pytest

from edakit.ibom.delivery_theme import install, TEXT, MUTED, SELECTED, OUTPUT_SELECTED
from edakit.ibom.delivery_widgets import OutputCard, RoundedPanel


@pytest.mark.parametrize('scaling', [1.0, 1.5, 2.0])
def test_title_typography_output_card_and_native_keyboard_behavior(scaling):
    root = tk.Tk()
    root.tk.call('tk', 'scaling', scaling)
    style = install(root)
    root.geometry('600x450')
    panel = RoundedPanel(root, padding=18)
    panel.pack(fill='both', expand=True)
    title = ttk.Label(panel, text='输出文件', style='ED.Title.TLabel')
    title.pack()
    selected = tk.BooleanVar(root, value=True)
    card = OutputCard(panel, 'Gerber、钻孔与槽铣', 'Gerber 子目录 · 使用当前工程制造参数', selected)
    card.pack(fill='x')
    try:
        root.update()
        assert not str(title.cget('font'))  # No option database override of style typography.
        assert Font(root, font=style.lookup('ED.Title.TLabel', 'font')).actual('size') == 10
        assert style.lookup('ED.Output.TCheckbutton', 'foreground', ('selected',)) == TEXT
        assert str(card.description.cget('foreground')) == MUTED
        assert str(card.description.cget('background')) == OUTPUT_SELECTED
        assert card.description.winfo_y()+card.description.winfo_height() <= card.winfo_height()-5
        assert card.description.winfo_x()+card.description.winfo_width() <= card.winfo_width()-10
        card.description.event_generate('<Button-1>'); root.update()
        assert not selected.get()
        card.focus_force(); root.update()
        card.event_generate('<KeyPress-space>'); card.event_generate('<KeyRelease-space>'); root.update()
        assert selected.get()
        card.configure(state='disabled')
        card.description.event_generate('<Button-1>'); root.update()
        assert selected.get()
        assert panel.surface.find_all()
    finally:
        root.destroy()


@pytest.mark.parametrize('scaling', [1.0, 1.5, 2.0])
def test_combobox_text_arrow_and_entry_are_visible_and_usable(scaling):
    root = tk.Tk()
    root.tk.call('tk', 'scaling', scaling)
    install(root)
    root.geometry('600x240')
    variable = tk.StringVar(root, value='37×47 cm')
    combo = ttk.Combobox(root, textvariable=variable, values=('37×47 cm', '30×40 cm'), state='readonly')
    combo.pack(fill='x', padx=20, pady=20)
    entry = ttk.Entry(root)
    entry.pack(fill='x', padx=20)
    try:
        root.update()
        for widget in (combo, entry):
            assert widget.winfo_height() >= 30
            elements = {widget.identify(x, widget.winfo_height()//2)
                        for x in range(widget.winfo_width())}
            assert any('textarea' in name for name in elements)
        assert 'downarrow' in combo.identify(combo.winfo_width()-5, combo.winfo_height()//2)
        combo.current(1)
        assert variable.get() == '30×40 cm'
        entry.insert(0, 'TEST-9')
        assert entry.get() == 'TEST-9'
    finally:
        root.destroy()

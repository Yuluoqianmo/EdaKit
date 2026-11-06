import tkinter as tk
from tkinter import ttk

from edakit.ibom.delivery_widgets import FormViewport
from edakit.ibom.delivery_widgets import wrap_on_width
from unittest.mock import patch


def test_scroll_moves_form_without_scrolling_canvas_pixels_and_clamps_resize():
    root = tk.Tk()
    try:
        root.geometry('400x300')
        viewport = FormViewport(root, highlightthickness=0)
        viewport.pack(fill='both', expand=True)
        scrollbar = []
        viewport.set_scrollbar(lambda a, b: scrollbar.append((a, b)))
        form = ttk.Frame(viewport, height=1200)
        viewport.attach(form)
        root.update()
        viewport.yview('moveto', .5); root.update()
        assert viewport.coords(viewport._window)[1] == -600
        assert float(viewport.tk.call(str(viewport), 'canvasy', 0)) == 0
        assert scrollbar[-1] == viewport.yview()
        viewport.yview('scroll', 100, 'pages'); root.update()
        assert viewport.yview()[1] == 1
        assert viewport._offset == form.winfo_height()-viewport.winfo_height()
        form.configure(height=100); root.update()
        viewport.yview_scroll(1, 'units'); root.update()
        assert viewport._offset == 0 and viewport.yview() == (0, 1)
        viewport.yview_scroll(-100, 'units')
        assert viewport._offset == 0
    finally:
        root.destroy()


def test_repaint_is_local_and_preserves_form_values_after_scrolling():
    root = tk.Tk()
    try:
        root.geometry('600x350')
        viewport = FormViewport(root, repaint=True, highlightthickness=0)
        viewport.pack(fill='both', expand=True)
        form = ttk.Frame(viewport)
        value = tk.StringVar(root, value='保留输入 TG150')
        ttk.Entry(form, textvariable=value).pack()
        for i in range(35):
            ttk.Radiobutton(form, text='选项 '+str(i), value=str(i)).pack()
        viewport.attach(form)
        root.update()
        assert viewport.repaint_on_scroll
        for fraction in (0, .9, .2, 1, 0):
            viewport.yview_moveto(fraction); root.update()
        assert viewport._paint_job is None
        assert value.get() == '保留输入 TG150'
        label = ttk.Label(form, wraplength=100)
        with patch.object(label, 'configure', wraps=label.configure) as configure:
            wrap_on_width(label, 100)
            assert configure.call_count == 0
            wrap_on_width(label, 200)
            assert configure.call_count == 1
    finally:
        root.destroy()


def test_scroll_repaint_coalesces_and_cancels_on_destroy():
    root = tk.Tk()
    try:
        viewport = FormViewport(root, repaint=True)
        viewport.pack(fill='both', expand=True)
        viewport.attach(ttk.Frame(viewport, height=1800))
        root.update()
        with patch('edakit.ibom.delivery_widgets.repaint_children') as paint:
            for fraction in (.1, .2, .3, .4):
                viewport.yview_moveto(fraction)
            root.update()
            assert paint.call_count == 1
            viewport._position(); root.update()
            assert paint.call_count == 1
            viewport.yview_moveto(.8)
            assert viewport._paint_job is not None
            viewport.destroy()
            root.update()
            assert paint.call_count == 1
    finally:
        root.destroy()

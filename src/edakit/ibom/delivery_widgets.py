"""Production cards with separate title/description typography."""
import tkinter as tk
import sys
from tkinter import ttk
from tkinter.font import Font

from .delivery_theme import PANEL, MUTED, BG, BORDER, OUTPUT_SELECTED


def repaint_children(widget):
    """Repaint the owned viewport and descendants after native geometry settles."""
    if sys.platform != 'win32':
        return False
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    redraw = user.RedrawWindow
    redraw.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.HRGN, wintypes.UINT]
    redraw.restype = wintypes.BOOL
    # RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_UPDATENOW.
    return bool(redraw(widget.winfo_id(), None, None, 0x0185))


def wrap_on_width(label, width):
    """Position-only Configure events must not invalidate label painting."""
    if int(label.cget('wraplength')) != width:
        label.configure(wraplength=width)


class FormViewport(tk.Canvas):
    """Clip a native form without Canvas pixel-copy scrolling on Windows.

    Canvas.yview scrolls both copied pixels and embedded native child windows.
    Moving only the form keeps those two rendering paths from tearing apart.
    """
    def __init__(self, parent, repaint=False, **kwargs):
        super().__init__(parent, **kwargs)
        self.repaint_on_scroll = repaint
        self._paint_job = None
        self._placed_offset = None
        self.form = None
        self._offset = 0
        self._height = 1
        self._notify = None
        self.surface = None
        self.bind('<Configure>', self._resize)
        self.bind('<Destroy>', self._cleanup_paint, add='+')

    def _cleanup_paint(self, event):
        if event.widget is self and self._paint_job is not None:
            self.after_cancel(self._paint_job)
            self._paint_job = None

    def _repaint(self):
        self._paint_job = None
        if self.winfo_viewable():
            repaint_children(self)

    def attach(self, form):
        self.form = form
        self._window = self.create_window(0, 0, window=form, anchor='nw')
        form.bind('<Configure>', self._form_size, add='+')
        self._resize()

    def enable_surface(self):
        """Use one drawing plane for dense manufacturing forms only."""
        if self.surface is None:
            from .delivery_surface import FormSurface
            self.repaint_on_scroll = False
            if self._paint_job is not None:
                self.after_cancel(self._paint_job)
                self._paint_job = None
            self._offset = 0
            self.coords(self._window, 0, 0)
            self._placed_offset = 0
            self.surface = FormSurface(self)
        return self.surface

    def finish_edit(self):
        if self.surface is not None:
            self.surface.finish()

    def set_scrollbar(self, callback):
        self._notify = callback
        self._position()

    def _form_size(self, event):
        self._height = max(1, event.height)
        self._position()

    def _resize(self, event=None):
        if self.form is not None:
            self.itemconfigure(self._window, width=max(1, self.winfo_width()))
            self._position()

    def _position(self):
        if self.surface is not None:
            self.surface.invalidate()
            return
        if self.form is not None:
            # Offscreen embedded windows can be unmapped, so their requested
            # size may change before Tk emits another Configure event.
            self._height = max(1, self.form.winfo_reqheight())
        visible = max(1, self.winfo_height())
        self._offset = min(max(0, self._offset), max(0, self._height-visible))
        if self.form is not None and self._placed_offset != self._offset:
            self.coords(self._window, 0, -self._offset)
            self._placed_offset = self._offset
            if self.repaint_on_scroll and self._paint_job is None:
                self._paint_job = self.after_idle(self._repaint)
        if self._notify:
            self._notify(*self.yview())

    def yview(self, *args):
        if self.surface is not None:
            return self.surface.yview(*args)
        if not args:
            return (self._offset/self._height,
                    min(1.0, (self._offset+max(1, self.winfo_height()))/self._height))
        if args[0] == 'moveto':
            self.yview_moveto(float(args[1]))
        elif args[0] == 'scroll':
            self.yview_scroll(int(args[1]), args[2])

    def yview_moveto(self, fraction):
        if self.surface is not None:
            return self.surface.yview_moveto(fraction)
        self._offset = round(float(fraction)*self._height)
        self._position()

    def yview_scroll(self, number, what):
        if self.surface is not None:
            return self.surface.yview_scroll(number, what)
        step = max(1, round(self.winfo_height()*.9)) if what == 'pages' else max(20, round(float(self.tk.call('tk', 'scaling'))*18))
        self._offset += int(number)*step
        self._position()


class RoundedPanel(ttk.Frame):
    """Decorative background does not participate in content size negotiation."""
    def __init__(self, parent, **kwargs):
        super().__init__(parent, style='ED.Background.TFrame', **kwargs)
        self.surface = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=BG)
        self.surface.place(x=0, y=0, relwidth=1, relheight=1)
        self.tk.call('lower', str(self.surface))
        self.bind('<Configure>', self.paint)

    def paint(self, event):
        if getattr(self, '_paint_size', None) == (event.width, event.height):
            return
        self._paint_size = (event.width, event.height)
        w, h, r = event.width-1, event.height-1, 12
        self.surface.delete('all')
        self.surface.create_polygon(r, 1, w-r, 1, w, 1, w, r, w, h-r, w, h,
                                    w-r, h, r, h, 1, h, 1, h-r, 1, r, 1, 1,
                                    smooth=True, splinesteps=24, fill=PANEL, outline=BORDER)


class OutputCard(ttk.Checkbutton):
    """Quiet checklist row; title, description and optional output location."""
    def __init__(self, parent, title, description, variable, location=''):
        self.variable, self.description_text = variable, description
        self.location_text = location
        super().__init__(parent, text='  '+title, variable=variable,
                         style='ED.Output.TCheckbutton', padding=(14, 10, 14, 30))
        self.description = ttk.Label(self, text=description, foreground=MUTED,
                                     font=('Microsoft YaHei UI', 9))
        self.description.bind('<Button-1>', self.click_description)
        self.location = ttk.Label(self, text=location, foreground=MUTED, font=('Microsoft YaHei UI', 9)) if location else None
        if self.location:
            self.location.bind('<Button-1>', self.click_description)
        self.trace = variable.trace_add('write', self.refresh)
        self.bind('<Configure>', self.layout_description)
        self.bind('<Destroy>', self.cleanup)
        self.refresh()

    def click_description(self, event):
        self.focus_set()
        self.invoke()
        return 'break'

    def layout_description(self, event=None):
        title_font = Font(self, font=('Microsoft YaHei UI', 10, 'bold'))
        scale = max(1, float(self.tk.call('tk', 'scaling'))/(96/72))
        left = 14+round(18*scale)+8
        reserve = 145 if self.location else 20
        self.description.configure(wraplength=max(100, self.winfo_width()-left-reserve))
        self.description.place(x=left, y=14+title_font.metrics('linespace'), width=max(100, self.winfo_width()-left-reserve))
        if self.location:
            self.location.place(relx=1, x=-135, rely=.5, anchor='w', width=120)
        padding = (14, 10, reserve, self.description.winfo_reqheight()+13)
        if tuple(int(x) for x in self.cget('padding')) != padding:
            super().configure(padding=padding)

    def refresh(self, *_):
        self.description.configure(background=OUTPUT_SELECTED if self.variable.get() else '#fff')
        if self.location:
            self.location.configure(background=OUTPUT_SELECTED if self.variable.get() else '#fff')

    def cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self.trace)

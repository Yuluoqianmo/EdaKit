"""Paint a form on one scrolling surface, with native controls while editing.

The original form remains stationary underneath for layout and model bindings.
Only Canvas items scroll; independent child HWNDs never move with the page.
"""
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font

from .delivery_theme import PANEL, TEXT, MUTED, BORDER, BLUE, FONT


class FormSurface(tk.Canvas):
    def __init__(self, viewport):
        super().__init__(viewport, background=PANEL, highlightthickness=0,
                         takefocus=True, yscrollincrement=1)
        self.viewport, self.source = viewport, viewport.form
        self.style = ttk.Style(self)
        self.regions, self.active, self.focus_source = [], None, None
        self._job, self._closed, self._drawing = None, False, False
        self._bindings, self._variables, self._fonts = {}, set(), {}
        self._focus_jobs = set()
        self._trace = self.register(self.invalidate)
        self._height = 1
        self._finishing = False
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.tk.call('raise', str(self))
        self.configure(yscrollcommand=self._notify_scrollbar)
        self.bind('<Configure>', self._resize)
        self.bind('<Map>', self.invalidate)
        self.bind('<<ThemeChanged>>', self._theme_changed)
        self.bind('<Button-1>', self._click)
        self.bind('<MouseWheel>', self._wheel)
        self.bind('<Tab>', self._tab)
        self.bind('<Shift-Tab>', lambda e: self._tab(e, -1))
        self.bind('<ISO_Left_Tab>', lambda e: self._tab(e, -1))
        self.bind('<space>', self._activate)
        self.bind('<Return>', self._activate)
        self.bind('<Up>', lambda e: self._arrow(-1))
        self.bind('<Down>', lambda e: self._arrow(1))
        self.bind('<Left>', lambda e: self._arrow(-1))
        self.bind('<Right>', lambda e: self._arrow(1))
        self.bind('<Prior>', lambda e: self._key_scroll(-1, 'pages'))
        self.bind('<Next>', lambda e: self._key_scroll(1, 'pages'))
        self.bind('<Home>', lambda e: self._key_end(0))
        self.bind('<End>', lambda e: self._key_end(1))
        self.bind('<Destroy>', self._cleanup, add='+')
        self.invalidate()

    def invalidate(self, *_):
        if not self._closed and self._job is None:
            self._job = self.after_idle(self._redraw)

    def _resize(self, event):
        if self.active:
            self.finish()
        self.invalidate()

    def _theme_changed(self, *_):
        self._fonts.clear()
        self.invalidate()

    def _option(self, widget, name, default=''):
        try:
            value = widget.cget(name)
            return value if str(value) else default
        except tk.TclError:
            return default

    def _look(self, widget, name, default):
        value = self._option(widget, name)
        return value or self.style.lookup(
            self._option(widget, 'style', widget.winfo_class()), name,
            state=widget.state(), default=default)

    def _font(self, widget):
        value = self._look(widget, 'font', FONT)
        key = str(value)
        if key not in self._fonts:
            self._fonts[key] = Font(self, font=value)
        return self._fonts[key]

    def _walk(self, parent, x=0, y=0):
        for widget in parent.winfo_children():
            if not widget.winfo_manager():
                continue
            xx, yy = x+widget.winfo_x(), y+widget.winfo_y()
            yield widget, xx, yy
            yield from self._walk(widget, xx, yy)

    def _watch(self, widgets):
        alive = set(widgets)
        for widget in set(self._bindings)-alive:
            for sequence, binding in self._bindings.pop(widget):
                try:
                    widget.unbind(sequence, binding)
                except tk.TclError:
                    pass
        variables = set()
        for widget in widgets:
            if widget not in self._bindings:
                self._bindings[widget] = [
                    (sequence, widget.bind(sequence, self.invalidate, add='+'))
                    for sequence in ('<Configure>', '<Map>', '<Unmap>', '<Destroy>')]
                if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox,
                                       ttk.Radiobutton, ttk.Checkbutton)):
                    # The surface owns traversal; backing controls only lay out.
                    widget.configure(takefocus=False)
            for option in ('textvariable', 'variable'):
                variable = str(self._option(widget, option))
                if variable:
                    variables.add(variable)
        for variable in self._variables-variables:
            self.tk.call('trace', 'remove', 'variable', variable, 'write', self._trace)
        for variable in variables-self._variables:
            self.tk.call('trace', 'add', 'variable', variable, 'write', self._trace)
        self._variables = variables

    def _rounded(self, x, y, width, height, fill, border, thickness=1):
        scale = max(1, float(self.tk.call('tk', 'scaling'))/(96/72))
        r = min(5*scale, width/2, height/2)
        return self.create_polygon(
            x+r, y, x+width-r, y, x+width, y, x+width, y+r,
            x+width, y+height-r, x+width, y+height, x+width-r, y+height,
            x+r, y+height, x, y+height, x, y+height-r, x, y+r, x, y,
            smooth=True, splinesteps=12, fill=fill, outline=border, width=thickness)

    def _text(self, widget, x, y, width, height, text, inset=1,
              center=False, color=None, wrap=True):
        font = self._font(widget)
        if not wrap:
            text = str(text)
            available = max(1, width-2*inset)
            if font.measure(text) > available:
                while text and font.measure(text+'…') > available:
                    text = text[:-1]
                text += '…'
        return self.create_text(
            x+width/2 if center else x+inset, y+height/2,
            anchor='center' if center else 'w', text=text, font=font,
            fill=color or self._look(widget, 'foreground', TEXT),
            justify=self._option(widget, 'justify', 'left'),
            width=max(1, width-2*inset) if wrap else 0)

    def _redraw(self):
        self._job = None
        if self._closed or self._drawing:
            return
        self._drawing = True
        try:
            nodes = list(self._walk(self.source))
            self._watch([self.source]+[w for w, _, _ in nodes])
            self._height = max(1, self.source.winfo_reqheight())
            self.configure(scrollregion=(0, 0, max(1, self.winfo_width()), self._height))
            self.delete('all')
            self.regions = []
            for widget, x, y in nodes:
                width, height = widget.winfo_width(), widget.winfo_height()
                if width <= 1 or height <= 1:
                    continue  # A newly expanded group will invalidate on Configure.
                if isinstance(widget, ttk.LabelFrame):
                    self.create_rectangle(x+1, y+10, x+width-1, y+height-1,
                                          fill=PANEL, outline=BORDER)
                    title = self._option(widget, 'text')
                    title_width = self._font(widget).measure(title)+10
                    self.create_rectangle(x+8, y, x+8+title_width, y+20,
                                          fill=PANEL, outline='')
                    self._text(widget, x+12, y, title_width, 20, title)
                elif isinstance(widget, ttk.Frame):
                    self.create_rectangle(x, y, x+width, y+height,
                                          fill=self._look(widget, 'background', PANEL), outline='')
                elif isinstance(widget, ttk.Label):
                    self._text(widget, x, y, width, height, self._option(widget, 'text'))
                elif isinstance(widget, (ttk.Entry, ttk.Combobox)):
                    disabled = widget.instate(['disabled'])
                    self.create_rectangle(x, y+1, x+width, y+height-1,
                                          fill='#eee' if disabled else '#fff',
                                          outline=BLUE if widget is self.focus_source else BORDER)
                    inset = 7
                    arrow = 22 if isinstance(widget, ttk.Combobox) else 0
                    self._text(widget, x, y, max(1, width-arrow), height, widget.get(),
                               inset=inset, color=MUTED if disabled else TEXT, wrap=False)
                    if arrow:
                        self.create_text(x+width-12, y+height/2, text='▾', fill=MUTED)
                    self.regions.append((widget, (x, y, width, height)))
                elif isinstance(widget, (ttk.Button, ttk.Radiobutton, ttk.Checkbutton)):
                    selected = widget.instate(['selected'])
                    disabled = widget.instate(['disabled'])
                    if isinstance(widget, ttk.Button):
                        self.create_rectangle(x, y, x+width, y+height,
                                              fill=self._look(widget, 'background', '#e5e5e5'),
                                              outline=BLUE if widget is self.focus_source else BORDER)
                    else:
                        self._rounded(x, y, width, height,
                                      '#eee' if disabled else '#e1ecf6' if selected else '#fff',
                                      '#d4d4d4' if disabled else '#346c99' if selected else BLUE if widget is self.focus_source else '#b4b7ba',
                                      thickness=2 if selected else 1)
                    self._text(widget, x, y, width, height, self._option(widget, 'text'),
                               inset=6, center=True,
                               color=MUTED if widget.instate(['disabled']) else BLUE if selected else TEXT)
                    self.regions.append((widget, (x, y, width, height)))
                elif isinstance(widget, ttk.Separator):
                    self.create_line(x, y, x+width, y, fill=BORDER)
            if self.active:
                editor, source, _ = self.active
                region = next((box for w, box in self.regions if w is source), None)
                if region is None or source.instate(['disabled']):
                    self.finish()
                else:
                    x, y, width, height = region
                    editor.place(x=x, y=round(y-self.canvasy(0)), width=width, height=height)
        finally:
            self._drawing = False

    def finish(self, cancel=False):
        """Close the temporary editor; its variable is the original model variable."""
        if self._finishing or not self.active:
            return
        self._finishing = True
        try:
            editor, source, old = self.active
            # Transfer focus before destroying the native editor (including IME).
            if self.focus_get() is editor:
                self.focus_set()
            self.active = None
            if cancel and source.winfo_exists():
                variable = self._option(source, 'textvariable')
                if variable:
                    self.setvar(variable, old)
            if editor.winfo_exists():
                editor.destroy()
            self.invalidate()
        finally:
            self._finishing = False

    def _focus_out(self, editor):
        def settled():
            self._focus_jobs.discard(job)
            if self._closed or not self.active or self.active[0] is not editor:
                return
            focus = self.tk.call('focus')
            if not str(focus).startswith(str(editor)):
                self.finish()
        job = self.after_idle(settled)
        self._focus_jobs.add(job)

    def _edit(self, source, box):
        x, y, width, height = box
        options = dict(textvariable=source.cget('textvariable'), font=self._font(source))
        if isinstance(source, ttk.Combobox):
            editor = ttk.Combobox(self, values=source.cget('values'),
                                  state=source.cget('state'), **options)
            def selected(event):
                source.event_generate('<<ComboboxSelected>>')
                self.finish()
            editor.bind('<<ComboboxSelected>>', selected)
        else:
            editor = ttk.Entry(self, **options)
        self.active = (editor, source, source.get())
        editor.place(x=x, y=round(y-self.canvasy(0)), width=width, height=height)
        editor.focus_set()
        editor.bind('<Return>', lambda e: (self.finish(), 'break')[-1])
        editor.bind('<Escape>', lambda e: (self.finish(cancel=True), 'break')[-1])
        editor.bind('<Tab>', self._tab)
        editor.bind('<Shift-Tab>', lambda e: self._tab(e, -1))
        editor.bind('<ISO_Left_Tab>', lambda e: self._tab(e, -1))
        editor.bind('<MouseWheel>', self._wheel)
        editor.bind('<FocusOut>', lambda e: self._focus_out(editor))

    def _invoke(self, source, box):
        if not source.winfo_exists() or source.instate(['disabled']):
            return
        self.focus_source = source
        if isinstance(source, (ttk.Entry, ttk.Combobox)):
            self._edit(source, box)
        else:
            self.focus_set()
            source.invoke()
        self.invalidate()

    def _click(self, event):
        self.finish()
        x, y = self.canvasx(event.x), self.canvasy(event.y)
        for source, box in reversed(self.regions):
            xx, yy, width, height = box
            if xx <= x < xx+width and yy <= y < yy+height:
                self._invoke(source, box)
                if (isinstance(source, ttk.Combobox) and self.active and
                        (source.instate(['readonly']) or x >= xx+width-24)):
                    self.tk.call('ttk::combobox::Post', str(self.active[0]))
                break
        return 'break'

    def _activate(self, event=None):
        for source, box in self.regions:
            if source is self.focus_source:
                self._invoke(source, box)
                break
        return 'break'

    def _tab(self, event=None, direction=1):
        self.finish()
        controls = [(w, box) for w, box in self.regions if not w.instate(['disabled'])]
        widgets = [w for w, _ in controls]
        index = widgets.index(self.focus_source) if self.focus_source in widgets else (-1 if direction > 0 else len(widgets))
        target = index+direction
        if not 0 <= target < len(controls):
            self.focus_set()
            (self.tk_focusNext() if direction > 0 else self.tk_focusPrev()).focus_set()
            return 'break'
        source, box = controls[target]
        self.focus_source = source
        _, y, _, height = box
        top = self.canvasy(0)
        if y < top:
            super().yview_moveto(max(0, y-8)/self._height)
        elif y+height > top+self.winfo_height():
            super().yview_moveto(max(0, y+height-self.winfo_height()+8)/self._height)
        if isinstance(source, (ttk.Entry, ttk.Combobox)):
            self._edit(source, box)
        else:
            self.focus_set()
        self.invalidate()
        return 'break'

    def _wheel(self, event):
        self.yview_scroll(-int(event.delta/120), 'units')
        return 'break'

    def _key_scroll(self, number, what):
        self.yview_scroll(number, what)
        return 'break'

    def _arrow(self, direction):
        source = self.focus_source
        if isinstance(source, ttk.Radiobutton) and source.winfo_exists():
            variable = self._option(source, 'variable')
            group = [(w, box) for w, box in self.regions
                     if isinstance(w, ttk.Radiobutton) and
                     self._option(w, 'variable') == variable and not w.instate(['disabled'])]
            widgets = [w for w, _ in group]
            if source in widgets:
                target, box = group[(widgets.index(source)+direction) % len(group)]
                self._invoke(target, box)
                return 'break'
        return self._key_scroll(direction, 'units')

    def _key_end(self, fraction):
        self.yview_moveto(fraction)
        return 'break'

    def yview(self, *args):
        if args:
            self.finish()
        return super().yview(*args)

    def yview_moveto(self, fraction):
        self.finish()
        return super().yview_moveto(fraction)

    def yview_scroll(self, number, what):
        self.finish()
        pixels = round(self.winfo_height()*.9) if what == 'pages' else max(20, round(float(self.tk.call('tk', 'scaling'))*18))
        return super().yview_scroll(int(number)*pixels, 'units')

    def _notify_scrollbar(self, first, last):
        if self.viewport._notify:
            self.viewport._notify(first, last)

    def _cleanup(self, event):
        if event.widget is not self or self._closed:
            return
        self._closed = True
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        for job in self._focus_jobs:
            self.after_cancel(job)
        self._focus_jobs.clear()
        for variable in self._variables:
            try:
                self.tk.call('trace', 'remove', 'variable', variable, 'write', self._trace)
            except tk.TclError:
                pass
        for widget, bindings in self._bindings.items():
            for sequence, binding in bindings:
                try:
                    widget.unbind(sequence, binding)
                except tk.TclError:
                    pass
        self._variables.clear()
        self._bindings.clear()

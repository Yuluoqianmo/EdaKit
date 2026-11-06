"""Tk editors for manufacturing choices; the workbook remains unchanged."""
import tkinter as tk
from tkinter import ttk
from tkinter.font import Font

from . import manufacturing as m
from . import stencil
from .delivery_theme import FONT
from .delivery_widgets import wrap_on_width


def wrapped(widget, text, width):
    font = Font(widget, font=FONT)
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for char in paragraph:
            if line and font.measure(line+char) > max(30, width):
                lines.append(line)
                line = ''
            line += char
        lines.append(line)
    return '\n'.join(lines)


class Choices(ttk.Frame):
    """Content-sized choice buttons that wrap to the available form width."""
    def __init__(self, parent, variable, options):
        super().__init__(parent)
        self.buttons = [ttk.Radiobutton(self, text=value, value=value, variable=variable,
                                       style='ED.Choice.TRadiobutton') for value in options]
        self.options, self.variable = options, variable
        self._layout_key = None
        self._font = Font(self, font=FONT)
        self.trace = variable.trace_add('write', self.refresh)
        self.bind('<Destroy>', self.cleanup)
        self.bind('<Configure>', self.reflow)
        self.refresh()
        self.reflow()

    def refresh(self, *_):
        for button, value in zip(self.buttons, self.options):
            button.configure(text=('✓ ' if self.variable.get() == value else '')+value)
        if self.winfo_width() > 1:
            self.reflow()

    def cleanup(self, event):
        if event.widget is self:
            self.variable.trace_remove('write', self.trace)

    def reflow(self, event=None):
        width = max(1, event.width if event is not None else self.winfo_width())
        if width <= 1:
            return
        key = (width, self.variable.get())
        if self._layout_key == key:
            return
        self._layout_key = key
        font = self._font
        y, used, row_height = 0, 0, 0
        for button, value in zip(self.buttons, self.options):
            text = ('✓ ' if self.variable.get() == value else '')+value
            button.configure(text=wrapped(self, text, width-36))
            needed = min(width, max(button.winfo_reqwidth(), max(font.measure(t) for t in button.cget('text').split('\n'))+36))
            height = max(button.winfo_reqheight(), len(button.cget('text').split('\n'))*font.metrics('linespace')+14)
            if used and used+needed > width:
                y, used, row_height = y+row_height+6, 0, 0
            button.place(x=used, y=y, width=needed, height=height)
            used += needed+6
            row_height = max(row_height, height)
        requested_height = y+row_height+4
        if int(self.cget('height')) != requested_height:
            self.configure(height=requested_height)


class StencilSize(ttk.Combobox):
    """Show effective area without changing saved/exported canonical size values."""
    def __init__(self, parent, variable, **kwargs):
        self.value = variable
        self.display = tk.StringVar(parent)
        self.syncing = False
        self.labels = {spec.value: spec.label for spec in stencil.CATALOGUE}
        super().__init__(parent, textvariable=self.display, state='readonly', **kwargs)
        self.value.trace_add('write', self.from_value)
        self.display.trace_add('write', self.from_display)
        self.from_value()

    def from_value(self, *_):
        if self.syncing:
            return
        self.syncing = True
        try:
            value = self.value.get()
            spec = stencil.lookup(value)
            label = spec.label if spec else value
            options = ['']+list(self.labels.values())
            if label and label not in options:
                options.append(label)
            self.configure(values=options)
            self.display.set(label)
        finally:
            self.syncing = False

    def from_display(self, *_):
        if not self.syncing:
            reverse = {label: value for value, label in self.labels.items()}
            self.value.set(reverse.get(self.display.get(), self.display.get()))


class Editor(ttk.Frame):
    def __init__(self, parent, field, variable, layers, saved=None):
        super().__init__(parent)
        self.field, self.variable = field, variable
        self.parts = m.restore(field['label'], variable.get(), saved)
        self.variables, self.widgets = {}, {}
        self.columnconfigure(0, weight=1)
        self.rebuild(layers)
        if field['label'] == '板材' and saved and '品牌/型号/TG' in saved:
            self.changed()

    def rebuild(self, layers, board_type='', thickness=''):
        if self.variables:
            self.parts.update({key: var.get() for key, var in self.variables.items()})
        definitions = list(m.schema(self.field['label'], layers, board_type, thickness))
        # Preserve inapplicable values after a layer change so validation can expose them.
        if self.parts.get('内层') and not any(key == '内层' for key, _ in definitions):
            definitions.append(('内层', ()))
        # Legacy custom text remains editable; new fields share the workbook's “其他”.
        if self.parts.get('补充要求'):
            definitions.append(('补充要求', ()))
        if getattr(self, 'definitions', None) == definitions:
            return
        self.definitions = definitions
        for child in self.winfo_children():
            child.destroy()
        self.variables, self.widgets = {}, {}
        for row, (key, choices) in enumerate(definitions):
            group = ttk.Frame(self, padding=(14, 10) if key == 'TG要求' else 0,
                              style='ED.Background.TFrame' if key == 'TG要求' else 'TFrame')
            group.grid(row=row, column=0, sticky='ew', pady=(0, 10))
            group.columnconfigure(0, weight=1)
            header = ttk.Frame(group)
            header.grid(row=0, column=0, sticky='ew')
            if len(definitions) > 1:
                title = 'TG 值要求（手工填写）' if key == 'TG要求' else '板材类别' if key == '类别' else key
                heading = ttk.Label(header, text=title, style='ED.Muted.TLabel')
                heading.pack(side='left')
            variable = tk.StringVar(value=self.parts.get(key, ''))
            ttk.Button(header, text='清除', style='ED.Link.TButton', command=lambda v=variable: v.set('')).pack(side='right')
            if choices:
                options = tuple(choices)
                if variable.get() and variable.get() not in options:
                    options += (variable.get(),)
                widget = Choices(group, variable, options)
            else:
                widget = ttk.Entry(group, textvariable=variable)
            widget.grid(row=1, column=0, sticky='ew', pady=(6, 4))
            self.variables[key], self.widgets[key] = variable, (widget, bool(choices))
            variable.trace_add('write', self.changed)

    def changed(self, *_):
        self.parts.update({key: var.get() for key, var in self.variables.items()})
        self.variable.set(m.compose(self.field['label'], self.parts))

    def configure(self, cnf=None, **kwargs):
        state = kwargs.pop('state', None)
        if state is not None:
            def buttons(parent):
                for child in parent.winfo_children():
                    if isinstance(child, ttk.Button):
                        child.configure(state='disabled' if state == 'disabled' else 'normal')
                    buttons(child)
            buttons(self)
            for widget, fixed in self.widgets.values():
                if isinstance(widget, ttk.Frame):
                    for child in widget.winfo_children():
                        child.configure(state='disabled' if state == 'disabled' else 'normal')
                else:
                    widget.configure(state='disabled' if state == 'disabled' else 'readonly' if fixed else 'normal')
        if cnf or kwargs:
            super().configure(cnf, **kwargs)

    def snapshot(self):
        return {key: var.get() for key, var in self.variables.items() if var.get()}


class MaterialEditor(Editor):
    """Material-specific requirements, with independent drafts for each category."""
    def __init__(self, parent, field, variable, layers, saved=None, drafts=None):
        ttk.Frame.__init__(self, parent)
        self.field, self.variable = field, variable
        self.parts = m.restore('板材', variable.get(), saved)
        self.material_drafts = {k: dict(v) for k, v in (drafts or {}).items() if isinstance(v, dict)}
        old_category = self.parts.get('类别', 'FR-4')
        category = '高频板' if old_category in ('罗杰斯高频板', '铁氟龙高频板') else old_category
        self.active_material = category
        self.variables, self.widgets = {}, {}
        self._state, self._changing = 'normal', False
        self.columnconfigure(0, weight=1)
        self.category = tk.StringVar(self, value=category)
        ttk.Label(self, text='板材类别', style='ED.Muted.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 7))
        options = m.MATERIALS + ((category,) if category not in m.MATERIALS else ())
        self.choices = Choices(self, self.category, options)
        self.choices.grid(row=1, column=0, sticky='ew')
        self.requirements = ttk.Frame(self, style='ED.Material.TFrame', padding=15)
        self.requirements.grid(row=2, column=0, sticky='ew', pady=(14, 0))
        self.requirements.columnconfigure(0, weight=1)
        self.note = ttk.Label(self, style='ED.Muted.TLabel', wraplength=420)
        self.note.grid(row=3, column=0, sticky='ew', pady=(8, 10))
        ttk.Separator(self).grid(row=4, column=0, sticky='ew', pady=(4, 10))
        ttk.Label(self, text='补充要求（选填）', style='ED.Heading.TLabel').grid(row=5, column=0, sticky='w')
        self.extra = tk.StringVar(self, value=self.parts.get('补充要求', ''))
        self.extra_entry = ttk.Entry(self, textvariable=self.extra)
        self.extra_entry.grid(row=6, column=0, sticky='ew', pady=(6, 0))
        # Keep legacy requirements visible verbatim; never relabel old TG as conductivity.
        initial = {k: v for k, v in self.parts.items() if k not in ('类别', '补充要求')}
        if category != 'FR-4' and initial.get('TG要求'):
            legacy = initial.pop('TG要求')
            self.extra.set('；'.join(x for x in (self.extra.get(), '原 TG 要求：'+legacy) if x))
        if category != old_category:
            self.extra.set('；'.join(x for x in (self.extra.get(), '原板材类别：'+old_category) if x))
        self.material_drafts[category] = initial
        self._render()
        self.category.trace_add('write', self.changed)
        self.extra.trace_add('write', self.changed)
        self.bind('<Configure>', lambda e: wrap_on_width(self.note, max(100, e.width-4)))
        self.changed()

    def _render(self):
        for child in self.requirements.winfo_children():
            child.destroy()
        self.variables = {'类别': self.category, '补充要求': self.extra}
        self.widgets = {'类别': (self.choices, True), '补充要求': (self.extra_entry, False)}
        category = self.active_material
        ttk.Label(self.requirements, text=category+' · 规格要求', style='ED.MaterialTitle.TLabel').grid(row=0, column=0, sticky='w', pady=(0, 10))
        definitions = m.MATERIAL_FIELDS.get(category, m.MATERIAL_FIELDS['其他板材'])
        for row, (key, title) in enumerate(definitions, 1):
            ttk.Label(self.requirements, text=title, style='ED.Material.TLabel').grid(row=row*2-1, column=0, sticky='w', pady=(4, 4))
            variable = tk.StringVar(self, value=self.material_drafts.get(category, {}).get(key, ''))
            entry = ttk.Entry(self.requirements, textvariable=variable)
            entry.grid(row=row*2, column=0, sticky='ew', pady=(0, 7))
            self.variables[key], self.widgets[key] = variable, (entry, False)
            variable.trace_add('write', self.changed)
        self.note.configure(text=m.MATERIAL_NOTES.get(category, '保留原板材类别；请核对具体材料与加工要求。'))
        self.configure(state=self._state)

    def changed(self, *_):
        if self._changing:
            return
        self._changing = True
        try:
            self.material_drafts[self.active_material] = {k: v.get() for k, v in self.variables.items() if k not in ('类别', '补充要求')}
            if self.category.get() != self.active_material:
                self.active_material = self.category.get()
                self._render()
            self.variable.set(m.compose('板材', self.snapshot()))
        finally:
            self._changing = False

    def rebuild(self, layers, board_type='', thickness=''):
        # Category changes own their rebuild, avoiding destroying the clicked control.
        return

    def configure(self, cnf=None, **kwargs):
        if 'state' in kwargs:
            self._state = kwargs['state']
        super().configure(cnf, **kwargs)

"""Detached production window with grouped forms and a size inspector."""
import json
import os
import queue
import subprocess
import threading
from pathlib import Path

from ..config import app_dir
from ..storage import atomic_write
from . import delivery, board_metadata, manufacturing, stencil
from .manufacturing_form import Editor, MaterialEditor, StencilSize, wrapped

from .delivery_theme import BG, PANEL, MUTED, BORDER, BLUE, SELECTED, FONT, install
from .delivery_widgets import OutputCard, RoundedPanel, FormViewport, wrap_on_width
AMBER, WARM = '#695326', PANEL


def configure_style(root):
    return install(root)


class DeliveryWindow:
    def __init__(self, root, args):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.args, self.source = root, args, Path(args.source)
        self.config = app_dir()/'delivery'/'settings.json'
        try:
            self.saved = json.loads(self.config.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.saved = {}
        self.previous = self.saved.get('boards', {}).get(delivery.exporter.board_key(self.source), {})
        self.fields, self.entries, self.sources = [], [], {}
        self.automatic, self.references = {}, {}
        self.events, self.busy, self.reading = queue.Queue(), False, True
        self.after_id, self.closed, self.loaded_data = None, False, b''
        self.page = tk.StringVar(root, value='PCB 参数')
        self.output = tk.StringVar(root, value=self.previous.get('outputFolder') or str(delivery.output_directory(self.source)))
        self.overwrite = tk.BooleanVar(root, value=False)
        self.selected_outputs = {key: tk.BooleanVar(root, value=key in self.previous.get('outputs', delivery.OUTPUTS)) for key in delivery.OUTPUTS}
        self.angle = tk.IntVar(root, value=0)
        self.status = tk.StringVar(root, value='正在读取 PCB 参数…')
        self.badge = tk.StringVar(root, value='PCB 读取中')
        self.controls, self.pages, self.canvases, self.collapsibles = [], {}, {}, {}
        configure_style(root)
        root.title('EdaKit · 生产交付')
        width = min(1220, max(980, root.winfo_screenwidth()-80))
        height = min(850, max(650, root.winfo_screenheight()-100))
        root.geometry(f'{width}x{height}'); root.minsize(980, 650)
        root.columnconfigure(0, weight=1); root.rowconfigure(1, weight=1)
        header = ttk.Frame(root, padding=(13, 8), style='ED.Background.TFrame')
        header.grid(row=0, column=0, sticky='ew'); header.columnconfigure(0, weight=1)
        ttk.Label(header, text='当前设计：'+self.source.name, style='ED.Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(header, textvariable=self.badge, style='ED.Caption.TLabel').grid(row=0, column=1, sticky='e')
        content = ttk.Frame(root, padding=(12, 0, 12, 0), style='ED.Background.TFrame')
        content.grid(row=1, column=0, sticky='nsew')
        content.columnconfigure(1, weight=1); content.rowconfigure(0, weight=1)
        navigation = ttk.Frame(content, padding=(8, 10), width=168, style='ED.Navigation.TFrame')
        navigation.grid(row=0, column=0, sticky='ns', padx=(0, 10))
        navigation.pack_propagate(False)
        ttk.Label(navigation, text='生产交付', style='ED.Navigation.TLabel').pack(anchor='w', padx=6, pady=(0, 12))
        self.notebook = ttk.Notebook(content, style='ED.Workspace.TNotebook')
        self.notebook.grid(row=0, column=1, sticky='nsew')
        for title in ('PCB 参数', 'Gerber / 光绘', '钢网参数', '交互式 iBOM', '输出文件'):
            ttk.Radiobutton(navigation, text=title, variable=self.page, value=title,
                            style='ED.Nav.TRadiobutton', command=self.change_page).pack(fill='x', pady=2)
            outer = ttk.Frame(self.notebook, padding=10)
            self.notebook.add(outer, text=title); self.pages[title] = outer
            if title in ('PCB 参数', '钢网参数'):
                # Reserve inspector space inside these pages. Moving the
                # shared inspector must not resize the entire Notebook and
                # trigger reflow in every hidden page on each tab switch.
                spacer = ttk.Frame(outer, width=280)
                spacer.pack(side='right', fill='y')
            canvas = FormViewport(outer, background=PANEL, highlightthickness=0)
            scroll = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
            scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
            canvas.set_scrollbar(scroll.set)
            form = ttk.Frame(canvas, padding=(3, 3)); form.columnconfigure(0, weight=1)
            canvas.attach(form)
            self.canvases[title], outer.form = canvas, form
        workspace = content
        self.notebook.bind('<<NotebookTabChanged>>', self.notebook_changed)
        self.aside = ttk.Frame(workspace, padding=(14, 0, 0, 0), width=310, style='ED.Background.TFrame')
        self.aside.place(in_=self.pages['PCB 参数'], relx=1, x=-280, y=10, width=270, relheight=1, height=-20)
        self.aside.grid_propagate(False); self.aside.columnconfigure(0, weight=1)
        self.aside.rowconfigure(0, weight=1)
        self.inspector_canvas = FormViewport(self.aside, background=BG, highlightthickness=0, width=275)
        inspector_scroll = ttk.Scrollbar(self.aside, orient='vertical', command=self.inspector_canvas.yview)
        self.inspector_canvas.grid(row=0, column=0, sticky='nsew')
        inspector_scroll.grid(row=0, column=1, sticky='ns')
        self.inspector_canvas.set_scrollbar(inspector_scroll.set)
        inspector_body = ttk.Frame(self.inspector_canvas, style='ED.Background.TFrame')
        inspector_body.columnconfigure(0, weight=1)
        self.inspector_canvas.attach(inspector_body)
        inspector = RoundedPanel(inspector_body, padding=18)
        inspector.grid(row=0, column=0, sticky='new'); inspector.columnconfigure(0, weight=1)
        self.preview_title = ttk.Label(inspector, text='板框包络', style='ED.Heading.TLabel')
        self.preview_title.grid(row=0, column=0, sticky='w')
        self.diagram = tk.Canvas(inspector, width=218, height=190, highlightthickness=0, background=PANEL)
        self.diagram.grid(row=1, column=0, sticky='ew', pady=8)
        self.preview_dimensions = ttk.Label(inspector, text='', style='ED.Muted.TLabel', justify='left', wraplength=215)
        self.preview_dimensions.grid(row=2, column=0, sticky='ew')
        self.fit_hint = ttk.Label(inspector, text='', foreground=AMBER, background=WARM, padding=9, wraplength=197, justify='left', font=('Microsoft YaHei UI', 9))
        self.fit_hint.grid(row=4, column=0, sticky='ew', pady=(13, 0))
        self.rotation = ttk.Frame(inspector)
        self.rotation.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        self.rotation.columnconfigure(0, weight=1)
        self.orientation_buttons = []
        for row, angle in enumerate((0, 90)):
            choice = ttk.Radiobutton(self.rotation, variable=self.angle, value=angle, style='ED.Choice.TRadiobutton', command=self.update_preview)
            choice.grid(row=row, column=0, sticky='ew', pady=4)
            self.orientation_buttons.append(choice)
        inspector.bind('<Configure>', lambda e: [w.configure(wraplength=max(100, e.width-44)) for w in (self.preview_dimensions, self.fit_hint)], add='+')
        info = ttk.Frame(inspector_body, padding=(3, 18), style='ED.Background.TFrame'); info.grid(row=1, column=0, sticky='new')
        ttk.Label(info, text='当前 PCB', background=BG, font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w')
        self.pcb_info = ttk.Label(info, text='正在读取叠层与尺寸…', style='ED.Caption.TLabel', wraplength=235, justify='left')
        self.pcb_info.pack(anchor='w', pady=(8, 0))
        info.bind('<Configure>', lambda e: self.pcb_info.configure(wraplength=max(100, e.width-12)))
        footer = ttk.Frame(root, padding=(12, 8, 12, 12), style='ED.Background.TFrame')
        footer.grid(row=2, column=0, sticky='ew'); footer.columnconfigure(1, weight=1)
        summary = ttk.Frame(footer, padding=(8, 4))
        summary.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        summary.columnconfigure(0, weight=1)
        self.description = ttk.Label(summary, text='', style='ED.Muted.TLabel', wraplength=900)
        self.description.grid(row=0, column=0, sticky='ew')
        self.status_label = ttk.Label(summary, textvariable=self.status, style='ED.Muted.TLabel', wraplength=900)
        self.status_label.grid(row=1, column=0, sticky='ew')
        summary.bind('<Configure>', lambda e: [w.configure(wraplength=max(100, e.width-24)) for w in (self.description, self.status_label)])
        ttk.Label(footer, text='输出目录', style='ED.Caption.TLabel').grid(row=1, column=0, sticky='w')
        entry = ttk.Entry(footer, textvariable=self.output)
        entry.grid(row=1, column=1, sticky='ew', padx=8)
        choose = ttk.Button(footer, text='浏览…', command=self.browse_output)
        choose.grid(row=1, column=2, sticky='e'); self.controls += [entry, choose]
        self.detail_button = ttk.Button(footer, text='展开读取详情', command=self.toggle_details)
        self.detail_button.grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        actions = ttk.Frame(footer, style='ED.Background.TFrame')
        actions.grid(row=2, column=2, sticky='e', pady=(8, 0))
        apply_button = ttk.Button(actions, text='应用设置', command=self.save_settings)
        apply_button.pack(side='left', padx=(0, 8)); self.controls.append(apply_button)
        self.button = ttk.Button(actions, text='生成所选文件', style='ED.Primary.TButton', command=self.start, state='disabled')
        self.button.pack(side='left')
        self.log = tk.Text(footer, height=4, wrap='word', state='disabled', background='#fff', foreground=MUTED, relief='sunken', borderwidth=1, font=(FONT[0], 9), padx=6, pady=5)
        self.log.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(8, 0)); self.log.grid_remove()
        root.bind('<MouseWheel>', self.wheel)
        self.diagram.bind('<Configure>', lambda event: self.update_preview())
        self.rotation.bind('<Configure>', lambda event: self.update_preview())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.load_template()
        self.build_ibom()
        from .gerber_window import GerberEditor
        self.gerber = GerberEditor(self.pages['Gerber / 光绘'].form, self.previous.get('gerberDraft', {}), self.status.set, self.apply_gerber)
        self.gerber.pack(fill='both', expand=True)
        outline_var = next((v for f, v, _ in self.entries if f['label'] == '板框层'), None)
        if outline_var is not None:
            def from_pcb(*_):
                if outline_var.get() != self.gerber.outline.get():
                    self.gerber.outline.set(outline_var.get())
            def from_gerber(*_):
                if self.gerber.outline.get() != outline_var.get():
                    outline_var.set(self.gerber.outline.get())
            outline_var.trace_add('write', from_pcb)
            self.gerber.outline.trace_add('write', from_gerber)
            if outline_var.get():
                from_pcb()
            elif self.gerber.outline.get():
                from_gerber()
        self.canvases['PCB 参数'].enable_surface()
        self.change_page()
        if getattr(args, 'ibom_only', False):
            self.only_ibom(); self.page.set('交互式 iBOM'); self.change_page()
        for variable in self.selected_outputs.values():
            variable.trace_add('write', self.update_output_selection)
        self.update_output_selection()
        self.after_id = root.after(0, self.poll)
        threading.Thread(target=self.read_metadata, daemon=True).start()

    def section(self, parent, title, subtitle=''):
        from tkinter import ttk
        section = ttk.LabelFrame(parent, text=title, padding=(10, 8))
        section.pack(fill='x', pady=(0, 10))
        if subtitle:
            ttk.Label(section, text=subtitle, style='ED.Muted.TLabel').pack(anchor='w', pady=(0, 6))
        return section

    def expandable(self, parent, key, title):
        from tkinter import ttk
        wrapper = ttk.Frame(parent); wrapper.pack(fill='x', pady=(0, 12))
        body = ttk.Frame(wrapper)
        def toggle():
            if body.winfo_manager():
                body.pack_forget(); button.configure(text='＋ '+title)
            else:
                body.pack(fill='x', pady=(12, 0)); button.configure(text='－ '+title)
        button = ttk.Button(wrapper, text='＋ '+title, style='ED.Link.TButton', command=toggle)
        button.pack(anchor='w'); self.collapsibles[key] = (button, body)
        return body

    def load_template(self):
        from tkinter import messagebox, ttk
        try:
            self.loaded_data = delivery.builtin_template().read_bytes()
            self.fields = delivery.initial_values(delivery.template_fields(self.loaded_data), self.source, self.loaded_data, self.saved)
        except Exception as error:
            messagebox.showerror('制板说明', '内置制板说明无法读取：'+str(error), parent=self.root); return
        pcb = self.pages['PCB 参数'].form
        self.summary = ttk.Label(pcb, text='正在读取 PCB 参数…', style='ED.Note.TLabel', wraplength=460)
        self.summary.pack(fill='x', pady=(0, 17))
        for title, labels in (('板材与规格', ('板框层', '板材', '厚度', '铜箔厚度')), ('表面与阻焊', ('表面处理', '阻焊要求'))):
            section = self.section(pcb, title)
            for label in labels:
                self.add_field(section, 'PCB说明', label)
        details = self.expandable(pcb, 'pcb_design', '设计数据与线宽 / 线距')
        for label in ('PCB尺寸', 'PCB层数', '最小线宽/线距(mil)', '最小孔径(mm)', '层序', '制图软件'):
            self.add_field(details, 'PCB说明', label)
        other = self.expandable(pcb, 'pcb_order', '型号、数量与交期')
        for label in ('型号', '板子数量', '是否加急'):
            self.add_field(other, 'PCB说明', label)
        steel = self.pages['钢网参数'].form
        specs = self.section(steel, '钢网规格')
        for label in ('钢网尺寸', '制作要求'):
            self.add_field(specs, '钢网', label)
        self.field_pair(specs, '钢网', ('数量', '钢网用途'))
        processing = self.section(steel, '加工选项')
        self.field_pair(processing, '钢网', ('MARK点', '抛光工艺'))
        self.field_pair(processing, '钢网', ('工程处理要求', '打印钢网型号（字符）到钢片上'))
        steel_details = self.expandable(steel, 'stencil_details', '型号与 PCB 尺寸')
        for label in ('型号', 'PCB尺寸'):
            self.add_field(steel_details, '钢网', label)
        self.build_output()
        for field, variable, _ in self.entries:
            if field['label'] in ('PCB层数', '板材', '厚度') and field['sheet'] == 'PCB说明':
                variable.trace_add('write', self.update_choices)
            if field['label'] in ('钢网尺寸', 'PCB尺寸', 'PCB层数', '最小孔径(mm)', '最小线宽/线距(mil)', '层序', '板框层'):
                variable.trace_add('write', self.update_preview)
        self.update_choices()

    def add_field(self, parent, sheet, label):
        import tkinter as tk
        from tkinter import ttk
        field = next((f for f in self.fields if f['sheet'] == sheet and f['label'] == label), None)
        if field is None:
            return
        key = sheet+'!'+field['ref']
        variable = tk.StringVar(self.root, value=field['value'])
        block = ttk.Frame(parent); block.pack(fill='x', pady=(0, 10)); block.columnconfigure(1, weight=1)
        label_text = {'板材': '板材与规格要求', '打印钢网型号（字符）到钢片上': '钢片打印型号', '工程处理要求': '工程处理', '钢网用途': '用途'}.get(label, label)
        ttk.Label(block, text=label_text, style='ED.Field.TLabel').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 5))
        layers = manufacturing.layer_count(self.value('PCB说明', 'PCB层数'))
        spec = self.previous.get('specValues', {}).get(key, {})
        if sheet == 'PCB说明' and label == '板材':
            widget = MaterialEditor(block, field, variable, layers,
                                    spec.get('parts') if spec.get('value') == field['value'] else field.get('spec'),
                                    spec.get('materialDrafts'))
        elif sheet == 'PCB说明' and manufacturing.schema(label, layers):
            widget = Editor(block, field, variable, layers, spec.get('parts') if spec.get('value') == field['value'] else field.get('spec'))
        elif sheet == '钢网' and label == '钢网尺寸':
            widget = StencilSize(block, variable)
        elif field['choices'] or label == '板框层':
            options = list(field['choices'])
            if variable.get() and variable.get() not in options:
                options.append(variable.get())
            widget = ttk.Combobox(block, textvariable=variable, values=('',)+tuple(options), state='normal' if label == '板框层' else 'readonly')
        else:
            widget = ttk.Entry(block, textvariable=variable)
        widget.grid(row=1, column=1, sticky='ew')
        hint = ttk.Label(block, text='', style='ED.Muted.TLabel', wraplength=420)
        block.bind('<Configure>', lambda e: wrap_on_width(hint, max(100, e.width-18)))
        hint.grid(row=2, column=0, columnspan=2, sticky='w', pady=(3, 0))
        if label == '阻焊要求':
            hint.configure(text='过孔盖油 / 开窗以 Gerber 图形为准。')
        elif label == '钢网尺寸':
            hint.configure(style='ED.Note.TLabel', text='选择规格后显示有效面积'); self.effective_hint = hint
        self.sources[key] = hint
        self.entries.append((field, variable, widget))

    def field_pair(self, parent, sheet, labels):
        from tkinter import ttk
        row = ttk.Frame(parent); row.pack(fill='x')
        row.columnconfigure(0, weight=1, uniform='fields'); row.columnconfigure(1, weight=1, uniform='fields')
        for column, label in enumerate(labels):
            box = ttk.Frame(row); box.grid(row=0, column=column, sticky='nsew', padx=(0, 7) if column == 0 else (7, 0))
            self.add_field(box, sheet, label)

    def build_output(self):
        from tkinter import ttk
        form = self.pages['输出文件'].form
        self.page_heading(form, '输出文件', '勾选本次需要生成的交付内容')
        heading = ttk.Frame(form, style='ED.List.TFrame', padding=1)
        heading.pack(fill='x', pady=(0, 12))
        columns = ttk.Frame(heading, style='ED.ListHeader.TFrame', padding=(14, 8))
        columns.pack(fill='x')
        ttk.Label(columns, text='交付内容', style='ED.ListHeader.TLabel').pack(side='left')
        ttk.Label(columns, text='输出位置', style='ED.ListHeader.TLabel', width=16).pack(side='right')
        for key, title, description in (
            ('gerber', 'Gerber、钻孔与槽铣', '使用当前工程的制造参数'),
            ('coordinates', '器件坐标 Excel', '顶底面坐标、位号与旋转角度'),
            ('instructions', '加工说明 Excel', 'PCB 制板要求与钢网说明'),
            ('ibom', '交互式 iBOM', '离线查看元件与装配位置')):
            ttk.Separator(heading).pack(fill='x')
            card = OutputCard(heading, title, description, self.selected_outputs[key], self.source.stem+'_art /' if key == 'gerber' else '输出目录')
            card.pack(fill='x')
            self.controls.append(card)
            if key == 'coordinates':
                body = self.expandable(heading, 'coordinate-cover', '坐标文件封面信息')
                self.build_report_metadata(body)
        self.output_count = ttk.Label(form, text='', style='ED.Muted.TLabel')
        self.output_count.pack(anchor='w', pady=(0, 10))
        check = ttk.Checkbutton(form, text='覆盖同名输出文件', variable=self.overwrite, style='ED.Setting.TCheckbutton')
        check.pack(anchor='w', pady=(2, 6)); self.controls.append(check)
        ttk.Label(form, text='所有文件统一输出到下方目录。', style='ED.Muted.TLabel', wraplength=520).pack(anchor='w', pady=(5, 15))
        ttk.Button(form, text='打开输出目录', command=self.open_output).pack(anchor='w')

    def build_report_metadata(self, form):
        from tkinter import ttk
        import datetime
        import tkinter as tk
        saved_report = self.previous.get('reportMetadata', {})
        self.report_metadata = {}
        groups = (
            (('coverTitle', '封面工程名称', self.source.stem),),
            (('documentNumber', '文件编号', ''), ('documentStatus', '文件状态', '正式')),
            (('version', '版本', ''), ('date', '日期', datetime.date.today().isoformat())),
            (('author', '编制', ''), ('reviewer', '审核', ''), ('approver', '批准', '')),
            (('changes', '更改项', ''),),
        )
        for fields in groups:
            line = ttk.Frame(form); line.pack(fill='x', pady=4)
            for column, (key, label, default) in enumerate(fields):
                line.columnconfigure(column, weight=1, uniform='fields')
                field = ttk.Frame(line)
                field.grid(row=0, column=column, sticky='ew', padx=(0 if column == 0 else 12, 0))
                field.columnconfigure(1, weight=1)
                variable = tk.StringVar(self.root, value=default if key == 'date' else saved_report.get(key, default))
                self.report_metadata[key] = variable
                ttk.Label(field, text=label, width=12 if column == 0 else 8).grid(row=0, column=0, sticky='w', padx=(0, 6))
                widget = ttk.Combobox(field, textvariable=variable, width=12, values=('正式', '临时'), state='readonly') if key == 'documentStatus' else ttk.Entry(field, textvariable=variable, width=12)
                widget.grid(row=0, column=1, sticky='ew')
                self.controls.append(widget)


    def build_ibom(self):
        import tkinter as tk
        from tkinter import ttk
        legacy = delivery.exporter.settings().get('bomByBoard', {}).get(delivery.exporter.board_key(self.source), '')
        saved = self.previous.get('ibom', {})
        self.bom_path = tk.StringVar(self.root, value=saved.get('path', legacy))
        self.bom_source = tk.StringVar(self.root, value=saved.get('source', 'file' if legacy else 'pcb'))
        form = self.pages['交互式 iBOM'].form
        self.page_heading(form, '交互式 iBOM', '选择器件信息来源；输出项目在“输出文件”页勾选')
        self.section_heading(form, '器件信息来源')
        section = ttk.Frame(form, style='ED.List.TFrame', padding=1)
        section.pack(fill='x')
        for value, title, description in (
                ('pcb', '使用 PCB 器件属性', '从当前 PCB 获取位号、封装及器件属性'),
                ('file', '使用最终 BOM 表格', '使用 CSV / Excel 中的器件信息与 PCB 位号匹配')):
            if value == 'file':
                ttk.Separator(section).pack(fill='x')
            row = ttk.Frame(section, style='ED.White.TFrame', padding=(12, 10))
            row.pack(fill='x')
            widget = ttk.Radiobutton(row, text=title, value=value, variable=self.bom_source, command=self.update_bom_source, style='ED.Source.TRadiobutton')
            widget.pack(anchor='w'); self.controls.append(widget)
            desc = ttk.Label(row, text=description, style='ED.WhiteMuted.TLabel', wraplength=550)
            desc.pack(anchor='w', padx=(25, 0), pady=(3, 0))
            row.bind('<Configure>', lambda e, label=desc: label.configure(wraplength=max(120, e.width-50)))
        row = ttk.Frame(form); row.pack(fill='x', pady=(10, 4)); row.columnconfigure(0, weight=1)
        self.bom_entry = ttk.Entry(row, textvariable=self.bom_path)
        self.bom_entry.grid(row=0, column=0, sticky='ew')
        self.bom_browse = ttk.Button(row, text='选择 BOM…', command=self.browse_bom)
        self.bom_browse.grid(row=0, column=1, padx=(8, 0))
        self.controls += [self.bom_entry, self.bom_browse]
        ttk.Label(form, text='最终 BOM 将核对位号、重复项与未匹配器件。', style='ED.Muted.TLabel', wraplength=550).pack(anchor='w', pady=6)
        self.update_bom_source()

    def page_heading(self, parent, title, description):
        from tkinter import ttk
        ttk.Label(parent, text=title, style='ED.PageTitle.TLabel').pack(anchor='w', pady=(0, 4))
        ttk.Label(parent, text=description, style='ED.Muted.TLabel').pack(anchor='w', pady=(0, 20))

    def section_heading(self, parent, title):
        from tkinter import ttk
        ttk.Label(parent, text=title, style='ED.Heading.TLabel').pack(anchor='w', pady=(12, 8))
        ttk.Separator(parent).pack(fill='x', pady=(0, 12))

    def update_bom_source(self):
        state = 'normal' if self.bom_source.get() == 'file' and not self.busy else 'disabled'
        for widget in (self.bom_entry, self.bom_browse):
            widget.configure(state=state)

    def browse_bom(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.root, title='选择最终 BOM', filetypes=[('BOM 表格', '*.csv *.xlsx *.xlsm'), ('所有文件', '*.*')])
        if path:
            self.bom_path.set(path)

    def only_ibom(self):
        for key, variable in self.selected_outputs.items():
            variable.set(key == 'ibom')
        self.status.set('已仅选择 iBOM，点击“生成所选 1 项”导出。')
        self.page.set('输出文件'); self.change_page()

    def field_values(self):
        self.canvases['PCB 参数'].finish_edit()
        return [dict(f, value=v.get(), **({'spec': w.snapshot()} if isinstance(w, Editor) else {}),
                     **({'materialDrafts': w.material_drafts} if isinstance(w, MaterialEditor) else {})) for f, v, w in self.entries]

    def remember_settings(self, values, destination, selected, ibom, draft, report_metadata=None):
        delivery.remember_values(self.saved, self.source, self.loaded_data, values, output=destination)
        record = self.saved['boards'][delivery.exporter.board_key(self.source)]
        record.update(outputs=selected, ibom=ibom, gerberDraft=draft)
        record['reportMetadata'] = report_metadata if report_metadata is not None else {k: v.get() for k, v in self.report_metadata.items()}
        current = {f['sheet']+'!'+f['ref']: f['value'] for f in values}
        record['autoValues'] = {k: v for k, v in self.automatic.items() if current.get(k) == v}
        record['specValues'] = {f['sheet']+'!'+f['ref']: {'value': f['value'], 'parts': f['spec'],
                              **({'materialDrafts': f['materialDrafts']} if 'materialDrafts' in f else {})} for f in values if 'spec' in f}
        atomic_write(self.config, json.dumps(self.saved, ensure_ascii=False))

    def save_settings(self):
        from tkinter import messagebox
        try:
            self.remember_settings(self.field_values(), self.output.get(), [k for k, v in self.selected_outputs.items() if v.get()],
                                   dict(source=self.bom_source.get(), path=self.bom_path.get(), open=False), self.gerber.snapshot())
        except (OSError, ValueError) as error:
            messagebox.showerror('保存设置', str(error), parent=self.root)
            return
        self.status.set('窗口设置已保存；Film 编辑请点“写入 PCB”，生成交付包时也会自动写入核验。')

    def update_output_selection(self, *_):
        count = sum(v.get() for v in self.selected_outputs.values())
        self.output_count.configure(text=f'已选择 {count} 项')
        self.button.configure(text=f'生成所选 {count} 项', state='disabled' if not count or self.busy or self.reading else 'normal')
        if self.page.get() == '输出文件':
            self.update_preview()

    def value(self, sheet, label):
        return next((v.get() for f, v, _ in self.entries if f['sheet'] == sheet and f['label'] == label), '')

    def notebook_changed(self, event=None):
        if not self.notebook.select() or not hasattr(self, 'description'):
            return
        title = self.notebook.tab(self.notebook.select(), 'text')
        self.page.set(title)
        self.change_page()

    def change_page(self):
        self.canvases['PCB 参数'].finish_edit()
        title = self.page.get()
        self.notebook.select(self.pages[title])
        self.description.configure(text={
            'PCB 参数': '板级信息从 PCB 读取；制板要求按工程需要选择，TG 值可手工填写。',
            'Gerber / 光绘': '按 PCB 实际叠层设置 Film；导出前自动写入、核验并取得新快照。',
            '钢网参数': '选择钢网规格后查看有效面积，支持 0° / 90° 比较 PCB 包络。',
            '交互式 iBOM': '选择 PCB 属性或最终 BOM；只导出 iBOM 可使用下方快捷按钮。',
            '输出文件': '只生成勾选的内容，统一写入下方输出目录。',
        }[title])
        if title in ('PCB 参数', '钢网参数'):
            self.aside.place(in_=self.pages[title], relx=1, x=-280, y=10, width=270, relheight=1, height=-20)
            self.aside.lift()
        else:
            self.aside.place_forget()
        self.update_preview()

    def wheel(self, event):
        if event.widget is self.log or event.widget.winfo_class() in ('TCombobox', 'Listbox', 'Treeview'):
            return
        canvas = self.canvases.get(self.page.get())
        widget = event.widget
        while widget is not None:
            if widget is self.aside:
                canvas = self.inspector_canvas
                break
            widget = getattr(widget, 'master', None)
        if canvas:
            canvas.yview_scroll(-int(event.delta/120), 'units')

    def update_choices(self, *_):
        layers = manufacturing.layer_count(self.value('PCB说明', 'PCB层数'))
        parts = {f['label']: w.snapshot() for f, _, w in self.entries if isinstance(w, Editor)}
        material, thickness = parts.get('板材', {}).get('类别', ''), parts.get('厚度', {}).get('成品板厚', '')
        for _, _, widget in self.entries:
            if isinstance(widget, Editor):
                widget.rebuild(layers, material, thickness)

    def update_preview(self, *_):
        if self.closed:
            return
        # Configure events also fire after our own label/diagram updates.
        # Skip identical content and geometry to avoid repeated Tcl drawing
        # and per-character font measurements when navigating pages.
        preview_key = (self.page.get(), self.angle.get(),
                       self.diagram.winfo_width(), self.rotation.winfo_width(),
                       tuple(v.get() for v in self.selected_outputs.values()),
                       tuple((f['sheet'], f['label'], v.get()) for f, v, _ in self.entries))
        if getattr(self, '_preview_key', None) == preview_key:
            return
        self._preview_key = preview_key
        pcb_size = self.value('PCB说明', 'PCB尺寸')
        self.pcb_info.configure(text='板尺寸  '+(pcb_size or '未读取')+'\n\n导电层  '+(self.value('PCB说明', 'PCB层数') or '—')+' 层\n\n板框层\n'+(self.value('PCB说明', '板框层') or '待选择'))
        if self.page.get() in ('Gerber / 光绘', '交互式 iBOM'):
            return
        if self.page.get() == '输出文件':
            self.diagram.grid_remove()
            self.rotation.grid_remove()
            self.preview_title.configure(text='交付概览')
            titles = {'gerber': 'Gerber、钻孔与槽铣', 'coordinates': '器件坐标 Excel',
                      'instructions': '加工说明 Excel', 'ibom': '交互式 iBOM'}
            chosen = [titles[key] for key, variable in self.selected_outputs.items() if variable.get()]
            self.preview_dimensions.configure(text=f'已选择 {len(chosen)} 项\n\n'+'\n\n'.join(chosen))
            self.fit_hint.configure(text='所选文件统一写入底部输出目录。' if chosen else '请至少选择一项输出内容。')
            return
        self.diagram.grid()
        steel = self.page.get() == '钢网参数'
        board = stencil.parse_dimensions(self.value('钢网', 'PCB尺寸') if steel else pcb_size)
        spec = stencil.lookup(self.value('钢网', '钢网尺寸'))
        if hasattr(self, 'effective_hint'):
            self.effective_hint.configure(text='可用开孔区域：'+stencil.dimensions(spec.effective) if spec else '请选择标准规格；自定义钢网的有效面积需另行确认。')
        if hasattr(self, 'summary'):
            self.summary.configure(text=(pcb_size or '板尺寸待确认')+'   /   '+(self.value('PCB说明', 'PCB层数') or '—')+' 层   /   最小孔径 '+(self.value('PCB说明', '最小孔径(mm)') or '—')+' mm')
        self.preview_title.configure(text='有效区域示意' if steel else '板框包络')
        self.diagram.delete('all')
        width, height = max(180, self.diagram.winfo_width()), 190
        self.rotation.grid() if steel and spec and board else self.rotation.grid_remove()
        if steel and spec:
            for angle, button in zip((0, 90), self.orientation_buttons):
                comparison = stencil.fit(spec, board, angle)
                if comparison:
                    margin = min(comparison['margin'])
                    label = ('✓ ' if self.angle.get() == angle else '')+str(angle)+'° · '+('可容纳' if comparison['fits'] else '超出有效区域')
                    label += '\n'+(f'最小方向单侧余量 {margin:.3f} mm' if comparison['fits'] else '此方向放不下当前板框包络')
                    button.configure(text=wrapped(button, label, max(100, self.rotation.winfo_width()-32)))
            ew, eh = spec.effective
            fit = stencil.fit(spec, board, self.angle.get())
            scale = min((width-38)/ew, (height-42)/eh)
            if fit and not fit['fits']:
                scale = min(scale, (width-18)/fit['board'][0], (height-25)/fit['board'][1])
            x, y = (width-ew*scale)/2, (height-eh*scale)/2
            self.diagram.create_rectangle(x-7, y-7, x+ew*scale+7, y+eh*scale+7, fill=BG, outline=BORDER)
            self.diagram.create_rectangle(x, y, x+ew*scale, y+eh*scale, fill=PANEL, outline='#b6c6db', dash=(3, 3))
            if fit:
                bw, bh = fit['board']; bx, by = x+(ew-bw)*scale/2, y+(eh-bh)*scale/2
                color = BLUE if fit['fits'] else '#b54737'
                self.diagram.create_rectangle(bx, by, bx+bw*scale, by+bh*scale, fill=SELECTED, outline=color, width=2)
                self.diagram.create_text(width/2, by+bh*scale/2, text='PCB · 90°' if fit['rotated'] else 'PCB', fill=color, font=('Segoe UI', 9))
                if not fit['fits']:
                    title = 'PCB 包络超出有效区域。'
                elif min(fit['margin']) < 1:
                    title = '包络可容纳，余量很小。\n最小方向单侧约 '+f"{min(fit['margin']):.3f}"+' mm。'
                else:
                    title = '旋转 90° 后包络可容纳。' if fit['rotated'] else '单板包络可容纳。'
                hint = title+(' 旋转 90° 后可容纳。' if not fit['fits'] and stencil.fit(spec, board, 90 if self.angle.get() == 0 else 0)['fits'] else '')+'\n仅比较尺寸包络；夹持留边、拼板和顶底合开布局请另行核对。'
            else:
                hint = 'PCB 尺寸未识别，暂不能比较。\n请在“型号与 PCB 尺寸”中核对毫米尺寸。'
            self.preview_dimensions.configure(text='外框尺寸   '+stencil.dimensions(spec.outer)+'\n\n有效面积   '+stencil.dimensions(spec.effective))
        else:
            if board:
                bw, bh = board; scale = min((width-24)/bw, 115/bh)
                x, y = (width-bw*scale)/2, (height-bh*scale)/2
                self.diagram.create_rectangle(x, y, x+bw*scale, y+bh*scale, fill=SELECTED, outline=BLUE, width=2)
                self.diagram.create_text(width/2, y+bh*scale/2, text='PCB', fill=BLUE, font=('Segoe UI', 10))
                self.diagram.create_text(width/2, min(height-10, y+bh*scale+21), text=stencil.dimensions(board), fill=MUTED, font=('Segoe UI', 9))
            else:
                self.diagram.create_text(width/2, height/2, text='尺寸待确认', fill=MUTED, font=FONT)
            if steel:
                self.preview_dimensions.configure(text='外框尺寸   未选标准规格\n\n有效面积   待确认')
                hint = '选择钢网尺寸后显示可用开孔区域。\n自定义或历史规格不会套用标准有效面积。'
            else:
                self.preview_dimensions.configure(text='层序   '+(self.value('PCB说明', '层序') or '待读取')+'\n\n线宽 / 线距   '+(self.value('PCB说明', '最小线宽/线距(mil)') or '待确认')+' mil')
                hint = '最小线宽来自实际走线。\n完整铜间距尚未自动测量，请核对线距。'
        self.fit_hint.configure(text=hint)

    def browse_output(self):
        from tkinter import filedialog
        current = Path(self.output.get()).expanduser()
        value = filedialog.askdirectory(parent=self.root, title='选择生产交付输出目录', initialdir=str(current if current.is_dir() else self.source.parent), mustexist=False)
        if value:
            self.output.set(value)

    def open_output(self):
        path = Path(self.output.get()).expanduser()
        if path.is_dir():
            os.startfile(path)

    def toggle_details(self):
        if self.log.winfo_manager():
            self.log.grid_remove(); self.detail_button.configure(text='展开读取详情')
        else:
            self.log.grid(); self.detail_button.configure(text='收起读取详情')

    def append(self, text, status=True):
        if status:
            self.status.set(text)
        self.log.configure(state='normal'); self.log.insert('end', text+'\n'); self.log.see('end'); self.log.configure(state='disabled')

    def set_busy(self, busy):
        from tkinter import ttk
        self.canvases['PCB 参数'].finish_edit()
        self.busy = busy
        outline_widget = next((w for f, _, w in self.entries if f['label'] == '板框层'), None)
        for widget in self.controls+[w for _, _, w in self.entries]:
            widget.configure(state='disabled' if busy else 'readonly' if isinstance(widget, ttk.Combobox) and widget is not outline_widget else 'normal')
        self.update_bom_source()
        self.gerber.set_busy(busy)
        self.update_output_selection()

        surface = self.canvases['PCB 参数'].surface
        if surface is not None:
            surface.invalidate()

    def start(self):
        from tkinter import messagebox
        if self.busy or self.reading:
            return
        selected = [key for key, variable in self.selected_outputs.items() if variable.get()]
        if not selected:
            return
        if 'instructions' in selected and not self.fields:
            messagebox.showerror('制板说明', '内置制板说明无法读取，请重新安装测试版。', parent=self.root); return
        destination = Path(self.output.get()).expanduser()
        if not self.output.get().strip() or not destination.is_absolute() or (destination.exists() and not destination.is_dir()):
            messagebox.showerror('输出目录', '请选择完整的输出文件夹路径。', parent=self.root); return
        replace = self.overwrite.get()
        if replace and not messagebox.askyesno('覆盖确认', '将替换本次生成的同名文件，是否继续？', parent=self.root):
            return
        report_metadata = {k: v.get() for k, v in self.report_metadata.items()}
        values = self.field_values()
        ibom = dict(source=self.bom_source.get(), path=self.bom_path.get().strip(), open=False)
        if 'ibom' in selected and ibom['source'] == 'file' and not Path(ibom['path']).is_file():
            self.page.set('交互式 iBOM'); self.change_page()
            messagebox.showerror('最终 BOM', '请选择存在的最终 BOM 文件。', parent=self.root); return
        film_config = None
        if 'gerber' in selected:
            try:
                self.film_connection()
                film_config = self.gerber.export_configuration()
            except ValueError as error:
                self.page.set('Gerber / 光绘'); self.change_page()
                messagebox.showerror('Gerber 配置', str(error), parent=self.root); return
        film_names = self.gerber.selected_films()
        copper = list(self.gerber.copper)
        draft = self.gerber.snapshot()
        errors = manufacturing.validate(values) if 'instructions' in selected else []
        if errors:
            self.page.set('PCB 参数'); self.change_page()
            messagebox.showerror('请核对制造规格', '\n'.join(errors), parent=self.root); return
        self.set_busy(True); self.append('正在检查并生成生产交付文件…')
        def worker():
            try:
                gerber_board = None
                saved_draft = draft
                if film_config is not None:
                    self.events.put(('progress', '正在核对并写入 PCB Film，取得最新导出快照…'))
                    applied = self.film_connection().apply(*film_config, copper=copper)
                    gerber_board = applied['board']
                    self.events.put(('film_applied', applied))
                    from copy import deepcopy
                    applied_files = deepcopy(applied['records'])
                    for file in applied_files:
                        file['enabled'] = file['name'] in film_names
                    saved_draft = dict(draft, files=applied_files, baselineRecords=deepcopy(applied['records']), enabledExisting=film_names)
                result = delivery.run(self.args.board, self.args.source, self.args.cadence_root, fields=values, output=destination, outputs=selected, labels=getattr(self.args, 'labels', None), overwrite=replace, ibom_bom=ibom['path'] if ibom['source'] == 'file' else None, ibom_use_board=ibom['source'] != 'file', film_names=film_names, gerber_board=gerber_board, report_metadata=report_metadata, progress=lambda text: self.events.put(('progress', text)))
                try:
                    self.remember_settings(values, destination, selected, ibom, saved_draft, report_metadata=report_metadata)
                except OSError as error:
                    self.events.put(('progress', '文件已生成，但设置未能保存：'+str(error)))
                self.events.put(('done', result))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def film_connection(self):
        from .film_bridge import FilmBridge
        connection = FilmBridge(getattr(self.args, 'film_session', None), self.args.source)
        if not connection.available():
            raise ValueError('当前窗口没有 PCB 回写连接，请安装新版后从 Allegro 重新打开生产交付。')
        return connection

    def apply_gerber(self, baseline, target):
        if self.busy or self.reading:
            return
        connection = self.film_connection()
        copper = list(self.gerber.copper)
        self.set_busy(True); self.append('正在写入 PCB Film 并读回核验…')
        def worker():
            try:
                result = connection.apply(baseline, target, copper=copper)
                self.events.put(('film_done', result))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def read_metadata(self):
        try:
            metadata = board_metadata.read(self.args.board, self.args.cadence_root)
            from .gerber import read_films, read_film_records, read_layer_polarities
            try:
                sidecar = Path(str(Path(self.args.board).with_suffix('.tsv'))+'.films.tsv')
                if sidecar.is_file():
                    records, layers = read_film_records(sidecar)
                    metadata['film_records'] = records
                    metadata['films'] = [record['name'] for record in records]
                    metadata['film_layers'] = layers
                    polarities = read_layer_polarities(sidecar)
                    for layer in metadata.get('copper_layers', []):
                        if layer['name'] in polarities:
                            layer['negative'] = polarities[layer['name']]
                else:
                    metadata['films'] = read_films(self.args.board, self.args.cadence_root)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                metadata.setdefault('warnings', []).append('Film 清单读取未完成：'+str(error))
            self.events.put(('metadata', metadata))
        except Exception as error:
            self.events.put(('metadata_error', str(error)))

    def apply_metadata(self, metadata):
        from tkinter import ttk
        self.gerber.apply_metadata(metadata)
        count, prior_auto = 0, self.previous.get('autoValues', {})
        for field, variable, widget in self.entries:
            key = field['sheet']+'!'+field['ref']
            choices = list(self.gerber.outline_entry.cget('values')) if field['label'] == '板框层' else metadata.get('choices', {}).get(field['label'])
            if choices is not None and isinstance(widget, ttk.Combobox):
                options = list(choices)
                if variable.get() and variable.get() not in options:
                    options.append(variable.get())
                widget.configure(values=('',)+tuple(options))
                self.sources[key].configure(text='可从 PCB 层中选择或手动输入 Class/Subclass；请核对实际外板框。')
            found = metadata['values'].get(field['label'])
            if found is not None and field['sheet'] == 'PCB说明' and field['label'] in manufacturing.REFERENCE_ONLY:
                self.references[field['label']] = found
                self.sources[key].configure(text='PCB 设计参考：'+found+'；成品规格请另选。'); continue
            if found is not None and variable.get() == field['value'] and (not variable.get() or prior_auto.get(key) == variable.get()):
                variable.set(found); self.automatic[key] = found
                self.sources[key].configure(text=metadata.get('sources', {}).get(field['label'], 'PCB 读取')); count += 1
        self.update_preview(); self.badge.set('PCB 数据已读取')
        self.append(f'已从 PCB 带入 {count} 项；制造规格请核对。')
        for text in metadata.get('details', [])+metadata.get('warnings', []):
            self.append(text, status=False)

    def poll(self):
        from tkinter import messagebox
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind in ('metadata', 'metadata_error'):
                    self.reading = False; self.set_busy(False)
                    if kind == 'metadata':
                        self.apply_metadata(value)
                    else:
                        self.badge.set('PCB 读取未完成'); self.append('PCB 参数读取失败，可核对填写后生成。'); self.append(value, status=False)
                elif kind == 'progress':
                    self.append(value)
                elif kind in ('film_done', 'film_applied'):
                    self.gerber.accept_write(value)
                    if kind == 'film_done':
                        self.set_busy(False)
                    self.append('Film 已写入当前 PCB 并读回核验；请保存 PCB 以保留这些设置。')
                elif kind == 'done':
                    self.set_busy(False)
                    self.append('导出完成：%s 个文件。%s' % (value['files'], '存在制造警告，请展开详情。' if value['warnings'] else ''))
                    if value['warnings']:
                        self.append('制造日志：'+value['log'], status=False)
                else:
                    self.set_busy(False); self.append('导出失败：'+value)
                    messagebox.showerror('生产交付', value, parent=self.root)
        except queue.Empty:
            pass
        self.after_id = self.root.after(100, self.poll)

    def close(self):
        from tkinter import messagebox
        if self.busy or self.reading:
            messagebox.showinfo('正在处理', '请等待当前 PCB 参数读取或生成任务完成后关闭。', parent=self.root); return
        snapshot = Path(self.args.board)
        for path in (snapshot, snapshot.with_suffix('.owner.json'), snapshot.with_suffix('.tsv'), Path(str(snapshot.with_suffix('.tsv'))+'.models.tsv'), Path(str(snapshot.with_suffix('.tsv'))+'.films.tsv')):
            path.unlink(missing_ok=True)
        self.stop_polling(); self.root.destroy()

    def stop_polling(self):
        import tkinter as tk
        self.closed = True
        if self.after_id:
            try:
                self.root.after_cancel(self.after_id)
            except tk.TclError:
                pass


def show(args):
    import tkinter as tk
    root = tk.Tk()
    view = DeliveryWindow(root, args)
    root.delivery_view = view
    try:
        root.mainloop()
    finally:
        view.stop_polling()
    return 0

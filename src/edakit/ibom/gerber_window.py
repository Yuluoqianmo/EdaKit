"""Native Film tree and property editor; drafts never impersonate PCB records."""
import copy
import tkinter as tk
from tkinter import font as tkfont
import uuid
from tkinter import ttk, messagebox

from . import gerber
from .delivery_theme import MUTED


class GerberEditor(ttk.Frame):
    def __init__(self, parent, saved, status, apply_callback=None):
        super().__init__(parent)
        self.status, self.busy = status, False
        self.apply_callback = apply_callback
        self.saved_baseline = saved.get('baselineRecords')
        self.archived_draft = saved.get('previousDraft')
        self.files = copy.deepcopy(saved.get('files', [])) if saved.get('version') == 1 else []
        if not isinstance(self.files, list) or any(not isinstance(f, dict) or not all(k in f for k in ('id', 'name', 'layers', 'role')) or not isinstance(f['layers'], list) for f in self.files):
            self.files = []
        self.restore_pending = bool(self.files)
        self.copper, self.known, self.existing = [], [], None
        self.records, self.available = None, None
        self.stack_text = tk.StringVar(self, value='PCB 实际叠层：正在读取…')
        self.enabled_existing = saved.get('enabledExisting')
        self.undo, self.items, self.issues = None, {}, []
        self.mode = tk.StringVar(self, value='existing')
        self.outline = tk.StringVar(self, value=saved.get('outline', ''))
        self.columnconfigure(0, weight=1)
        self.header = ttk.LabelFrame(self, text='配置来源', padding=(10, 7))
        self.hint = ttk.Label(self, text='正在读取工程 Film 清单…', style='ED.Muted.TLabel', wraplength=700)
        self.hint.grid(row=1, column=0, sticky='ew', pady=(7, 8))
        self.bind('<Configure>', lambda e: self.hint.configure(wraplength=max(150, e.width-12)))
        config = ttk.LabelFrame(self, text='按 PCB 配置', padding=(10, 8))
        config.grid(row=2, column=0, sticky='ew'); config.columnconfigure(1, weight=1)
        ttk.Label(config, text='板框层').grid(row=0, column=0, padx=(0, 10))
        self.outline_entry = ttk.Combobox(config, textvariable=self.outline, state='normal')
        self.outline_entry.grid(row=0, column=1, sticky='ew')
        ttk.Label(config, text='支持手动输入 Class/Subclass；请选择实际外板框，CUTOUT 仅为内切口。', style='ED.Muted.TLabel', wraplength=650).grid(row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))
        actions = ttk.Frame(config); actions.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        ttk.Button(actions, text='一键设置…', command=self.configure_plan).pack(side='left')
        ttk.Button(actions, text='写入 PCB', command=self.write_pcb).pack(side='left', padx=7)
        ttk.Label(config, textvariable=self.stack_text, style='ED.Muted.TLabel', wraplength=650).grid(row=2, column=0, columnspan=2, sticky='w', pady=(8, 0))
        self.split = ttk.Frame(self); self.split.grid(row=3, column=0, sticky='nsew', pady=(12, 0))
        self.split.columnconfigure(0, weight=1)
        left = ttk.Frame(self.split); left.grid(row=0, column=0, sticky='nsew')
        left.columnconfigure(0, weight=1)
        bar = ttk.Frame(left); bar.grid(row=0, column=0, columnspan=2, sticky='ew')
        self.edit_buttons = []
        for text, command in (('新建文件', lambda: self.edit('new')), ('添加子层', lambda: self.edit('layer-new')), ('修改', lambda: self.edit('edit')), ('删除', self.delete), ('撤销', self.restore)):
            button = ttk.Button(bar, text=text, command=command, style='ED.Toolbar.TButton', width=0)
            button.pack(side='left', padx=(0, 3)); self.edit_buttons.append(button)
        self.change_summary = ttk.Label(left, text='', style='ED.Muted.TLabel', wraplength=700)
        self.change_summary.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        self.change_summary.bind('<Configure>', lambda e: self.change_summary.configure(wraplength=max(180, e.width)))
        self.tree = ttk.Treeview(left, columns=('change',), show='tree', selectmode='browse', height=16, style='ED.Film.Treeview')
        self.icons = {}
        for selected in (False, True):
            icon = tk.PhotoImage(master=self, width=38, height=18)
            icon.put('#7b8b9d', to=(1, 2, 14, 15)); icon.put('#ffffff', to=(2, 3, 13, 14))
            if selected:
                icon.put('#1673b5', to=(2, 3, 13, 14))
                for x, y in ((4, 8), (5, 9), (6, 10), (7, 9), (8, 8), (9, 7), (10, 6)):
                    icon.put('#ffffff', to=(x, y, x+2, y+2))
            icon.put('#b78e35', to=(20, 3, 29, 6)); icon.put('#f7d370', to=(21, 4, 28, 7))
            icon.put('#b78e35', to=(19, 6, 36, 16)); icon.put('#f7d370', to=(20, 7, 35, 15))
            self.icons[selected] = icon
        self.layer_icon = tk.PhotoImage(master=self, width=14, height=14)
        for y in range(4, 11):
            radius = 3-abs(7-y)
            self.layer_icon.put('#b44c83', to=(7-radius, y, 8+radius, y+1))
        self.tree.heading('#0', text='层文件 / Class / Subclass')
        self.tree.tag_configure('added', foreground='#176b37', background='#edf8ef')
        self.tree.tag_configure('changed', foreground='#955600')
        self.deleted_font = tkfont.nametofont('TkDefaultFont').copy()
        self.deleted_font.configure(overstrike=True)
        self.tree.tag_configure('removed', foreground='#a12626', background='#fff0ef', font=self.deleted_font)
        self.tree.column('#0', width=400, minwidth=200, stretch=True)
        self.tree.column('change', width=84, minwidth=84, stretch=False)
        self.tree.grid(row=2, column=0, sticky='nsew', pady=(6, 0))
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        scroll.grid(row=2, column=1, sticky='ns', pady=(6, 0)); self.tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(left, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=3, column=0, sticky='ew'); self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', self.show_properties)
        self.tree.bind('<Double-1>', self.double_click)
        self.tree.bind('<space>', self.toggle)
        self.tree.bind('<Button-1>', self.click_output, add='+')
        self.properties = ttk.LabelFrame(self.split, text='文件属性', padding=(10, 8))
        self.properties.grid(row=2, column=0, sticky='ew', pady=(10, 0))
        self.properties.columnconfigure(0, weight=1)
        self.property_text = ttk.Label(self.properties, text='选择层文件或子层查看属性。', justify='left', wraplength=260)
        self.property_text.grid(row=0, column=0, sticky='new')
        self.property_table = ttk.Frame(self.properties)
        self.property_table.grid(row=1, column=0, sticky='ew', pady=(6, 0))
        self.property_table.columnconfigure(1, weight=1)
        self.properties.bind('<Configure>', lambda e: self.property_text.configure(wraplength=max(100, e.width-24)))
        self.toggle_button = ttk.Button(self.properties, text='切换是否输出', command=self.toggle)
        self.toggle_button.grid(row=2, column=0, sticky='w', pady=(8, 0))
        ttk.Label(self.split, text='▸ 展开 / 收起文件夹   ◆ PCB 子层   ☑ 输出此文件（单击图标或按空格切换）', style='ED.Muted.TLabel', wraplength=700).grid(row=1, column=0, sticky='w', pady=6)
        self.review_frame = ttk.LabelFrame(self, text='层映射核对结果', padding=8)
        self.review_tree = ttk.Treeview(self.review_frame, columns=('level',), show='tree headings', height=5)
        self.review_tree.heading('#0', text='检查结果（双击定位）'); self.review_tree.heading('level', text='类型')
        self.review_tree.column('#0', width=470); self.review_tree.column('level', width=80, stretch=False)
        self.review_tree.pack(fill='x'); self.review_tree.bind('<Double-1>', self.locate)
        self.refresh()

    def snapshot(self):
        return dict(version=1, files=copy.deepcopy(self.files), outline=self.outline.get(), enabledExisting=self.enabled_existing,
                    baselineRecords=copy.deepcopy(self.records), previousDraft=copy.deepcopy(self.archived_draft))

    def selected_films(self):
        if self.mode.get() == 'draft':
            return [f['name'] for f in self.files if f.get('enabled', True)]
        return None if self.existing is None else [name for name in self.existing if name in self.enabled_existing]

    def change_mode(self):
        if self.mode.get() == 'draft' and not self.files and self.records is not None:
            self.files = copy.deepcopy(self.records)
            for file in self.files:
                file['enabled'] = file['name'] in (self.enabled_existing or [])
        self.refresh()

    def begin_edit(self):
        """Copy the selected native item into the pending tree on first edit."""
        if self.busy or self.records is None:
            return False
        if self.mode.get() == 'existing':
            selection = self.tree.selection()
            file, index = self.items.get(selection[0], (None, None)) if selection else (None, None)
            self.files = copy.deepcopy(self.records)
            for item in self.files:
                item['enabled'] = item['name'] in (self.enabled_existing or [])
            self.mode.set('draft'); self.refresh()
            if file:
                iid = file['id'] + (':layer:'+str(index) if index is not None else '')
                if self.tree.exists(iid):
                    self.tree.selection_set(iid); self.tree.see(iid)
        return True

    def export_configuration(self):
        if self.records is None or self.available is None:
            raise ValueError('尚未读取 PCB 真实 Film 映射，请从 Allegro 重新打开生产交付。')
        expected = gerber.recommended(self.copper, self.outline.get(), self.available)
        records = gerber.identify_records(self.files if self.mode.get() == 'draft' else self.records, expected)
        if self.mode.get() == 'existing':
            for file in records:
                file['enabled'] = file['name'] in (self.enabled_existing or [])
        # Validate even disabled Film definitions: they are written back too.
        for file in records:
            if not file['layers'] or any(layer not in self.available for layer in file['layers']):
                raise ValueError('Film 包含空映射或 PCB 中不存在的子层：'+file['name'])
        self.issues = gerber.review(records, self.copper, self.outline.get(), self.available, full_inventory=True)
        self.show_review()
        errors = [issue['text'] for issue in self.issues if issue['level'] == '错误']
        if errors:
            raise ValueError('\n'.join(errors))
        return copy.deepcopy(self.records), records

    def write_pcb(self):
        if self.busy:
            return
        try:
            baseline, target = self.export_configuration()
            if self.apply_callback is None:
                raise ValueError('当前窗口没有 PCB 回写连接，请从新版 Allegro 插件入口重新打开。')
            self.apply_callback(baseline, target)
        except ValueError as error:
            messagebox.showerror('写入 PCB', str(error), parent=self)

    def accept_write(self, result):
        selected = {file['name'] for file in result['target'] if file.get('enabled', True)}
        # Readback IDs are tied to current native names, including renamed Films.
        self.apply_metadata(dict(film_records=result['records'], film_layers=result['known'],
                                 films=[file['name'] for file in result['records']]))
        self.enabled_existing = [file['name'] for file in result['records'] if file['name'] in selected]
        self.files = copy.deepcopy(result['records'])
        for file in self.files:
            file['enabled'] = file['name'] in selected
        self.undo = None; self.mode.set('existing'); self.refresh()
        self.status('Film 已写入当前 PCB 并读回核验；保存 PCB 后可持久保留。')

    def apply_metadata(self, metadata):
        if 'copper_layers' in metadata:
            self.copper = metadata['copper_layers']
        if 'film_layers' in metadata:
            self.available = metadata['film_layers']
        self.known = self.available if self.available is not None else metadata.get('geometry_layers', self.known)
        if 'film_records' in metadata:
            if self.restore_pending:
                from .film_bridge import signature
                try:
                    same = self.saved_baseline is not None and signature(self.saved_baseline) == signature(metadata['film_records'])
                except (KeyError, TypeError, ValueError):
                    same = False
                if not same:
                    self.archived_draft = copy.deepcopy(self.files)
                    self.files = []
                    self.status('PCB Film 与上次草稿基线不同，编辑区将使用当前 PCB；旧草稿已归档到设置。')
                else:
                    self.mode.set('draft')
                self.restore_pending = False
            self.records = copy.deepcopy(metadata['film_records'])
        self.stack_text.set('PCB 实际叠层：'+str(len(self.copper))+' 层  ·  '+' → '.join(c['name'] for c in self.copper) if self.copper else 'PCB 实际叠层尚未读取，不能一键配置。')
        detected = gerber.outline_choices(metadata.get('choices', {}).get('板框层', []))
        candidates = gerber.outline_choices(detected, self.known, self.records or [])
        self.outline_entry.configure(values=candidates)
        if not self.outline.get() or self.outline.get().upper().endswith('/CUTOUT'):
            self.outline.set(gerber.preferred_outline(detected) or gerber.preferred_outline(candidates))
        if 'films' in metadata:
            self.existing = sorted(metadata['films'], key=gerber.film_sort_key)
            if self.enabled_existing is None:
                self.enabled_existing = list(self.existing)
            else:
                self.enabled_existing = [name for name in self.enabled_existing if name in self.existing]
        self.refresh()

    def refresh(self):
        opened = {iid for iid in self.tree.get_children() if self.tree.item(iid, 'open')}
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children()); self.items = {}
        self.removed_items = {}
        draft = self.mode.get() == 'draft'
        current = self.files if draft else (self.records or [])
        changes = gerber.film_changes(self.records or [], current)
        self.changes = changes
        by_id = {change['id']: change for change in changes}
        counts = {kind: sum(change['kind'] == kind for change in changes) for kind in ('新增', '修改', '删除')}
        self.change_summary.configure(text=('待写入 PCB：'+'  ·  '.join(f'{kind} {count}' for kind, count in counts.items())+'。＋ 新增  ·  − 删除（原位保留，可恢复）  ·  ~ 修改（原值 → 新值）') if changes else '与 PCB Film 一致；增删改后将显示变更标记。勾选仅控制本次输出。')
        if draft:
            self.hint.configure(text='增删改直接在原树对比；确认后点击“写入 PCB”。生成交付包时也会自动核对并写入。')
            baseline = {file['id']: file for file in self.records or []}
            pending = {file['id']: file for file in self.files}
            display = dict(baseline); display.update(pending)
            for fid in sorted(display, key=lambda fid: gerber.film_sort_key(baseline.get(fid, display[fid])['name'])):
                file = display[fid]
                fid = file['id']
                change = by_id.get(fid)
                deleted = fid not in pending
                tag = 'removed' if deleted else 'added' if fid not in baseline else 'changed' if change else ''
                prefix = {'removed': '− ', 'added': '＋ ', 'changed': '~ '}.get(tag, '')
                old = baseline.get(fid)
                name = old['name']+' → '+file['name'] if old and old['name'] != file['name'] else file['name']
                self.tree.insert('', 'end', iid=fid, text=prefix+name, tags=(tag,) if tag else (), image=self.icons[False if deleted else file.get('enabled', True)], values=('待删除' if deleted else '新增' if tag == 'added' else '已修改' if change else '',), open=fid in opened)
                self.items[fid] = (file, None)
                if deleted:
                    self.removed_items[fid] = (file, None)
                for row in gerber.inline_layer_rows(old['layers'] if old else [], [] if deleted else file['layers']):
                    index, removed, added = row['index'], row['removed'], row['added']
                    iid = fid+(':removed:' if removed else ':layer:')+str(index)
                    source = old if removed else file
                    tag = 'removed' if removed else 'added' if added else ''
                    self.tree.insert(fid, 'end', iid=iid, text=('− ' if removed else '＋ ' if added else '')+row['layer'], tags=(tag,) if tag else (), image=self.layer_icon, values=('待删除' if removed else '新增' if added else '',))
                    self.items[iid] = (source, index)
                    if removed:
                        self.removed_items[iid] = (source, index)
        else:
            self.hint.configure(text=(f'工程已有 {len(self.existing)} 个 Film；内部层映射已读取，勾选直接控制本次导出。' if self.records is not None else f'工程已有 {len(self.existing)} 个 Film；仅有名称，请更新插件并从 Allegro 重新打开以读取内部映射。') if self.existing is not None else 'Film 清单未读取完成。')
            for index, name in enumerate(self.existing or []):
                iid = 'existing-'+str(index)
                self.tree.insert('', 'end', iid=iid, text=name, image=self.icons[name in self.enabled_existing], values=('☑' if name in self.enabled_existing else '☐',))
                record = next((f for f in self.records or [] if f['name'] == name), dict(name=name))
                self.items[iid] = (record, None)
                for layer_index, layer in enumerate(record.get('layers', [])):
                    child = iid+':layer:'+str(layer_index)
                    self.tree.insert(iid, 'end', iid=child, text=layer, image=self.layer_icon)
                    self.items[child] = (record, layer_index)
                self.tree.item(iid, open=iid in opened)
        for button in self.edit_buttons:
            button.configure(state='normal' if self.records is not None and not self.busy else 'disabled')
        self.edit_buttons[-1].configure(state='normal' if draft and self.undo is not None and not self.busy else 'disabled')
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self.show_properties()

    def show_properties(self, event=None):
        for child in self.property_table.winfo_children():
            child.destroy()
        selected = self.tree.selection()
        removed = bool(selected and selected[0] in getattr(self, 'removed_items', {}))
        self.edit_buttons[3].configure(text='恢复' if removed else '删除')
        for button in self.edit_buttons[1:3]:
            button.configure(state='disabled' if removed or self.busy or self.records is None else 'normal')
        self.toggle_button.configure(state='disabled' if removed or self.busy else 'normal')
        if not selected or selected[0] not in self.items:
            self.property_text.configure(text='选择层文件或子层查看属性。'); return
        file, index = self.items[selected[0]]
        self.property_text.configure(text='选择子层可查看完整 Class / Subclass。' if index is None else '当前子层：'+file['layers'][index])
        changed = next((change for change in getattr(self, 'changes', []) if change['id'] == file.get('id')), None)
        pairs = [('输出文件', file['name']+'.art'), ('变更状态', changed['kind']+' · 尚未写入 PCB' if changed else '与 PCB 一致'),
                 ('包含子层', str(len(file['layers']))+' 项' if 'layers' in file else '尚未读取'),
                 ('图形极性', ('负片' if file.get('negative') else '正片') if 'negative' in file else '尚未读取'),
                 ('镜像输出', ('是' if file.get('mirror') else '否') if 'mirror' in file else '尚未读取')]
        if removed:
            pairs[1] = ('变更状态', '待删除 · 原位保留，可点击“恢复”')
        if changed and changed['old'] and changed['new']:
            old, new = changed['old'], changed['new']
            for position, key, label, formatter in (
                (0, 'name', '输出文件', lambda v: v+'.art'),
                (3, 'negative', '图形极性', lambda v: '负片' if v else '正片'),
                (4, 'mirror', '镜像输出', lambda v: '是' if v else '否')):
                if old.get(key) != new.get(key):
                    pairs[position] = (label, formatter(old.get(key))+' → '+formatter(new.get(key)))
        for row, (label, value) in enumerate(pairs):
            ttk.Label(self.property_table, text=label, style='ED.PropertyName.TLabel').grid(row=row, column=0, sticky='ew', padx=(0, 1), pady=(0, 1))
            ttk.Label(self.property_table, text=value, style='ED.PropertyValue.TLabel', wraplength=600).grid(row=row, column=1, sticky='ew', pady=(0, 1))

    def click_output(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and self.tree.identify_element(event.x, event.y) == 'image' and not self.tree.parent(iid):
            self.tree.selection_set(iid)
            return self.toggle()

    def toggle(self, event=None):
        if self.busy:
            return 'break'
        selected = self.tree.selection()
        if selected and selected[0] in self.removed_items:
            return 'break'
        if selected:
            file, _ = self.items[selected[0]]
            if self.mode.get() == 'draft':
                self.undo = copy.deepcopy(self.files); file['enabled'] = not file.get('enabled', True)
            else:
                name = file['name']
                if name in self.enabled_existing:
                    self.enabled_existing.remove(name)
                else:
                    self.enabled_existing.append(name)
            self.refresh(); self.review_frame.grid_remove()
        return 'break'

    def double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        if self.tree.identify_element(event.x, event.y) in ('image', 'Treeitem.indicator'):
            return
        self.edit('edit')

    def configure_plan(self):
        if self.busy:
            return
        try:
            if self.records is None or self.available is None:
                raise ValueError('尚未读取工程真实 Film 映射。请更新插件后，从 Allegro 的生产交付入口重新打开。')
            expected = gerber.recommended(self.copper, self.outline.get(), self.available)
            actual = gerber.identify_records(self.records, expected)
            base = gerber.identify_records(self.files, expected) if self.mode.get() == 'draft' else actual
        except ValueError as error:
            messagebox.showerror('一键配置', str(error), parent=self); return
        dialog = tk.Toplevel(self); dialog.title('一键配置 · 差异预览'); dialog.transient(self.winfo_toplevel())
        dialog.geometry('680x430'); dialog.minsize(480, 320)
        body = ttk.Frame(dialog, padding=12); body.pack(fill='both', expand=True)
        mode = tk.BooleanVar(dialog, value=False)
        text = tk.Text(body, height=13, wrap='word', font=('Microsoft YaHei UI', 10))
        plan = []
        def preview():
            try:
                plan[:] = gerber.merge(actual if mode.get() else base, expected)
            except ValueError as error:
                text.configure(state='normal'); text.delete('1.0', 'end'); text.insert('1.0', str(error)); text.configure(state='disabled')
                plan.clear(); return
            _, added, fixed, kept = plan
            value = self.stack_text.get()+f'\n新增 {len(added)} 个，补齐 {len(fixed)} 个，保留 {len(kept)} 个手工文件\n已有 Film 名称、子层、极性和镜像设置保留。\n'
            for title, items in (('新增', added), ('补齐', fixed), ('保留手工修改', kept)):
                value += '\n'+title+'\n'+('\n'.join(items) or '无')+'\n'
            value += '\n'+('重新从工程已有 Film 开始。' if mode.get() else '在当前配置上补齐。')+'\n确认后核对映射、写入当前 PCB，并读回验证；不会自动保存源 .brd。'
            text.configure(state='normal'); text.delete('1.0', 'end'); text.insert('1.0', value); text.configure(state='disabled')
        for value, title in ((False, '补齐缺失，保留当前修改'), (True, '重新从工程 Film 开始')):
            ttk.Radiobutton(body, text=title, variable=mode, value=value, command=preview).pack(anchor='w')
        text.pack(fill='both', expand=True, pady=10)
        def apply():
            if not plan:
                return
            self.undo = copy.deepcopy(self.files); self.files = plan[0]; self.mode.set('draft'); self.refresh()
            self.review_frame.grid_remove(); dialog.destroy(); self.write_pcb()
        buttons = ttk.Frame(body); buttons.pack(fill='x')
        ttk.Button(buttons, text='设置并写入 PCB', command=apply).pack(side='right')
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right', padx=8)
        preview(); dialog.grab_set()

    def edit(self, kind):
        if not self.begin_edit():
            return
        selection = self.tree.selection()
        if kind != 'new' and selection and selection[0] in self.removed_items:
            return
        file, index = self.items.get(selection[0], (None, None)) if selection else (None, None)
        if kind != 'new' and file is None:
            return
        layer_mode = kind == 'layer-new' or kind == 'edit' and index is not None
        dialog = tk.Toplevel(self); dialog.title('子层设置' if layer_mode else '层文件设置'); dialog.transient(self.winfo_toplevel())
        dialog.geometry('520x340'); dialog.minsize(430, 300)
        body = ttk.Frame(dialog, padding=14); body.pack(fill='both', expand=True); body.columnconfigure(1, weight=1)
        name = tk.StringVar(dialog, value=file['layers'][index] if layer_mode and kind == 'edit' else '' if layer_mode else file['name'] if file and kind != 'new' else 'CUSTOM')
        role = tk.StringVar(dialog, value=gerber.ROLES.get(file['role'], '自定义') if file else '自定义')
        negative = tk.BooleanVar(dialog, value=file.get('negative', False) if file else False)
        mirror = tk.BooleanVar(dialog, value=file.get('mirror', False) if file else False)
        ttk.Label(body, text='Class / Subclass' if layer_mode else '文件名（不含 .art）').grid(row=0, column=0, sticky='w', padx=(0, 8))
        candidates = list(dict.fromkeys(self.known + [group+'/'+c['name'] for c in self.copper for group in ('ETCH', 'PIN', 'VIA CLASS')]))
        entry = ttk.Combobox(body, textvariable=name, values=candidates) if layer_mode else ttk.Entry(body, textvariable=name)
        entry.grid(row=0, column=1, sticky='ew')
        if not layer_mode:
            ttk.Label(body, text='文件用途').grid(row=1, column=0, sticky='w', pady=12)
            ttk.Combobox(body, textvariable=role, values=list(gerber.ROLES.values()), state='readonly').grid(row=1, column=1, sticky='ew')
            ttk.Checkbutton(body, text='负片', variable=negative).grid(row=2, column=1, sticky='w')
            ttk.Checkbutton(body, text='镜像输出', variable=mirror).grid(row=3, column=1, sticky='w')
        else:
            ttk.Label(body, text='可选择已读取的图形层或输入完整层名；焊盘/过孔层存在性需核对。', foreground=MUTED, wraplength=440).grid(row=1, column=0, columnspan=2, sticky='w', pady=12)
        error = tk.StringVar(dialog)
        ttk.Label(body, textvariable=error, foreground='#9e2e28', wraplength=440).grid(row=4, column=0, columnspan=2, sticky='w', pady=8)
        def save():
            value = name.get().strip()
            if not layer_mode and value.lower().endswith('.art'):
                value = value[:-4]
            if layer_mode:
                if '/' not in value or any(not p.strip() for p in value.split('/', 1)):
                    error.set('请输入完整 Class / Subclass。'); return
                if any(layer == value and (kind != 'edit' or i != index) for i, layer in enumerate(file['layers'])):
                    error.set('该文件已包含此子层。'); return
            elif not gerber.valid_name(value) or any(f['name'].casefold() == value.casefold() and (kind == 'new' or f is not file) for f in self.files):
                error.set('文件名无效或已存在。'); return
            self.undo = copy.deepcopy(self.files)
            if layer_mode:
                if kind == 'layer-new':
                    file['layers'].append(value)
                else:
                    file['layers'][index] = value
                file['modified'] = True
            elif kind == 'new':
                self.files.append(dict(id='manual-'+uuid.uuid4().hex, name=value, role=next(k for k, v in gerber.ROLES.items() if v == role.get()), layers=[], enabled=True, negative=negative.get(), mirror=mirror.get(), modified=True))
            else:
                file.update(name=value, role=next(k for k, v in gerber.ROLES.items() if v == role.get()), negative=negative.get(), mirror=mirror.get(), modified=True)
            self.refresh(); self.review_frame.grid_remove(); dialog.destroy()
        buttons = ttk.Frame(body); buttons.grid(row=5, column=0, columnspan=2, sticky='e', pady=10)
        ttk.Button(buttons, text='取消', command=dialog.destroy).pack(side='right')
        ttk.Button(buttons, text='保存', command=save).pack(side='right', padx=8)
        dialog.bind('<Return>', lambda e: save()); dialog.bind('<Escape>', lambda e: dialog.destroy())
        entry.focus_set(); dialog.grab_set()

    def delete(self):
        if not self.begin_edit() or not self.tree.selection():
            return
        iid = self.tree.selection()[0]
        file, index = self.items[iid]
        if iid in self.removed_items:
            self.undo = copy.deepcopy(self.files)
            current = next((f for f in self.files if f['id'] == file['id']), None)
            if current is None:
                self.files.append(copy.deepcopy(file))
            elif index is not None and file['layers'][index] not in current['layers']:
                # Insert beside the nearest surviving successor from the baseline.
                successor = next((layer for layer in file['layers'][index+1:] if layer in current['layers']), None)
                position = current['layers'].index(successor) if successor else len(current['layers'])
                current['layers'].insert(position, file['layers'][index])
            self.refresh(); self.review_frame.grid_remove()
            return
        label = file['name']+'.art' if index is None else file['layers'][index]
        if not messagebox.askyesno('删除配置项', '从草稿中删除 '+label+'？', parent=self):
            return
        self.undo = copy.deepcopy(self.files)
        if index is None:
            self.files.remove(file)
        else:
            file['layers'].pop(index); file['modified'] = True
        self.refresh(); self.review_frame.grid_remove()

    def restore(self):
        if self.undo is not None and not self.busy:
            self.files, self.undo = self.undo, None; self.refresh(); self.review_frame.grid_remove()

    def run_review(self):
        if self.mode.get() == 'existing':
            if self.records is not None and self.available is not None:
                try:
                    expected = gerber.recommended(self.copper, self.outline.get(), self.available)
                    records = gerber.identify_records(self.records, expected)
                    for file in records:
                        file['enabled'] = file['name'] in self.enabled_existing
                    self.issues = gerber.review(records, self.copper, self.outline.get(), self.available, full_inventory=True)
                except ValueError as error:
                    self.issues = [dict(level='人工核对', text=str(error))]
            else:
                self.issues = [dict(level='人工核对', text='仅读取了 Film 名称；请重新从 Allegro 打开生产交付以读取真实映射。')]
            if self.existing is not None and not self.selected_films():
                self.issues.insert(0, dict(level='错误', text='未勾选任何工程 Film。'))
        else:
            self.issues = gerber.review(self.files, self.copper, self.outline.get(), self.known, full_inventory=self.available is not None)
        self.show_review()
        return self.issues

    def show_review(self):
        self.review_tree.delete(*self.review_tree.get_children())
        for i, issue in enumerate(self.issues):
            self.review_tree.insert('', 'end', iid=str(i), text=issue['text'], values=(issue['level'],))
        self.review_frame.grid(row=5, column=0, sticky='ew', pady=(6, 0))

    def locate(self, event=None):
        selection = self.review_tree.selection()
        if not selection:
            return
        issue = self.issues[int(selection[0])]
        iid = issue.get('file')
        if iid and not self.tree.exists(iid):
            iid = next((key for key, (file, index) in self.items.items() if index is None and file.get('id') == iid), None)
        if iid and self.tree.exists(iid):
            self.tree.item(iid, open=True)
            if issue.get('index') is not None:
                iid += ':layer:'+str(issue['index'])
            self.tree.selection_set(iid); self.tree.see(iid); self.show_properties()

    def set_busy(self, busy):
        self.busy = busy
        def update(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, (ttk.Button, ttk.Radiobutton)):
                    widget.configure(state='disabled' if busy else 'normal')
                elif isinstance(widget, ttk.Combobox):
                    widget.configure(state='disabled' if busy else 'normal' if widget is self.outline_entry else 'readonly')
                update(widget)
        update(self); self.refresh()

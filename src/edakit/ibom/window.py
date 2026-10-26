"""Independent export window; owns a persistent copy of Allegro's temporary snapshot."""
import os
import json
import queue
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from ..config import app_dir
from . import exporter


def launch(args):
    from .retention import cleanup
    cleanup(app_dir() / 'ibom')
    folder = app_dir() / 'ibom' / 'snapshots'
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / (uuid.uuid4().hex + '.brd')
    from ..storage import atomic_write
    process = None
    try:
        atomic_write(snapshot.with_suffix('.owner.json'), json.dumps({'pid': os.getpid()}))
        shutil.copy2(args.board, snapshot)
        labels = getattr(args, 'labels', None)
        if labels:
            shutil.copy2(labels, snapshot.with_suffix('.tsv'))
            models = Path(str(labels) + '.models.tsv')
            if models.is_file():
                shutil.copy2(models, Path(str(snapshot.with_suffix('.tsv')) + '.models.tsv'))
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command += ['-m', 'edakit']
        command += ['ibom-export', '--dialog-worker', '--board', str(snapshot), '--source', str(args.source), '--cadence-root', str(args.cadence_root or '')]
        if labels:
            command += ['--labels', str(snapshot.with_suffix('.tsv'))]
        process = subprocess.Popen(command, env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'),
                         creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0,
                         close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        # No child owns these files unless Popen has returned successfully.
        for path in (snapshot.with_suffix('.owner.json'), snapshot,
                     snapshot.with_suffix('.tsv'), Path(str(snapshot.with_suffix('.tsv')) + '.models.tsv')):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    try:
        atomic_write(snapshot.with_suffix('.owner.json'), json.dumps({'pid': process.pid}))
    except OSError:
        # A running worker must retain its inputs. An unreadable lease prevents
        # retention cleanup until the worker closes and removes its snapshot.
        try:
            snapshot.with_suffix('.owner.json').write_text('{}', encoding='utf-8')
        except OSError:
            try:
                os.utime(snapshot, None)
            except OSError:
                pass
    return 0


def show(args):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title('EdaKit · 交互式 BOM')
    root.geometry('760x610')
    root.minsize(640, 570)
    style = ttk.Style(root)
    style.configure('TLabel', font=('Microsoft YaHei UI', 10))
    style.configure('TButton', padding=(10, 5))
    cfg = exporter.settings()
    source = Path(args.source)
    existing = cfg.get('bomByBoard', {}).get(exporter.board_key(source), '')
    output = tk.StringVar(value=cfg.get('outputFolder') or str(source.parent / 'Output_Files' / 'iBOM'))
    bom = tk.StringVar(value=existing)
    native = tk.BooleanVar(value=not bool(existing))
    status = tk.StringVar(value='就绪。点击导出后显示实际处理阶段。')
    opened = tk.BooleanVar(value=True)
    events = queue.Queue()
    busy = False
    result_path = ''
    main = ttk.Frame(root, padding=20)
    main.pack(fill='both', expand=True)
    main.columnconfigure(0, weight=1)
    ttk.Label(main, text='交互式 BOM 导出', font=('Microsoft YaHei UI', 15, 'bold')).grid(row=0, column=0, sticky='w')
    ttk.Label(main, text=source.name).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 12))
    ttk.Label(main, text='输出目录').grid(row=2, column=0, sticky='w')
    out_entry = ttk.Entry(main, textvariable=output)
    out_entry.grid(row=3, column=0, sticky='ew', pady=(5, 14))
    def pick_folder():
        path = filedialog.askdirectory(parent=root, initialdir=output.get() if Path(output.get()).is_dir() else str(source.parent), title='选择输出目录')
        if path:
            output.set(path)
    folder_btn = ttk.Button(main, text='选择目录', command=pick_folder)
    folder_btn.grid(row=3, column=1, padx=(10, 0), pady=(5, 14))
    def update_mode():
        state = 'disabled' if native.get() else 'normal'
        bom_entry.configure(state=state)
        bom_btn.configure(state=state)
    native_check = ttk.Checkbutton(main, text='使用板内器件信息', variable=native, command=update_mode)
    native_check.grid(row=4, column=0, sticky='w')
    ttk.Label(main, text='取消勾选可使用最终 BOM 表，按位号关联物料编码等信息。').grid(row=5, column=0, columnspan=2, sticky='w', pady=(6, 8))
    bom_entry = ttk.Entry(main, textvariable=bom)
    bom_entry.grid(row=6, column=0, sticky='ew')
    def pick_bom():
        path = filedialog.askopenfilename(parent=root, title='选择最终 BOM', filetypes=[('BOM 表格', '*.xlsx *.csv *.tsv *.txt'), ('所有文件', '*.*')])
        if path:
            bom.set(path)
    bom_btn = ttk.Button(main, text='选择 BOM', command=pick_bom)
    bom_btn.grid(row=6, column=1, padx=(10, 0))
    open_check = ttk.Checkbutton(main, text='完成后打开交互式 BOM', variable=opened)
    open_check.grid(row=7, column=0, sticky='w', pady=(14, 10))
    status_label = ttk.Label(main, textvariable=status, wraplength=650)
    status_label.grid(row=8, column=0, columnspan=2, sticky='w', pady=(6, 6))
    main.bind('<Configure>', lambda event: status_label.configure(wraplength=max(240, event.width-40)))
    bar = ttk.Progressbar(main, mode='indeterminate')
    bar.grid(row=9, column=0, columnspan=2, sticky='ew')
    log_frame = ttk.Frame(main)
    log_frame.grid(row=10, column=0, columnspan=2, sticky='nsew', pady=10)
    log_frame.rowconfigure(0, weight=1)
    log_frame.columnconfigure(0, weight=1)
    log = tk.Text(log_frame, height=6, wrap='word', padx=6, pady=6, font=('Microsoft YaHei UI', 9), state='disabled', relief='flat', bg='#f2f5f8')
    log.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(log_frame, orient='vertical', command=log.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    log.configure(yscrollcommand=scroll.set)
    main.rowconfigure(10, weight=1, minsize=110)
    controls = [out_entry, folder_btn, native_check, bom_entry, bom_btn, open_check]
    def append(message):
        if not message.startswith('文件：'):
            status.set(message)
        log.configure(state='normal'); log.insert('end', message+'\n'); log.see('end-1c'); log.configure(state='disabled')
    def finish(success=False):
        nonlocal busy
        busy = False
        bar.stop()
        bar.configure(mode='determinate', value=100 if success else 0)
        for control in controls:
            control.configure(state='normal')
        update_mode()
        export_btn.configure(state='normal')
    def start():
        nonlocal busy
        if busy:
            return
        if not Path(output.get()).is_absolute():
            messagebox.showerror('输出目录', '请选择完整的输出目录。', parent=root); return
        if not native.get() and not Path(bom.get()).is_file():
            messagebox.showerror('BOM 表格', '请选择有效的最终 BOM 表格。', parent=root); return
        use_native, output_path, bom_path, auto_open = native.get(), output.get(), bom.get(), opened.get()
        busy = True
        for control in controls:
            control.configure(state='disabled')
        export_btn.configure(state='disabled')
        bar.configure(mode='indeterminate', value=0)
        bar.start(12)
        append('开始导出：'+source.name)
        def worker():
            try:
                receipt = exporter.generate(args.board, source=args.source, output=output_path,
                    bom=bom_path if not use_native else None, use_board=use_native,
                    cadence_root=args.cadence_root, open_result=auto_open,
                    progress=lambda message: events.put(('stage', message)), labels=getattr(args, 'labels', None))
                fresh = exporter.settings()
                fresh['outputFolder'] = output_path
                boards = fresh.setdefault('bomByBoard', {})
                if use_native:
                    boards.pop(exporter.board_key(source), None)
                else:
                    boards[exporter.board_key(source)] = bom_path
                exporter.settings(fresh)
                events.put(('done', receipt))
            except Exception as error:
                events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()
    export_btn = ttk.Button(main, text='导出', command=start)
    export_btn.grid(row=11, column=1, sticky='e')
    def poll():
        nonlocal result_path
        try:
            while True:
                kind, value = events.get_nowait()
                if kind == 'stage':
                    append(value)
                elif kind == 'done':
                    finish(True); result_path = value['html']; append('文件：'+result_path)
                else:
                    finish(); append('导出失败：'+value)
                    messagebox.showerror('导出失败', value, parent=root)
        except queue.Empty:
            pass
        root.after(100, poll)
    def close():
        if busy:
            messagebox.showinfo('正在导出', '请等待当前导出完成后关闭窗口。', parent=root)
            return
        Path(args.board).with_suffix('.owner.json').unlink(missing_ok=True)
        Path(args.board).unlink(missing_ok=True)
        Path(args.board).with_suffix('.tsv').unlink(missing_ok=True)
        Path(str(Path(args.board).with_suffix('.tsv')) + '.models.tsv').unlink(missing_ok=True)
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', close)
    update_mode()
    root.after(100, poll)
    root.mainloop()
    return 0

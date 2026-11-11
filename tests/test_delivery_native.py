import json
import tkinter as tk
from types import SimpleNamespace

from edakit.ibom import delivery_window as w


def test_bom_mode_shortcut_and_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(w.delivery.exporter, 'settings', lambda: {'bomByBoard': {w.delivery.exporter.board_key(tmp_path/'pcb.brd'): str(tmp_path/'legacy.csv')}})
    args = SimpleNamespace(source=str(tmp_path/'pcb.brd'), board=str(tmp_path/'copy.brd'), ibom_only=True)
    root = tk.Tk(); view = w.DeliveryWindow(root, args)
    try:
        root.update()
        assert not {'设计人员电话', '其他'}.intersection(f['label'] for f, _, _ in view.entries)
        view.apply_metadata({'values': {}, 'choices': {'板框层': ['BOARD GEOMETRY/CUTOUT']},
                             'film_layers': ['BOARD GEOMETRY/OUTLINE', 'BOARD GEOMETRY/DESIGN_OUTLINE', 'BOARD GEOMETRY/CUTOUT']})
        outline_field = next(widget for f, _, widget in view.entries if f['label'] == '板框层')
        assert 'BOARD GEOMETRY/OUTLINE' in outline_field.cget('values')
        outline_field.set('BOARD GEOMETRY/OUTLINE')
        assert view.gerber.outline.get() == 'BOARD GEOMETRY/OUTLINE'
        view.gerber.outline_entry.set('BOARD GEOMETRY/DESIGN_OUTLINE')
        assert outline_field.get() == 'BOARD GEOMETRY/DESIGN_OUTLINE'
        view.set_busy(True); view.set_busy(False)
        assert not outline_field.instate(['disabled', 'readonly'])
        button, body = view.collapsibles['coordinate-cover']
        assert not body.winfo_manager()
        wrapper = button.master
        siblings = wrapper.master.pack_slaves()
        before = siblings[siblings.index(wrapper)-1]
        assert isinstance(before, w.OutputCard)
        button.invoke(); root.update()
        assert body.winfo_manager() == 'pack'
        view.report_metadata['author'].set('折叠保留')
        button.invoke(); root.update()
        assert not body.winfo_manager()
        assert view.report_metadata['author'].get() == '折叠保留'
        assert view.page.get() == '交互式 iBOM'
        assert [k for k, v in view.selected_outputs.items() if v.get()] == ['ibom']
        assert view.bom_source.get() == 'file' and view.bom_path.get().endswith('legacy.csv')
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        texts = [str(child.cget('text')) for child in descendants(view.pages['交互式 iBOM'].form) if 'text' in child.keys()]
        assert not any('导出完成后打开' in text or '仅选择 iBOM' in text or '本次只需要' in text for text in texts)
        view.bom_source.set('pcb'); view.update_bom_source()
        assert view.bom_entry.instate(['disabled'])
        view.reading = False; view.set_busy(True); view.set_busy(False)
        assert view.bom_entry.instate(['disabled'])
        view.bom_source.set('file'); view.update_bom_source()
        assert not view.bom_entry.instate(['disabled'])
        view.bom_path.set(str(tmp_path/'final.xlsx'))
        view.report_metadata['author'].set('坐标编制测试')
        view.report_metadata['version'].set('A/1')
        view.save_settings()
        saved = json.loads(view.config.read_text(encoding='utf8'))
        record = saved['boards'][w.delivery.exporter.board_key(tmp_path/'pcb.brd')]
        assert record['reportMetadata']['author'] == '坐标编制测试'
        assert record['ibom'] == dict(source='file', path=str(tmp_path/'final.xlsx'), open=False)
        assert record['outputs'] == ['ibom'] and record['gerberDraft']['version'] == 1
    finally:
        view.stop_polling(); root.destroy()
    root = tk.Tk(); view = w.DeliveryWindow(root, args)
    try:
        assert view.bom_path.get().endswith('final.xlsx') and not hasattr(view, 'open_ibom')
        assert view.report_metadata['author'].get() == '坐标编制测试'
        assert view.report_metadata['version'].get() == 'A/1'
        import datetime
        assert view.report_metadata['date'].get() == datetime.date.today().isoformat()
    finally:
        view.stop_polling(); root.destroy()


def test_missing_native_connection_blocks_gerber_but_does_not_block_ibom(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    errors = []
    monkeypatch.setattr('tkinter.messagebox.showerror', lambda *a, **kw: errors.append(a))
    root = tk.Tk(); view = w.DeliveryWindow(root, SimpleNamespace(source=str(tmp_path/'pcb.brd'), board=str(tmp_path/'copy.brd')))
    try:
        view.reading = False
        for key, variable in view.selected_outputs.items():
            variable.set(key == 'gerber')
        view.gerber.mode.set('draft'); view.start()
        assert errors and '回写连接' in errors[-1][1]
        assert view.page.get() == 'Gerber / 光绘' and not view.busy
        view.only_ibom(); view.bom_source.set('pcb'); view.start()
        assert view.busy
    finally:
        view.stop_polling(); root.destroy()


def test_export_synchronizes_pending_films_and_uses_verified_snapshot(tmp_path, monkeypatch):
    from edakit.ibom import gerber as g
    monkeypatch.setattr(w, 'app_dir', lambda: tmp_path/'private')
    monkeypatch.setattr(w.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(w.delivery.exporter, 'settings', lambda: {})
    errors, calls, writes = [], [], []
    monkeypatch.setattr('tkinter.messagebox.showerror', lambda *a, **kw: errors.append(a))
    args = SimpleNamespace(source=str(tmp_path/'pcb.brd'), board=str(tmp_path/'initial.brd'), cadence_root='fixture')
    root = tk.Tk(); view = w.DeliveryWindow(root, args)
    copper = [dict(name=name, kind='CONDUCTOR') for name in ('TOP', 'BOTTOM')]
    files = g.recommended(copper, 'BOARD GEOMETRY/OUTLINE')
    known = list(dict.fromkeys(l for f in files for l in f['layers']))
    verified = tmp_path/'verified.brd'; verified.write_bytes(b'fresh-films')
    def apply(baseline, target, *, copper):
        writes.append((baseline, target, copper))
        return dict(board=verified, records=target, known=known, target=target)
    try:
        view.gerber.apply_metadata(dict(copper_layers=copper, film_records=files, films=[f['name'] for f in files], film_layers=known, choices={'板框层': ['BOARD GEOMETRY/OUTLINE']}))
        view.reading = False; view.set_busy(False)
        view.gerber.mode.set('draft'); view.gerber.change_mode()
        view.gerber.files[1]['name'] = 'NEW_TOP'
        monkeypatch.setattr(view, 'film_connection', lambda: SimpleNamespace(apply=apply))
        monkeypatch.setattr(w.threading, 'Thread', lambda target, **kw: SimpleNamespace(start=target))
        def run(*a, **kw):
            calls.append(kw)
            assert writes and kw['gerber_board'] == verified
            assert 'NEW_TOP' in kw['film_names']
            return dict(files=10, warnings=False)
        monkeypatch.setattr(w.delivery, 'run', run)
        for key, variable in view.selected_outputs.items():
            variable.set(key == 'gerber')
        view.start()
        root.after_cancel(view.after_id); view.after_id = None
        view.poll()
        assert len(calls) == 1 and not errors and not view.busy
        assert view.gerber.mode.get() == 'existing' and 'NEW_TOP' in view.gerber.selected_films()
        def reject(*a, **kw):
            raise ValueError('native write rejected')
        monkeypatch.setattr(view, 'film_connection', lambda: SimpleNamespace(apply=reject))
        view.start()
        root.after_cancel(view.after_id); view.after_id = None
        view.poll()
        assert len(calls) == 1 and errors and 'native write rejected' in errors[-1][1]
    finally:
        view.stop_polling(); root.destroy()

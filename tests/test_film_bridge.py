"""Transport/receipt and independent Tk tests; never open or automate Allegro."""
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from edakit.ibom import film_bridge as b, gerber as g


COPPER = [dict(name='TOP', kind='CONDUCTOR'), dict(name='BOTTOM', kind='CONDUCTOR')]
OUTLINE = 'BOARD GEOMETRY/OUTLINE'


def films_text(records, known):
    text = 'EDAKIT_FILMS\t1\n'
    for file in records:
        text += f"F\t{file['name']}\t{int(file.get('negative', False))}\t{int(file.get('mirror', False))}\n"
        text += ''.join(f"L\t{file['name']}\t{layer}\n" for layer in file['layers'])
    return text+''.join('K\t'+layer+'\n' for layer in known)+f'END\t{len(records)}\n'


@pytest.fixture
def session(tmp_path):
    base = tmp_path/'random.bridge'
    source = tmp_path/'source.brd'; source.write_bytes(b'original-source')
    Path(str(base)+'.host.json').write_text(json.dumps(dict(host={'pid': 987, 'identity': 'fixture'}, source=str(source))))
    target = g.recommended(COPPER, OUTLINE)
    known = list(dict.fromkeys(layer for f in target for layer in f['layers']))
    return base, source, target, known


def native_receipt(base, nonce, target, known, status='OK'):
    Path(str(base)+'.'+nonce+'.brd').write_bytes(b'verified-live-snapshot')
    Path(str(base)+'.'+nonce+'.films.tsv').write_text(films_text(target, known), encoding='utf-8')
    Path(str(base)+'.'+nonce+'.receipt').write_text(nonce+'\n'+status+'\nNative callback result\n', encoding='ascii')


def test_roundtrip_add_rename_delete_layers_and_selected_output(session):
    base, source, files, known = session
    baseline = copy.deepcopy(files)
    files[1]['name'] = 'MY_TOP'
    files[-1]['enabled'] = False
    deleted = files.pop(-2)
    files.append(dict(id='manual', name='NEW_FILE', layers=[OUTLINE], negative=False, mirror=True))
    def sender(host, nonce):
        assert host['pid'] == 987
        request = Path(str(base)+'.request').read_text(encoding='mbcs' if b.os.name == 'nt' else 'utf-8')
        assert f'F\tMY_TOP\t0\t0\t{baseline[1]["name"]}\tETCH/TOP' in request
        assert f'F\t{deleted["name"]}\t' not in request
        assert 'F\tNEW_FILE\t0\t1\t*\t'+OUTLINE in request
        native_receipt(base, nonce, files, known)
    result = b.FilmBridge(base, source, sender=sender).apply(baseline, files, copper=COPPER)
    assert result['board'].read_bytes() == b'verified-live-snapshot'
    assert b.signature(result['records']) == b.signature(files)
    assert result['target'][-2]['enabled'] is False
    assert source.read_bytes() == b'original-source'
    assert not Path(str(base)+'.pending').exists()
    assert not Path(str(base)+'.uncertain').exists()


@pytest.mark.parametrize('failure', ['mismatch', 'missing-board', 'wrong-nonce', 'uncertain', 'timeout', 'send-failed'])
def test_unverified_result_blocks_export_and_retries(session, failure):
    base, source, target, known = session
    def sender(host, nonce):
        if failure == 'send-failed':
            raise TimeoutError('transport timeout')
        if failure == 'timeout':
            return
        native_receipt(base, nonce, target, known, 'UNCERTAIN' if failure == 'uncertain' else 'OK')
        if failure == 'mismatch':
            changed = copy.deepcopy(target); changed[1]['layers'].pop()
            Path(str(base)+'.'+nonce+'.films.tsv').write_text(films_text(changed, known))
        elif failure == 'missing-board':
            Path(str(base)+'.'+nonce+'.brd').unlink()
        elif failure == 'wrong-nonce':
            Path(str(base)+'.'+nonce+'.receipt').write_text('wrong\nOK\nother request\n')
    bridge = b.FilmBridge(base, source, sender=sender, timeout=0)
    with pytest.raises((ValueError, TimeoutError)):
        bridge.apply(target, target, copper=COPPER)
    assert Path(str(base)+'.uncertain').exists()
    assert Path(str(base)+'.request').read_bytes() == b'EDAKIT_FILM_CANCELLED\n'
    with pytest.raises(ValueError, match='上次回写结果未确认'):
        bridge.apply(target, target, copper=COPPER)
    assert source.read_bytes() == b'original-source'


def test_explicit_native_failure_with_verified_rollback_allows_retry(session):
    base, source, target, known = session
    def sender(host, nonce):
        native_receipt(base, nonce, target, known, 'ERROR')
    with pytest.raises(b.NativeRejected):
        b.FilmBridge(base, source, sender=sender).apply(target, target, copper=COPPER)
    assert not Path(str(base)+'.uncertain').exists()


def test_source_conflict_pending_and_invalid_payload_never_send(session):
    base, source, target, known = session
    def forbidden(*args):
        pytest.fail('must reject before sending')
    with pytest.raises(ValueError, match='不一致'):
        b.FilmBridge(base, source.with_name('different.brd'), sender=forbidden).apply(target, target, copper=COPPER)
    Path(str(base)+'.pending').touch()
    with pytest.raises(ValueError, match='尚未结束'):
        b.FilmBridge(base, source, sender=forbidden).apply(target, target, copper=COPPER)
    Path(str(base)+'.pending').unlink()
    target[0]['layers'] = ['BOARD GEOMETRY/OUTLINE\nmalformed']
    with pytest.raises(ValueError, match='无效'):
        b.FilmBridge(base, source, sender=forbidden).apply([], target, copper=COPPER)


@pytest.mark.parametrize('count', [2, 4, 6, 8, 16])
def test_actual_copper_count_and_verified_plane_polarity(tmp_path, count):
    copper = [dict(name='PCB_'+str(i), kind='PLANE' if i == 1 else 'CONDUCTOR', negative=i == 1) for i in range(count)]
    files = g.recommended(copper, OUTLINE)
    assert len([f for f in files if f['role'] == 'copper']) == count
    assert next(f for f in files if f.get('source') == 'PCB_1')['negative']
    request = b.request_text('a'*32, [], files, copper)
    assert len([row for row in request.splitlines() if row.startswith('C\t')]) == count
    text = films_text(files, [l for f in files for l in f['layers']])
    text = text.replace('END\t', 'P\tPCB_1\t1\nEND\t')
    path = tmp_path/'films.tsv'; path.write_text(text)
    assert g.read_layer_polarities(path) == {'PCB_1': True}


def test_snapshot_copy_uses_temporary_input_and_refuses_source_overwrite(tmp_path):
    source = tmp_path/'source.brd'; source.write_bytes(b'memory-snapshot')
    output = tmp_path/'owned.brd'
    assert b.copy_snapshot(SimpleNamespace(board=source, output=output)) == 0
    assert output.read_bytes() == b'memory-snapshot' and source.read_bytes() == b'memory-snapshot'
    for path in (source, output):
        with pytest.raises(ValueError):
            b.copy_snapshot(SimpleNamespace(board=source, output=path))


def test_native_command_only_accepts_fixed_hex_token():
    with pytest.raises(ValueError):
        b.send({}, 'untrusted" skill delete')


@pytest.mark.skipif(os.name != 'nt', reason='Windows WM_COPYDATA protocol')
def test_windows_transport_only_targets_owned_test_process(tmp_path):
    # The receiver is our own Python/Tk process. No Cadence windows are opened,
    # enumerated by name, selected, controlled, or sent any message.
    received, ready = tmp_path/'received.json', tmp_path/'ready'
    script = r'''
import ctypes, json, os, sys, tkinter as tk
from ctypes import wintypes as w
from pathlib import Path
root = tk.Tk(); root.title('EdaKit transport test'); root.geometry('260x60+20+20')
tk.Label(root, text='Independent Film transport test').pack(); root.update()
api = ctypes.WinDLL('user32', use_last_error=True)
api.GetParent.argtypes = [w.HWND]; api.GetParent.restype = w.HWND
hwnd = api.GetParent(root.winfo_id())
class CopyData(ctypes.Structure):
    _fields_ = [('tag', ctypes.c_size_t), ('size', w.DWORD), ('data', ctypes.c_void_p)]
Proc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
api.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_void_p]
api.SetWindowLongPtrW.restype = ctypes.c_void_p
api.CallWindowProcW.argtypes = [ctypes.c_void_p, w.HWND, w.UINT, w.WPARAM, w.LPARAM]
api.CallWindowProcW.restype = ctypes.c_ssize_t
@Proc
def callback(h, message, wp, lp):
    if message == 0x4a:
        packet = ctypes.cast(lp, ctypes.POINTER(CopyData)).contents
        raw = ctypes.string_at(packet.data, packet.size)
        Path(sys.argv[1]).write_text(json.dumps(dict(tag=packet.tag, raw=raw.decode('ascii'))))
        return 1
    return api.CallWindowProcW(old, h, message, wp, lp)
old = api.SetWindowLongPtrW(hwnd, -4, ctypes.cast(callback, ctypes.c_void_p))
Path(sys.argv[2]).write_text(str(os.getpid()))
def finish():
    if Path(sys.argv[1]).exists():
        root.destroy()
    else:
        root.after(50, finish)
root.after(50, finish); root.after(10000, root.destroy); root.mainloop()
'''
    process = subprocess.Popen([sys.executable, '-c', script, str(received), str(ready)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic()+10
        while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        assert ready.exists()
        nonce = 'e'*32
        receiver_pid = int(ready.read_text())  # Windows venv redirector may own Popen.pid
        b.send(dict(pid=receiver_pid, identity=b.process_identity(receiver_pid)), nonce)
        stdout, stderr = process.communicate(timeout=12)
        assert process.returncode == 0, stderr.decode(errors='replace')
        result = json.loads(received.read_text())
        assert result == dict(tag=0x26297811, raw='skill edakitDeliveryApplyFilms("'+nonce+'")\x00')
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=5)


def test_native_template_is_ascii_and_procedures_have_balanced_top_level_forms():
    # This catches malformed generated SKILL, not native API/runtime behavior.
    path = Path(__file__).parents[1]/'src/edakit/install/templates/ibom.il'
    text = path.read_text(encoding='ascii')
    stack, quoted, escaped, comment = [], False, False, False
    for index, ch in enumerate(text):
        if comment:
            comment = ch != '\n'
        elif quoted:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == ';':
            comment = True
        elif ch == '"':
            quoted = True
        elif ch == '(':
            if text[max(0, index-9):index] == 'procedure':
                assert not stack, f'nested procedure at line {text[:index].count(chr(10))+1}'
            stack.append(index)
        elif ch == ')':
            assert stack, f'extra parenthesis at {index}'
            stack.pop()
    assert not stack and not quoted


def test_renamed_saved_id_preserves_existing_native_film_settings(session):
    base, source, files, known = session
    target = copy.deepcopy(files)
    target[1]['id'] = 'id-before-rename'
    payload = b.request_text('f'*32, files, target, COPPER)
    name = files[1]['name']
    assert f'F\t{name}\t0\t0\t{name}\t' in payload


def test_editor_integrates_review_then_accepts_authoritative_readback(session):
    import tkinter as tk
    from tkinter import ttk
    from edakit.ibom.gerber_window import GerberEditor
    base, source, files, known = session
    root = tk.Tk()
    writes = []
    editor = GerberEditor(root, {}, lambda m: None, lambda baseline, target: writes.append((baseline, target)))
    try:
        editor.apply_metadata(dict(copper_layers=COPPER, film_records=files, films=[f['name'] for f in files], film_layers=known, choices={'板框层': [OUTLINE]}))
        editor.mode.set('draft'); editor.change_mode()
        editor.files[1]['name'] = 'renamed'; editor.files[-1]['enabled'] = False
        editor.write_pcb()
        assert len(writes) == 1 and writes[0][1][1]['name'] == 'renamed'
        readback_path = source.with_suffix('.tsv')
        readback_path.write_text(films_text(writes[0][1], known))
        records, _ = g.read_film_records(readback_path)
        editor.accept_write(dict(records=records, known=known, target=writes[0][1]))
        assert editor.mode.get() == 'existing'
        assert 'renamed' in editor.selected_films() and files[-1]['name'] not in editor.selected_films()
        assert not editor.undo
        def descendants(w):
            for child in w.winfo_children():
                yield child
                yield from descendants(child)
        buttons = [w.cget('text') for w in descendants(editor) if isinstance(w, ttk.Button)]
        assert '核对层映射' not in buttons and '一键设置…' in buttons
        baseline, target = editor.export_configuration()
        assert {f['name'] for f in baseline} == {f['name'] for f in records}
        editor.mode.set('draft'); editor.change_mode()
        editor.files[1]['layers'] = []
        with pytest.raises(ValueError, match='空映射'):
            editor.export_configuration()
    finally:
        root.destroy()


def test_changed_native_baseline_does_not_reapply_stale_saved_draft(session):
    import tkinter as tk
    from edakit.ibom.gerber_window import GerberEditor
    _, _, files, known = session
    stale = copy.deepcopy(files); stale[1]['name'] = 'old-draft'
    changed = copy.deepcopy(files); changed[1]['name'] = 'current-PCB'
    root = tk.Tk()
    try:
        editor = GerberEditor(root, dict(version=1, files=stale, baselineRecords=files), lambda m: None)
        editor.apply_metadata(dict(film_records=changed, films=[f['name'] for f in changed], film_layers=known))
        editor.mode.set('draft'); editor.change_mode()
        assert 'current-PCB' in [f['name'] for f in editor.files]
        assert 'old-draft' not in [f['name'] for f in editor.files]
        assert editor.snapshot()['previousDraft'] == stale
    finally:
        root.destroy()


def test_native_tree_edit_button_enters_edit_and_keeps_selected_layer(session):
    import tkinter as tk
    from tkinter import ttk
    from edakit.ibom.gerber_window import GerberEditor
    _, _, files, known = session
    root = tk.Tk()
    editor = GerberEditor(root, {}, lambda m: None)
    try:
        editor.apply_metadata(dict(film_records=files, films=[f['name'] for f in files], film_layers=known))
        assert editor.mode.get() == 'existing'
        assert all(not button.instate(['disabled']) for button in editor.edit_buttons[:-1])
        editor.tree.selection_set('existing-1:layer:0')
        editor.edit('edit'); root.update()
        dialog = next(w for w in editor.winfo_children() if isinstance(w, tk.Toplevel))
        assert dialog.title() == '子层设置'
        assert editor.mode.get() == 'draft'
        assert editor.items[editor.tree.selection()[0]][1] == 0
        dialog.destroy()
        editor.tree.selection_set(editor.files[1]['id'])
        editor.edit('edit'); root.update()
        dialog = next(w for w in editor.winfo_children() if isinstance(w, tk.Toplevel))
        assert dialog.title() == '层文件设置'
        assert editor.records == files
        dialog.destroy()
        editor.set_busy(True)
        assert all(button.instate(['disabled']) for button in editor.edit_buttons)
    finally:
        root.destroy()

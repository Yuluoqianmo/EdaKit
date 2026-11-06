import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

from edakit.ibom import gerber as g


def copper():
    return [dict(name=name, kind='CONDUCTOR') for name in ('TOP', 'SIGNAL_3', 'SIGNAL_7', 'BOTTOM')]


def test_film_order_is_natural_ascending_in_reader_and_tree(tmp_path, monkeypatch):
    import tkinter as tk
    from edakit.ibom.gerber_window import GerberEditor
    names = ['12_ADB', '11_ADT', '10_DRILL', '9_PASTE', '02_TOP', '01_OUTLINE']
    expected = ['01_OUTLINE', '02_TOP', '9_PASTE', '10_DRILL', '11_ADT', '12_ADB']
    monkeypatch.setattr(g, 'app_dir', lambda: tmp_path/'private')
    board = tmp_path/'copy.brd'; board.write_bytes(b'pcb')
    def runner(cmd, stdout, **kwargs):
        stdout.write(('\n'.join(names)+'\n').encode())
        return SimpleNamespace(returncode=0)
    assert g.read_films(board, tmp_path, runner) == expected
    root = tk.Tk()
    try:
        editor = GerberEditor(root, {}, lambda message: None)
        editor.apply_metadata({'films': names})
        assert [editor.tree.item(i, 'text') for i in editor.tree.get_children()] == expected
        editor.tree.selection_set('existing-0'); editor.toggle()
        assert editor.selected_films() == expected[1:]
        editor.files = [dict(id=n, name=n, layers=[], role='custom') for n in names]
        editor.mode.set('draft'); editor.refresh()
        assert [editor.tree.item(i, 'text').removeprefix('＋ ') for i in editor.tree.get_children()] == expected
        assert [f['name'] for f in editor.files] == names
    finally:
        root.destroy()


def test_recommendations_follow_real_stack_order_and_include_reference_and_package_silk():
    files = g.recommended(copper(), 'BOARD GEOMETRY/DESIGN_OUTLINE')
    assert len(files) == 11
    assert files[2]['layers'] == ['ETCH/SIGNAL_3', 'PIN/SIGNAL_3', 'VIA CLASS/SIGNAL_3']
    silk = next(f for f in files if f['id'] == 'silk-TOP')
    assert 'REF DES/SILKSCREEN_TOP' in silk['layers']
    assert 'PACKAGE GEOMETRY/SILKSCREEN_TOP' in silk['layers']
    assert not any(i['level'] == '错误' for i in g.review(files, copper(), 'BOARD GEOMETRY/DESIGN_OUTLINE'))


def test_special_stack_and_cutout_require_manual_configuration():
    for layers, outline in (([dict(name='TOP', kind='PLANE'), copper()[-1]], 'BOARD GEOMETRY/OUTLINE'), (copper(), 'BOARD GEOMETRY/CUTOUT'), ([], 'BOARD GEOMETRY/OUTLINE')):
        with pytest.raises(ValueError):
            g.recommended(layers, outline)


def test_merge_preserves_manual_edits_and_can_replace_without_mutating_inputs():
    expected = g.recommended(copper(), 'BOARD GEOMETRY/OUTLINE')
    files = copy.deepcopy(expected[:3])
    files[1]['layers'].pop(); files[2].update(name='manual-name', modified=True)
    before = copy.deepcopy(files)
    merged, added, fixed, kept = g.merge(files, expected)
    assert files == before and len(merged) == 11
    assert len(added) == 8 and len(fixed) == 1 and kept == ['manual-name.art']
    assert next(f for f in merged if f['id'] == files[1]['id'])['layers'][-1] == 'VIA CLASS/TOP'
    replaced, *_ = g.merge(files, expected, True)
    assert replaced == expected and replaced is not expected


@pytest.mark.parametrize('name', ['', 'CON', 'nul.txt', '../x', 'LPT1', 'a.', 'a ', 'a/b', 'a\\b', 'a\n'])
def test_invalid_filenames(name):
    assert not g.valid_name(name)


def test_review_locates_missing_copper_content_and_deselected_films():
    files = g.recommended(copper(), 'BOARD GEOMETRY/OUTLINE')
    files[1]['layers'].remove('VIA CLASS/TOP')
    issues = g.review(files, copper(), 'BOARD GEOMETRY/OUTLINE')
    assert any(i.get('file') == files[1]['id'] and 'VIA CLASS/TOP' in i['text'] for i in issues)
    files[2]['enabled'] = False
    assert any('缺少铜层输出：SIGNAL_3' in i['text'] for i in g.review(files, copper(), 'BOARD GEOMETRY/OUTLINE'))


def test_film_reader_only_lists_from_snapshot_and_rejects_invalid_output(tmp_path, monkeypatch):
    monkeypatch.setattr(g, 'app_dir', lambda: tmp_path/'private')
    board = tmp_path/'copy.brd'; board.write_bytes(b'unchanged')
    def runner(cmd, stdout, **kw):
        assert cmd[1:] == ['-l', str(board.resolve())]
        stdout.write(b'TOP\nBOTTOM\n')
        return SimpleNamespace(returncode=0)
    assert g.read_films(board, tmp_path, runner) == ['BOTTOM', 'TOP']
    assert board.read_bytes() == b'unchanged'
    def invalid(cmd, stdout, **kw):
        stdout.write(b'../outside\n')
        return SimpleNamespace(returncode=0)
    with pytest.raises(ValueError):
        g.read_films(board, tmp_path, invalid)


def test_tree_crud_undo_mode_and_live_export_selection(tmp_path, monkeypatch):
    import tkinter as tk
    from tkinter import ttk
    from edakit.ibom.delivery_theme import install
    from edakit.ibom.gerber_window import GerberEditor
    root = tk.Tk(); install(root)
    editor = GerberEditor(root, {}, lambda message: None, lambda baseline, target: None)
    editor.pack(fill='both', expand=True)
    root.geometry('1000x700')
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    try:
        expected = g.recommended(copper(), 'BOARD GEOMETRY/OUTLINE')
        actual = [dict(expected[1], name='TOP', origin='pcb'), dict(expected[4], name='BOTTOM', origin='pcb')]
        known = list(dict.fromkeys([layer for file in expected for layer in file['layers']]+['BOARD GEOMETRY/DIMENSION']))
        editor.apply_metadata(dict(copper_layers=copper(), films=['TOP', 'BOTTOM'], film_records=actual, film_layers=known, choices={'板框层': ['BOARD GEOMETRY/OUTLINE']}))
        assert editor.selected_films() == ['BOTTOM', 'TOP']
        root.update(); editor.tree.selection_set('existing-0'); editor.toggle()
        assert editor.selected_films() == ['TOP']
        editor.configure_plan(); root.update()
        dialog = next(w for w in descendants(root) if isinstance(w, tk.Toplevel))
        next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '设置并写入 PCB').invoke()
        assert editor.mode.get() == 'draft' and len(editor.files) == 11
        editor.tree.selection_set('copper-TOP')
        editor.edit('layer-new'); root.update()
        dialog = next(w for w in descendants(root) if isinstance(w, tk.Toplevel))
        combo = next(w for w in descendants(dialog) if isinstance(w, ttk.Combobox))
        combo.set('BOARD GEOMETRY/DIMENSION')
        next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '保存').invoke()
        assert editor.files[1]['layers'][-1] == 'BOARD GEOMETRY/DIMENSION'
        editor.restore(); assert 'BOARD GEOMETRY/DIMENSION' not in editor.files[1]['layers']
        editor.tree.selection_set('copper-TOP'); editor.edit('edit'); root.update()
        dialog = next(w for w in descendants(root) if isinstance(w, tk.Toplevel))
        entry = next(w for w in descendants(dialog) if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox))
        entry.delete(0, 'end'); entry.insert(0, 'CUSTOM-TOP')
        next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '保存').invoke()
        assert editor.files[1]['name'] == 'CUSTOM-TOP'
        monkeypatch.setattr('tkinter.messagebox.askyesno', lambda *a, **kw: True)
        editor.tree.selection_set('copper-TOP'); editor.delete(); assert len(editor.files) == 10
        editor.restore(); assert len(editor.files) == 11
        editor.run_review(); assert not any(i['level'] == '错误' for i in editor.issues)
        editor.set_busy(True); assert all(w.instate(['disabled']) for w in editor.edit_buttons)
        editor.set_busy(False); assert not editor.edit_buttons[0].instate(['disabled'])
        assert editor.snapshot()['enabledExisting'] == ['TOP']
    finally:
        root.destroy()

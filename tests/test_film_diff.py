import copy
import tkinter as tk
from edakit.ibom import gerber as g
from edakit.ibom.gerber_window import GerberEditor


def records():
    return g.recommended([dict(name=n, kind='CONDUCTOR') for n in ('TOP', 'BOTTOM')], 'BOARD GEOMETRY/OUTLINE')


def test_diff_tracks_rename_polarity_layer_add_remove_and_deleted_file():
    before = records(); after = copy.deepcopy(before)
    after[1].update(name='RENAMED', negative=True, mirror=True)
    after[1]['layers'].remove('PIN/TOP'); after[1]['layers'].append('BOARD GEOMETRY/OUTLINE')
    deleted = after.pop(2)
    after.append(dict(id='manual', name='NEW', layers=['ETCH/TOP']))
    changes = g.film_changes(before, after)
    assert [c['kind'] for c in changes] == ['修改', '删除', '新增']
    renamed = changes[0]
    assert renamed['id'] == before[1]['id']
    assert '-02_TOP.art' in renamed['diff'] and '+RENAMED.art' in renamed['diff']
    assert '-PIN/TOP' in renamed['diff'] and '+BOARD GEOMETRY/OUTLINE' in renamed['diff']
    assert '+极性：负片' in renamed['diff'] and '+镜像：是' in renamed['diff']
    assert changes[1]['old']['name'] == deleted['name'] and changes[1]['new'] is None
    assert g.film_changes(before, copy.deepcopy(before)) == []
    enabled = copy.deepcopy(before); enabled[0]['enabled'] = False
    assert g.film_changes(before, enabled) == []


def test_inline_tree_deleted_rows_restore_undo_and_write_ack_clear_marks():
    root = tk.Tk(); editor = GerberEditor(root, {}, lambda m: None)
    before = records(); known = list(dict.fromkeys(l for f in before for l in f['layers']))
    try:
        editor.pack(fill='both', expand=True)
        editor.apply_metadata(dict(film_records=before, films=[f['name'] for f in before], film_layers=known))
        root.update()
        assert not editor.header.winfo_ismapped() and not editor.header.winfo_children()
        editor.begin_edit(); editor.undo = copy.deepcopy(editor.files)
        editor.files[1]['name'] = 'RENAMED'
        removed = editor.files.pop(2)
        editor.refresh()
        assert editor.tree.item(before[1]['id'], 'text') == '~ 02_TOP → RENAMED'
        assert '删除 1' in editor.change_summary.cget('text')
        assert not hasattr(editor, 'diff_button') and not hasattr(editor, 'show_diff')
        assert 'removed' in editor.tree.item(removed['id'], 'tags')
        assert removed['id'] in editor.removed_items
        assert all(f['id'] != removed['id'] for f in editor.files)
        editor.tree.selection_set(removed['id']); editor.show_properties()
        assert editor.edit_buttons[3].cget('text') == '恢复'
        editor.toggle()
        assert all(f['id'] != removed['id'] for f in editor.files)
        editor.delete()
        assert any(f['id'] == removed['id'] for f in editor.files)
        editor.restore()
        assert all(f['id'] != removed['id'] for f in editor.files)
        editor.files = copy.deepcopy(before); editor.refresh()
        assert not editor.changes
        editor.files[1]['name'] = 'RENAMED'; editor.refresh()
        target = copy.deepcopy(editor.files)
        editor.accept_write(dict(records=target, target=target, known=known))
        assert not editor.changes and not editor.removed_items
        assert editor.records[1]['name'] == 'RENAMED'
    finally:
        root.destroy()


def test_inline_replaced_layer_ghost_never_addresses_pending_index():
    root = tk.Tk(); editor = GerberEditor(root, {}, lambda m: None)
    before = records(); known = list(dict.fromkeys(l for f in before for l in f['layers']))
    try:
        editor.apply_metadata(dict(film_records=before, films=[f['name'] for f in before], film_layers=known))
        editor.begin_edit()
        film = editor.files[1]; old = film['layers'][1]
        film['layers'][1] = 'BOARD GEOMETRY/OUTLINE'; editor.refresh()
        fid = film['id']; ghost = fid+':removed:1'
        assert editor.tree.item(ghost, 'text') == '− '+old
        assert editor.items[ghost][0] is not film
        assert editor.items[fid+':layer:1'][0] is film
        editor.tree.selection_set(ghost); editor.edit('edit')
        assert not any(isinstance(w, tk.Toplevel) for w in editor.winfo_children())
        editor.delete()
        assert old in film['layers'] and 'BOARD GEOMETRY/OUTLINE' in film['layers']
        assert ghost not in editor.removed_items
        rows = g.inline_layer_rows(['A', 'B', 'C'], ['A', 'X', 'C'])
        assert [(r['layer'], r['removed'], r['index']) for r in rows] == [('A', False, 0), ('B', True, 1), ('X', False, 1), ('C', False, 2)]
    finally:
        root.destroy()


def test_export_target_excludes_deleted_film_and_subclass_rows():
    root = tk.Tk(); editor = GerberEditor(root, {}, lambda m: None)
    before = records(); known = list(dict.fromkeys(l for f in before for l in f['layers']))
    try:
        editor.apply_metadata(dict(film_records=before, films=[f['name'] for f in before], film_layers=known,
                                   copper_layers=[dict(name=n, kind='CONDUCTOR') for n in ('TOP', 'BOTTOM')],
                                   choices={'板框层': ['BOARD GEOMETRY/OUTLINE']}))
        editor.begin_edit()
        removed = next(f for f in editor.files if f['role'] == 'silk')
        editor.files.remove(removed)
        copper = editor.files[1]
        copper['layers'].append('BOARD GEOMETRY/OUTLINE')
        editor.refresh()
        baseline, target = editor.export_configuration()
        assert removed['id'] in editor.removed_items
        assert removed['id'] in {f['id'] for f in baseline}
        assert removed['id'] not in {f['id'] for f in target}
        assert {f['id']: f['layers'] for f in target} == {f['id']: f['layers'] for f in editor.files}
    finally:
        root.destroy()

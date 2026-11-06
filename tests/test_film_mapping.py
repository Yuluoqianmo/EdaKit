from pathlib import Path
from types import SimpleNamespace
import copy

import pytest

from edakit.ibom import gerber as g


def fixture_data(tmp_path):
    copper = [dict(name=name, kind='CONDUCTOR') for name in ('TOP', 'POWER_A', 'SIG_B', 'BOTTOM')]
    expected = g.recommended(copper, 'BOARD GEOMETRY/OUTLINE')
    known = list(dict.fromkeys(layer for file in expected for layer in file['layers']))
    text = 'EDAKIT_FILMS\t1\n'
    # Arbitrary engineering names cannot be matched by generated IDs or filenames.
    for i, file in enumerate(expected):
        text += f'F\tMY_FILM_{i}\t{int(i == 2)}\t{int(i == 3)}\n'
        for layer in file['layers']:
            if i != 1 or not layer.startswith('VIA CLASS/'):
                text += f'L\tMY_FILM_{i}\t{layer}\n'
    text += ''.join('K\t'+layer+'\n' for layer in known)+f'END\t{len(expected)}\n'
    path = tmp_path/'films.tsv'; path.write_text(text, encoding='utf8')
    return copper, expected, known, path


def test_real_mapping_merge_preserves_names_flags_and_fills_existing_film(tmp_path):
    copper, expected, known, path = fixture_data(tmp_path)
    records, layers = g.read_film_records(path)
    before = copy.deepcopy(records)
    identified = g.identify_records(records, expected)
    result, added, fixed, kept = g.merge(identified, g.recommended(copper, 'BOARD GEOMETRY/OUTLINE', layers))
    assert records == before
    assert len(result) == 11 and not added and len(fixed) == 1
    assert {file['name'] for file in result} == {file['name'] for file in records}
    assert next(file for file in result if file['source'] == 'POWER_A' and file['role'] == 'copper')['negative']
    assert next(file for file in result if file['source'] == 'SIG_B' and file['role'] == 'copper')['mirror']
    top = next(file for file in result if file.get('match') == 'copper-TOP')
    assert top['name'] == 'MY_FILM_1' and 'VIA CLASS/TOP' in top['layers']
    assert not any(i['level'] == '错误' for i in g.review(result, copper, 'BOARD GEOMETRY/OUTLINE', known, full_inventory=True))


def test_partial_or_invalid_mapping_cannot_be_used(tmp_path):
    for text in ('EDAKIT_FILMS\t1\nF\tTOP\t0\t0\n',
                 'EDAKIT_FILMS\t1\nEND\t1\n',
                 'EDAKIT_FILMS\t1\nL\tmissing\tETCH/TOP\nEND\t0\n',
                 'EDAKIT_FILMS\t1\nF\tTOP\t0\t0\nF\ttop\t0\t0\nEND\t2\n'):
        path = tmp_path/'bad.tsv'; path.write_text(text)
        with pytest.raises(ValueError):
            g.read_film_records(path)


def test_old_generated_drafts_rebase_to_actual_films_and_current_stack(tmp_path):
    copper, expected, known, path = fixture_data(tmp_path)
    records, _ = g.read_film_records(path)
    old = g.recommended([dict(name=name, kind='CONDUCTOR') for name in ('TOP', 'INNER1', 'INNER2', 'INNER3', 'INNER4', 'BOTTOM')], 'BOARD GEOMETRY/OUTLINE')
    base = g.configuration_base(records, old, expected)
    result, added, _, _ = g.merge(base, expected)
    assert not added and len(result) == 11
    assert {f['name'] for f in result} == {f['name'] for f in records}
    assert not any('INNER' in layer for f in result for layer in f['layers'])


def test_actual_stack_and_available_layers_are_only_source_of_recommendations():
    copper = [dict(name=name, kind='CONDUCTOR') for name in ('TOP', 'A', 'B', 'C', 'D', 'E', 'F', 'BOTTOM')]
    known = ['BOARD GEOMETRY/DESIGN_OUTLINE']+['ETCH/'+c['name'] for c in copper]
    result = g.recommended(copper, known[0], known)
    assert len(result) == 9
    assert [file['source'] for file in result if file['role'] == 'copper'] == [c['name'] for c in copper]
    assert all(layer in known for file in result for layer in file['layers'])
    assert not any('INNER' in layer for file in result for layer in file['layers'])


def test_ambiguous_mapping_blocks_automatic_changes(tmp_path):
    copper, expected, _, path = fixture_data(tmp_path)
    records, _ = g.read_film_records(path)
    records.append(dict(records[1], id='duplicate', name='extra'))
    with pytest.raises(ValueError, match='多个已有 Film'):
        g.merge(g.identify_records(records, expected), expected)


def test_real_tree_expands_properties_and_shows_readonly_stack(tmp_path):
    import tkinter as tk
    from tkinter import ttk
    from edakit.ibom.gerber_window import GerberEditor
    copper, expected, known, path = fixture_data(tmp_path)
    records, _ = g.read_film_records(path)
    root = tk.Tk()
    try:
        editor = GerberEditor(root, {}, lambda message: None, lambda baseline, target: None)
        editor.pack(fill='both', expand=True)
        editor.apply_metadata(dict(copper_layers=copper, films=[r['name'] for r in records], film_records=records, film_layers=known, choices={'板框层': ['BOARD GEOMETRY/OUTLINE']}))
        root.update()
        assert '4 层' in editor.stack_text.get() and 'POWER_A' in editor.stack_text.get()
        assert not any(isinstance(w, ttk.Combobox) for w in editor.header.winfo_children())
        iid = next(i for i in editor.tree.get_children() if editor.tree.item(i, 'text') == 'MY_FILM_1')
        assert len(editor.tree.get_children(iid)) == 2
        editor.tree.selection_set(iid); editor.show_properties()
        assert editor.property_table.winfo_children()
        editor.configure_plan(); root.update()
        dialog = next(w for w in editor.winfo_children() if isinstance(w, tk.Toplevel))
        def descendants(w):
            for child in w.winfo_children():
                yield child
                yield from descendants(child)
        next(w for w in descendants(dialog) if isinstance(w, ttk.Button) and w.cget('text') == '设置并写入 PCB').invoke()
        assert len(editor.files) == 11
        assert {f['name'] for f in editor.files} == {f['name'] for f in records}
    finally:
        root.destroy()

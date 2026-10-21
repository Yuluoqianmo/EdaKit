import importlib.util
import subprocess
import shutil
import pytest
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def test_readback_contract_rejects_short_offgrid_and_fake_labels(tmp_path):
    from conftest import DATA
    from edakit.easyeda.parse import parse_component
    from edakit.symbol.capture_lib import generate_lib_xml
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('verify', root/'tools/diag/verify_capture_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    symbol = parse_component('C2040', json.loads((DATA/'C2040.json').read_text(encoding='utf-8'))).symbol
    xml = generate_lib_xml(symbol, package_name='RP2040_P6')
    path = tmp_path/'readback.xml'
    path.write_text(xml, encoding='utf-8')
    expected = module.contract(path)
    assert len(expected) == 57
    for change, message in [('short', 'not Line'), ('grid', 'Off-grid'),
                            ('labels', 'Unexpected text'), ('hidden', 'disabled')]:
        tree = ET.ElementTree(ET.fromstring(xml))
        if change == 'short':
            tree.find('.//IsLong/Defn').set('val', '0')
        elif change == 'grid':
            tree.find('.//SymbolPinScalar/Defn').set('hotptX', '1')
        elif change == 'labels':
            ET.SubElement(tree.find('.//NormalView'), 'CommentText')
        else:
            tree.find('.//IsPinNumbersVisible/Defn').set('val', '0')
        tree.write(path, encoding='utf-8')
        with pytest.raises(ValueError, match=message):
            module.contract(path)


def test_native_acceptance_uses_plugin_placement_sequence(tmp_path):
    tcl = shutil.which('tclsh')
    if not tcl:
        pytest.skip('Tcl runtime unavailable')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('prepare', root/'tools/diag/prepare_capture_acceptance.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    library = tmp_path/'final.olb'
    library.write_text('test library')
    script = module.native_placement_script(library, 'RP2040_P5R2')
    harness = '''
set calls {}
proc capGetMostRecentSchFrameID {} {return frame}
proc DboTclHelper_sGetConstCharPtr {x} {return $x}
namespace eval ui {proc SchematicActivate {x} {lappend ::calls activate}}
proc capGetIsSchematicEditingDisabled {} {return 0}
proc UnSelectAll {} {lappend ::calls unselect}
proc ZoomRedraw {} {lappend ::calls redraw}
proc PlaceNew {lib part flag} {
    if {![file isfile $lib]} {error "No placement snapshot"}
    if {$part ne "RP2040_P5R2" || $flag ne "0"} {error "Wrong arguments"}
    lappend ::calls place
    return 1
}
'''
    path = tmp_path/'test.tcl'
    path.write_text(harness+script+'\nputs "ORDER=$calls"\n', encoding='utf-8')
    result = subprocess.run([tcl, str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'ORDER=activate unselect redraw place' in result.stdout
    assert 'EDAKIT_NATIVE_ARMED' in result.stdout

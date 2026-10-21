import importlib.util
import subprocess
import shutil
import pytest
from pathlib import Path


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

import subprocess
from pathlib import Path
import pytest
from test_tcl_plugin import TCLSH


def test_context_fingerprint_refresh_and_fallback(tmp_path):
    if not TCLSH: pytest.skip('Tcl unavailable')
    plugin=Path(__file__).resolve().parents[1]/'src/edakit/install/templates/properties.tcl'
    driver=tmp_path/'context.tcl'
    driver.write_text(r'''namespace eval ::edakit {proc schematicActive {} {return 1}}
proc after {args} {}
source [lindex $argv 0]
proc ::edakit::properties::active {} {return design}
proc ::edakit::properties::stringCall {args} {return designName}
proc GetInstanceOccurrence {} {return parent}
set ::pageReads 0
set ::key one
proc ::edakit::properties::readContextIds {scope} {if {$scope eq "page"} {incr ::pageReads};return {a b}}
proc ::edakit::properties::pageFingerprint {} {return $::key}
for {set i 0} {$i<10} {incr i} {::edakit::properties::captureContext}
if {$::pageReads != 1} {error "unchanged context rescanned"}
set ::key otherHierarchy
::edakit::properties::captureContext
if {$::pageReads != 2} {error "hierarchy not refreshed"}
set ::edakit::properties::contextReadAt 0
::edakit::properties::captureContext
if {$::pageReads != 3} {error "periodic refresh missing"}
proc ::edakit::properties::pageFingerprint {} {error unavailable}
::edakit::properties::captureContext
if {$::pageReads != 4} {error "fallback missing"}
puts PASS
''',encoding='ascii')
    r=subprocess.run([TCLSH,str(driver),str(plugin)],capture_output=True,text=True,timeout=15)
    assert r.returncode==0,r.stdout+r.stderr
    assert 'PASS' in r.stdout

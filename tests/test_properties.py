"""Property bridge invariants and the real Tcl handler with a tiny DBO double."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from edakit.bridge import properties as p

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(p, 'resolve_target', lambda session: session if session == 'host-a' else '')

def snapshot():
    job = p.submit({'session': 'host-a'})['job']
    data = {'ok': 1, 'action': 'snapshot', 'design': 'design-1', 'root': 'root', 'rows': 1,
            '0.id': '0/1', '0.reference': 'U1', '0.path': '0/1', '0.props': 2,
            '0.0.name': 'Manufacturer', '0.0.value': 'Original', '0.0.readonly': 0,
            '0.1.name': 'Reference', '0.1.value': 'U1', '0.1.readonly': 1}
    (p.directory() / (job + '.resp')).write_text(p.encode(data), encoding='ascii')
    return job

def test_unicode_newline_and_tcl_are_data(tmp_path):
    value = '厂商\n= [exec anything] ; $secret \\ "{}😀'
    path = tmp_path / 'wire'
    path.write_text(p.encode({'name': value}), encoding='ascii')
    assert p.decode(path) == {'name': value}

def test_no_offline_write():
    with pytest.raises(ValueError, match='not connected'):
        p.submit({'session': ''})

def test_job_session_isolation_and_immutable_original():
    job = snapshot()
    with pytest.raises(ValueError, match='another'):
        p.status(job, 'host-b')
    submitted = p.submit({'session': 'host-a', 'action': 'apply', 'snapshot': job,
                         'changes': [{'id': '0/1', 'name': 'Manufacturer', 'value': '厂商\n=x', 'old': 'forged'}]})['job']
    request = p.decode(p.directory() / (submitted + '.req'))
    assert request['0.old'] == 'Original'
    assert request['0.value'] == '厂商\n=x'
    assert request['snapshot'] == job
    assert request['session'] == 'host-a'

@pytest.mark.parametrize('change', [
    {'id': '0/1', 'name': 'Reference', 'value': 'U9'},
    {'id': '0/1', 'name': 'manufacturer', 'value': 'a'},
    {'id': '0/1', 'name': 'bad\nname', 'value': 'a'},
    {'id': '0/1', 'name': 'New', 'value': '\x00'},
    {'id': 'missing', 'name': 'New', 'value': 'a'},
    None,
])
def test_invalid_edits_are_rejected(change):
    with pytest.raises(ValueError):
        p.submit({'session': 'host-a', 'action': 'apply', 'snapshot': snapshot(), 'changes': [change]})

def test_duplicate_changes_and_layout_validation():
    change = {'id': '0/1', 'name': 'Manufacturer', 'value': 'x'}
    with pytest.raises(ValueError, match='Duplicate'):
        p.submit({'session': 'host-a', 'action': 'apply', 'snapshot': snapshot(), 'changes': [change, change]})
    with pytest.raises(ValueError):
        p.layout({'columns': [{}]})
    with pytest.raises(ValueError):
        p.layout({'columns': ['Value', 'value']})
    expected = {'columns': ['Manufacturer', 'Value'], 'widths': {'Value': 240}, 'templates': {'采购': ['Manufacturer', 'Value']}}
    assert p.layout(expected) == expected
    assert p.layout() == expected

def test_pending_job_timeout(monkeypatch):
    job = p.submit({'session': 'host-a'})['job']
    assert p.status(job, 'host-a')['state'] == 'pending'
    monkeypatch.setattr(p.time, 'time', lambda: (p.directory() / (job + '.owner')).stat().st_mtime + 126)
    assert p.status(job, 'host-a')['state'] == 'error'

def test_tcl_native_handler_conflicts_and_scope(tmp_path):
    tcl = shutil.which('tclsh') or shutil.which('tclsh8.6')
    if not tcl:
        pytest.skip('No Tcl runtime')
    template = Path(__file__).parents[1] / 'src/edakit/install/templates/properties.tcl'
    wire = tmp_path / 'wire.txt'
    wire.write_text(p.encode({'value': '厂商\n[exec bad]; = 😀'}), encoding='ascii')
    driver = tmp_path / 'test.tcl'
    driver.write_text(r'''
source [lindex $argv 0]
set wire [lindex $argv 1]
set data [::edakit::properties::readWire $wire]
::edakit::properties::writeWire "$wire.out" $data
set ::model [dict create a [dict create Value [list old 0] Reference [list U1 1]] b [dict create Value [list other 0]] c [dict create Value [list old 0]]]
set ::design D
proc ::edakit::properties::active {} {return $::design}
proc ::edakit::properties::stringCall {obj method} {return test.dsn}
proc ::edakit::properties::collect {design} {return [list R [dict create 0/1 [list a part U1] 0/9/1 [list b part U1] 0/2 [list c part U1]]]}
proc ::edakit::properties::props {obj} {return [dict get $::model $obj]}
proc DboTclHelper_sMakeCString {args} {return [lindex $args 0]}
proc DboTclHelper_sDeleteCString {args} {}
proc DboState {} {return state}
proc state {method} {return 1}
proc part {args} {}
proc D {args} {}
proc a {method args} {
    if {$method eq "SetEffectivePropStringValue"} {
        dict set ::model a [lindex $args 0] [list [lindex $args 1] 0]
        return state
    }
    error "Unexpected $method"
}
set snap [::edakit::properties::handle [dict create action snapshot scope design] job]
if {[dict get $snap rows] != 3} {error "Hierarchy rows lost"}
set req [dict create action apply snapshot job design D|test.dsn root R count 1 0.id 0/1 0.reference U1 0.name Value 0.exists 1 0.old old 0.value new]
set result [::edakit::properties::handle $req j2]
if {[dict get $result 0.state] ne "applied"} {error "Apply failed: $result"}
if {[dict get $::model b Value] ne {other 0}} {error "Wrong hierarchy edited"}
dict set req 0.value newer
set result [::edakit::properties::handle $req j3]
if {[dict get $result 0.state] ne "conflict"} {error "Conflict missed: $result"}
dict set req 0.old forged
set result [::edakit::properties::handle $req j4]
if {[dict get $result 0.state] ne "error"} {error "Forged original accepted"}
namespace eval ::edakit {proc schematicActive {} {return $::viewActive}}
set ::viewActive 1
proc ::edakit::properties::readContextIds {scope} {if {$scope eq "selected"} {return a};return {a b}}
proc GetInstanceOccurrence {} {return parent}
::edakit::properties::captureContext
set ::viewActive 0
set selectedSnap [::edakit::properties::handle [dict create action snapshot scope selected] selectedJob]
if {[dict get $selectedSnap rows] != 2} {error "Selected package did not include peer units or crossed hierarchy"}
if {[::edakit::properties::selectedIds selected] ne "a"} {error "CEF focus lost selection"}
if {[::edakit::properties::selectedIds page] ne {a b}} {error "CEF focus lost page"}
set ::design changed
if {![catch {::edakit::properties::selectedIds selected}]} {error "Stale selection crossed designs"}
if {![catch {::edakit::properties::handle $req j5}]} {error "Design switch accepted"}
puts PASS
''', encoding='ascii')
    result = subprocess.run([tcl, str(driver), str(template), str(wire)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS' in result.stdout
    assert p.decode(Path(str(wire) + '.out'))['value'] == '厂商\n[exec bad]; = 😀'
    assert template.read_bytes().isascii()

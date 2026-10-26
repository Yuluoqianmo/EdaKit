import json
import os
import time
from pathlib import Path

import pytest
from edakit.services import bom
from edakit.ibom.retention import cleanup
from edakit.symbol.verification import verify
from edakit.easyeda.model import Footprint, Pad
from edakit.render.layers import category, filtered


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16', 'utf-16-be', 'utf-32'])
def test_workbook_rejects_entities_in_all_encodings(encoding):
    data = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "expanded">]><x>&a;</x>'
    with pytest.raises((ValueError, bom.ET.ParseError)):
        bom.xml(data.encode(encoding))


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_workbook_accepts_normal_unicode_xml(encoding):
    assert bom.xml('<x>中文</x>'.encode(encoding)).text == '中文'


def test_retention_preserves_active_recent_unknown_and_user_outputs(tmp_path):
    root = tmp_path / 'private'
    jobs = root / 'jobs'
    jobs.mkdir(parents=True)
    old = time.time() - 40 * 86400
    for suffix in ('11111111', '22222222', '33333333'):
        job = jobs / ('20260101_000000_' + suffix)
        job.mkdir()
        (job / 'board.xml').write_text('large data')
        if suffix == '22222222':
            (job / 'owner.json').write_text(json.dumps({'pid': os.getpid()}))
        if suffix != '33333333':
            os.utime(job, (old, old))
    unknown = jobs / 'user-folder'
    unknown.mkdir()
    os.utime(unknown, (old, old))
    cleanup(root)
    assert not (jobs / '20260101_000000_11111111').exists()
    assert (jobs / '20260101_000000_22222222/board.xml').exists()
    assert (jobs / '20260101_000000_33333333/board.xml').exists()
    assert unknown.exists()


def test_retention_removes_orphan_snapshot_companions(tmp_path):
    folder = tmp_path / 'snapshots'
    folder.mkdir()
    board = folder / ('a' * 32 + '.brd')
    companions = [board, board.with_suffix('.tsv'), Path(str(board.with_suffix('.tsv')) + '.models.tsv')]
    for path in companions:
        path.write_text('private snapshot')
    old = time.time() - 40 * 86400
    os.utime(board, (old, old))
    cleanup(tmp_path)
    assert not any(path.exists() for path in companions)


def test_olb_verification_rejects_stale_same_name(tmp_path):
    xml = '<Lib><Package><Defn name="A"/><LibPart><SymbolPinScalar><Defn position="0" name="VCC" hotptX="10"/></SymbolPinScalar><PinNumber><Defn position="0" number="1"/></PinNumber></LibPart></Package></Lib>'
    expected, actual = tmp_path / 'in.xml', tmp_path / 'out.xml'
    expected.write_text(xml)
    actual.write_text(xml.replace('hotptX="10"', 'hotptX="20"'))
    with pytest.raises(ValueError, match='成品内容'):
        verify(expected, actual)
    actual.write_text(xml.replace('<Lib>', '<Lib timestamp="different">'))
    assert verify(expected, actual) == 1


def test_preview_layers_share_native_mapping_without_mutating_source():
    fp = Footprint(pads=[Pad(number='1')], lines=[('ComponentShapeLayer', [(0, 0), (1, 1)]), ('TOP_SILK', [(0, 0), (2, 2)])])
    assert category('ComponentPolarityLayer') == 'silk'
    assert category('ComponentShapeLayer') == 'assembly'
    assert not filtered(fp, 'pads').lines
    assert len(filtered(fp, 'silk').lines) == 1
    assert not filtered(fp, 'assembly').pads
    assert len(fp.lines) == 2 and len(fp.pads) == 1


@pytest.mark.parametrize('old,new', [('pcbFootprint="GOOD"', 'pcbFootprint="WRONG"'), ('type="4"', 'type="7"'), ('name="Maker" val="A"', 'name="Maker" val="B"')])
def test_critical_olb_changes_rejected(tmp_path, old, new):
    xml = '<Lib><Package><Defn name="U" pcbFootprint="GOOD"/><LibPart><SymbolPinScalar><Defn name="VCC" type="4" hotptX="10"/></SymbolPinScalar><SymbolUserProp><Defn name="Maker" val="A"/></SymbolUserProp></LibPart></Package></Lib>'
    a,b = tmp_path/'a.xml',tmp_path/'b.xml'
    a.write_text(xml); b.write_text(xml.replace(old,new))
    with pytest.raises(ValueError): verify(a,b)


def test_numeric_equivalence_preserves_pin_identifiers(tmp_path):
    xml = '<Lib><Package><Defn name="U"/><LibPart><SymbolPinScalar><Defn name="VCC" hotptX="10" type="4"/></SymbolPinScalar><PinNumber><Defn number="01" position="0"/></PinNumber></LibPart></Package></Lib>'
    a,b=tmp_path/'a.xml',tmp_path/'b.xml'
    a.write_text(xml); b.write_text(xml.replace('hotptX="10"','hotptX="1e1"').replace('type="4"','type="4.0"'))
    assert verify(a,b)==1
    b.write_text(xml.replace('number="01"','number="1"'))
    with pytest.raises(ValueError): verify(a,b)


@pytest.mark.parametrize('stage', ['copy', 'spawn', 'lease'])
def test_snapshot_failure_ownership(tmp_path, monkeypatch, stage):
    from types import SimpleNamespace
    from edakit.ibom import window
    from edakit import storage
    board=tmp_path/'input.brd';board.write_bytes(b'board')
    labels=tmp_path/'labels.tsv';labels.write_text('labels')
    args=SimpleNamespace(board=str(board),source=str(board),labels=str(labels),cadence_root='')
    calls=[]
    def spawn(*args, **kwargs):
        calls.append(args)
        if stage=='spawn': raise OSError('spawn failed')
        return SimpleNamespace(pid=os.getpid())
    monkeypatch.setattr(window.subprocess,'Popen',spawn)
    original=storage.atomic_write
    writes=[]
    def write(path,data):
        writes.append(path)
        if stage=='lease' and len(writes)==2: raise OSError('lease failed')
        return original(path,data)
    monkeypatch.setattr(storage,'atomic_write',write)
    if stage=='copy': labels.unlink()
    if stage=='lease': assert window.launch(args)==0
    else:
        with pytest.raises(OSError): window.launch(args)
    folder=window.app_dir()/'ibom'/'snapshots'
    if stage=='lease':
        assert len(list(folder.glob('*.brd')))==1
        assert next(folder.glob('*.brd')).read_bytes()==b'board'
        assert json.loads(next(folder.glob('*.owner.json')).read_text())=={}
    else: assert list(folder.iterdir())==[]


@pytest.mark.parametrize('change,blocked', [('footprint', True), ('type', True), ('numeric', False)])
def test_tcl_real_cli_verification(tmp_path, change, blocked):
    import subprocess
    from test_tcl_plugin import TCLSH, PLUGIN
    if not TCLSH: pytest.skip('Tcl unavailable')
    xml='<Lib><Package><Defn name="U" pcbFootprint="GOOD"/><LibPart><SymbolPinScalar><Defn name="VCC" type="4" hotptX="10"/></SymbolPinScalar></LibPart></Package></Lib>'
    mutations={'footprint':('GOOD','WRONG'), 'type':('type="4"','type="7"'), 'numeric':('hotptX="10"','hotptX="10.00"')}
    expected,actual=tmp_path/'expected.xml',tmp_path/'actual.xml'
    expected.write_text(xml);actual.write_text(xml.replace(*mutations[change]))
    driver=tmp_path/'verify.tcl'
    driver.write_text(r'''proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
set ::actual [lindex $argv 2]
proc XMATIC_OLB2XML {olb xml} {file copy -force $::actual $xml}
rename exec nativeExec
proc exec {args} {
    return [nativeExec $::env(EDAKIT_TEST_PYTHON) $::env(EDAKIT_TEST_ENTRY) {*}[lrange $args 1 end]]
}
source [lindex $argv 0]
set failed [catch {::edakit::verifyOlbContent dummy [lindex $argv 1] [lindex $argv 3]} reason]
if {$failed != [lindex $argv 4]} {error "unexpected result: $failed $reason"}
puts PASS
''',encoding='ascii')
    result=subprocess.run([TCLSH,str(driver),str(PLUGIN),str(expected),str(actual),str(tmp_path/'part.olb'),str(int(blocked))],capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stdout+result.stderr
    assert 'PASS' in result.stdout

"""Repeated placement skips XML generation, native conversion and merge launch."""
import json
from pathlib import Path
import subprocess

import pytest

from edakit.config import Config
from edakit.easyeda.parse import parse_component
from edakit.pipeline import stage_component
from conftest import DATA


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "runtime"))
    component = parse_component("C2040", json.loads((DATA / "C2040.json").read_text(encoding="utf-8")))
    cfg = Config(footprint_lib=str(tmp_path / "lib"), project_olb=str(tmp_path / "project.olb"))
    return component, cfg


def test_capture_preparation_reuses_xml_across_calls_and_instances(prepared, monkeypatch):
    from edakit.symbol import capture_lib
    component, cfg = prepared
    first = stage_component(component, cfg, capture_only=True)
    before = first.symbol_xml.stat().st_mtime_ns
    def forbidden(*args, **kwargs):
        raise AssertionError("Unchanged Capture input must not regenerate XML")
    monkeypatch.setattr(capture_lib, "generate_lib_xml", forbidden)
    # Reloading a component does not depend on the server's in-memory cache.
    component = parse_component("C2040", json.loads((DATA / "C2040.json").read_text(encoding="utf-8")))
    second = stage_component(component, cfg, capture_only=True)
    assert second.preparation_reused and second.symbol_xml == first.symbol_xml
    assert second.symbol_xml.stat().st_mtime_ns == before


@pytest.mark.parametrize("change", ["symbol", "description", "manufacturer", "mpn", "footprint", "library", "defaults", "corrupt", "missing", "version"])
def test_capture_preparation_invalidates(prepared, monkeypatch, change):
    from edakit.symbol import capture_lib, prepared as module
    component, cfg = prepared
    first = stage_component(component, cfg, capture_only=True)
    if change == "symbol":
        component.symbol.pins[0].name = "CHANGED"
    elif change in {"description", "manufacturer", "mpn"}:
        setattr(component.symbol, change, "CHANGED")
    elif change == "footprint":
        component.footprint.name = "CHANGED"
    elif change == "library":
        cfg.project_olb += ".new"
    elif change == "defaults":
        original = capture_lib.default_values_block()
        monkeypatch.setattr(capture_lib, "default_values_block", lambda: original + "\n")
    elif change == "version":
        monkeypatch.setattr(module, "CAPTURE_FORMAT_VERSION", module.CAPTURE_FORMAT_VERSION + 1)
    elif change == "corrupt":
        first.symbol_xml.write_text("corrupt", encoding="utf-8")
    else:
        first.symbol_xml.unlink()
    second = stage_component(component, cfg, capture_only=True)
    assert not second.preparation_reused
    assert "<Lib" in second.symbol_xml.read_text(encoding="utf-8")


DRIVER = r'''
set ::env(LOCALAPPDATA) [lindex $argv 1]
set ::env(EDAKIT_EXE) [lindex $argv 2]
set input [lindex $argv 3]
set project [lindex $argv 4]
set scenario [lindex $argv 5]
set ::calls 0
set ::badReadback 0
array set ::loaded {}
proc cachedPlaceNew {path part} {
    if {$::scenario eq "basename-cache"} { set pathKey [file tail $path] } else { set pathKey $path }
    if {![info exists ::loaded($pathKey)]} {
        set f [open $path r]; set ::loaded($pathKey) [read $f]; close $f
    }
    return [expr {[string first "name=\"$part\"" $::loaded($pathKey)] >= 0}]
}
proc after {args} {}
proc RegisterAction {args} {}
proc InsertXMLMenu {args} {}
proc XMATIC_XML2OLB {xml olb} {
    incr ::calls
    set f [open $xml r]; fconfigure $f -encoding utf-8
    set body [read $f]; close $f
    set f [open $olb w]; fconfigure $f -encoding utf-8 -translation lf
    puts $f "FAKE-OLB\n$body"; close $f
}
proc XMATIC_OLB2XML {olb xml} {
    incr ::calls
    if {$::badReadback} { error "readback unavailable" }
    set f [open $olb r]; fconfigure $f -encoding utf-8
    set body [read $f]; close $f
    set body [string range $body [expr {[string first "\n" $body]+1}] end]
    set f [open $xml w]; fconfigure $f -encoding utf-8 -translation lf
    puts -nonewline $f $body; close $f
}
proc exec {args} {
    incr ::calls
    array set opts [lrange $args 2 end]
    file copy -force $opts(--part) $opts(--out)
}
source [lindex $argv 0]
set key [string repeat a 64]
set keyB [string repeat b 64]
if {$scenario eq "no-readback"} { set ::badReadback 1 }
if {$scenario ne "hot-restart"} {
    set active [::edakit::buildOlb C2040 $input $project RP2040 $key]
    if {$::calls == 0} { error "cold build did not execute" }
    if {![cachedPlaceNew $active RP2040]} { error "first part not placed" }
    if {$scenario eq "warm-only"} { puts WARM; exit 0 }
}
if {$scenario eq "no-readback"} {
    if {[file exists [file join [::edakit::locateAppDir] olb_cache $key ready.meta]]} {
        error "unverified library was cached"
    }
    puts PASS; exit 0
}
if {$scenario eq "eviction"} {
    set root [file join [::edakit::locateAppDir] olb_cache]
    for {set i 1} {$i <= 129} {incr i} {
        set oldKey [format %064x $i]
        set oldDir [file join $root $oldKey]
        file mkdir $oldDir
        foreach name [list source.xml part.olb verified.olb [file tail [::edakit::placementCacheFile $oldKey]]] {
            file copy -force $active [file join $oldDir $name]
        }
        set meta [file join $oldDir ready.meta]
        ::edakit::writeKV $meta [list version 2 part_name OLD project_olb $project]
        file mtime $meta [expr {[clock seconds] - 1000 + $i}]
    }
    ::edakit::rememberPlacementOlb $key $input $project RP2040 [file join [::edakit::locateAppDir] lcsc_test.olb]
    set entries [glob -nocomplain -directory $root -types d *]
    if {[llength $entries] != 128 || ![file exists $active]} { error "cache pruning failed" }
    if {[file exists [file join $root [format %064x 1]]]} { error "oldest cache files were not removed" }
}
if {$scenario eq "legacy-cache"} {
    set dir [file dirname $active]
    file rename $active [file join $dir part.olb]
    ::edakit::writeKV [file join $dir ready.meta] [list version 1 part_name RP2040 project_olb $project]
}
if {$scenario in {switch-back pending-switch basename-cache}} {
    set other "$input.other.xml"
    set f [open $input r]; set body [read $f]; close $f
    set f [open $other w]; puts $f [string map {RP2040 SECOND} $body]; close $f
    set second [::edakit::buildOlb C2 $other $project SECOND $keyB]
    if {![cachedPlaceNew $second SECOND]} { error "second part hidden by host path cache" }
    if {$second eq $active} { error "different parts share one loaded library path" }
}
if {$scenario eq "pending-switch"} {
    proc IsSchematicViewActive {} { return 1 }
    proc ::edakit::placePart {olb args} {
        set expected [placementCacheFile [string repeat a 64]]
        if {![sameBinaryFile $olb $expected]} { error "pending placement used another part" }
        return "armed: correct part"
    }
    set response [file join [::edakit::locateQueueDir] resp_pending.resp]
    set claim [file join [::edakit::locateQueueDir] pending.work]
    ::edakit::writeKV $claim [list seq pending]
    set ::edakit::pendingPlace [list $active RP2040 1 500 500 "" $response pending $claim 0 C2040 $input $project $key]
    set ::calls 0
    ::edakit::tryPendingPlace
    array set result [::edakit::readKV $response]
    if {!$result(ok) || $::calls != 0 || [file exists $claim]} { error "pending reuse failed" }
    puts PASS; exit 0
}
if {$scenario eq "active-missing"} { file delete -force [file join [::edakit::locateAppDir] lcsc_test.olb] }
if {$scenario eq "cache-missing"} { file delete -force $active }
if {$scenario eq "corrupt"} {
    set file [::edakit::placementCacheFile $key]
    set f [open $file r]; set bytes [read $f]; close $f
    # Same-size modification must invalidate even if mtime stays unchanged.
    set f [open $file w]; puts -nonewline $f [string replace $bytes 0 0 X]; close $f
}
if {$scenario eq "source-change"} {
    set f [open $input a]; puts $f "<!-- changed -->"; close $f
}
if {$scenario eq "project-missing"} { file delete -force $project }
set ::calls 0
set result [::edakit::buildOlb C2040 $input $project RP2040 $key]
set rebuilt [expr {$scenario in {corrupt source-change project-missing cache-missing legacy-cache}}]
if {$rebuilt && ($::calls == 0 || $::edakit::lastOlbReused)} { error "did not rebuild invalid entry" }
if {!$rebuilt && ($::calls != 0 || !$::edakit::lastOlbReused)} { error "cache hit executed native work: $::calls" }
if {[file tail $result] ne "ek_[string range $key 0 23].olb"} { error "cache path is not content-addressed" }
if {![cachedPlaceNew $result RP2040]} { error "returning to the first part failed" }
puts "PASS native_calls=$::calls reused=$::edakit::lastOlbReused"
'''


@pytest.mark.parametrize("scenario", ["same", "switch-back", "active-missing", "corrupt", "source-change", "project-missing", "no-readback", "restart", "pending-switch", "cache-missing", "basename-cache", "legacy-cache", "eviction"])
def test_tcl_verified_library_reuse(tmp_path, scenario):
    from test_tcl_plugin import TCLSH, PLUGIN, PART_XML
    if not TCLSH:
        pytest.skip("Tcl unavailable")
    driver = tmp_path / "driver.tcl"
    driver.write_text(DRIVER, encoding="ascii")
    source = tmp_path / "part.xml"
    source.write_text(PART_XML, encoding="utf-8")
    exe = tmp_path / "fake.exe"
    exe.touch()
    args = [TCLSH, str(driver), str(PLUGIN), str(tmp_path / "runtime"), str(exe), str(source), str(tmp_path / "project.olb")]
    if scenario == "restart":
        warm = subprocess.run(args + ["warm-only"], capture_output=True, text=True, timeout=15)
        assert warm.returncode == 0, warm.stdout + warm.stderr
        scenario = "hot-restart"
    result = subprocess.run(args + [scenario], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout

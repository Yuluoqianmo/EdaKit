# edakit -- one-shot diagnostic (pure ASCII on purpose).
# In Capture's command window:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_diag.tcl"
# Copy everything it prints back to Claude.

puts "===== edakit diagnostic ====="

if {[llength [info commands ::edakit::showProbe]] == 0} {
    puts "PLUGIN: NOT LOADED (no ::edakit::showProbe)"
    return
}

puts "PLUGIN: namespace loaded"

foreach c {edakitProbe edakitMall edakitLog edakitDispatch} {
    if {[llength [info commands $c]]} {
        puts "CMD $c : OK (args: [info args $c])"
    } else {
        puts "CMD $c : MISSING  <-- old TCL file still installed"
    }
}

puts "TK: [expr {[llength [info commands tk_messageBox]] ? "present" : "ABSENT (no popups possible)"}]"
puts "DBO SessionLog: [expr {[llength [info commands DboState_WriteToSessionLog]] ? "present" : "absent"}]"
puts "AddAccessoryMenu: [expr {[llength [info commands AddAccessoryMenu]] ? "present" : "absent"}]"

set exe ""
catch { set exe [::edakit::locateExe] }
puts "EXE: [expr {$exe eq "" ? "(not found)" : $exe}]"
if {[info exists ::env(EDAKIT_EXE)]} {
    puts "EXE env var: $::env(EDAKIT_EXE)"
} else {
    puts "EXE env var: (not set)"
}
set marker [file join [::edakit::locateAppDir] exe_path.txt]
puts "EXE marker file: $marker"
if {[file exists $marker]} {
    set fp [open $marker r]
    puts "  content: [string trim [read $fp]]"
    close $fp
} else {
    puts "  (missing)"
}

puts "---- simulate a menu click (Capture passes arguments) ----"
if {[catch { edakitProbe menuclick } err]} {
    puts "PROBE via global wrapper FAILED: $err"
} else {
    puts "PROBE via global wrapper: returned OK (output above)"
}

puts "---- diag log file ----"
set dlog [file join [::edakit::locateAppDir] edakit.log]
puts "path: $dlog"
if {[file exists $dlog]} {
    set fp [open $dlog r]
    set body [read $fp]
    close $fp
    set lines [lrange [split $body "\n"] end-40 end]
    puts [join $lines "\n"]
} else {
    puts "(log file missing -- menu never clicked, or OLD tcl still loaded)"
}

puts "===== end of diagnostic ====="

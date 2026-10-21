# edakit -- Capture autoload entry
# Installed to <SPB>/tools/capture/tclscripts/capAutoLoad/edakitInit.tcl
# (top level of capAutoLoad -- Capture only scans that folder, not subfolders).
# Capture sources every .tcl file in capAutoLoad at startup.
#
# This file only pulls in the main logic; everything lives in edakit.tcl.
# Keep it PURE ASCII -- see the note at the top of edakit.tcl.

set _edakit_dir [file join [file dirname [info script]] "edakit"]
set _edakit_main [file join $_edakit_dir "edakit.tcl"]

if {[file exists $_edakit_main]} {
    if {[catch { source $_edakit_main } err]} {
        puts "edakit: failed to load main logic: $err"
    }
} else {
    puts "edakit: edakit.tcl not found (looked in $_edakit_dir)"
}

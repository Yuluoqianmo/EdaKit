# edakit -- CEF embedded view test (pure ASCII).
# Run in Capture's command window (mall server must be running):
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_cef_diag.tcl"
#
# Opens our mall page in a CEF (Chromium) view -- the engine Cadence itself
# uses for HTML panes (orPrm::WF_CEF). This is the "modern browser inside
# Capture" option, unlike OpenURL's IE7 tab.

puts "===== CEF view test ====="

proc tryShow {label script} {
    if {[catch { uplevel #0 $script } e]} {
        puts "$label -> ERR: $e"
    } else {
        puts "$label -> '$e'"
    }
}

# where is the mall?
set url ""
set uf [file join [::edakit::locateAppDir] url.txt]
if {[file exists $uf]} {
    set fp [open $uf r]
    set url [string trim [read $fp]]
    close $fp
}
puts "url.txt -> '$url'"
if {$url eq ""} {
    puts "NO URL: start the mall first (menu Open LCSC Mall)"
    return
}

# package availability
tryShow "package require orPrmWebComp" { package require orPrmWebComp }
tryShow "orPrm::CreateWidget exists" { expr {[llength [info commands orPrm::CreateWidget]] ? "yes" : "no"} }
tryShow "orPrm::WF_CEF value" { expr {[info exists ::orPrm::WF_CEF] ? $::orPrm::WF_CEF : "unset"} }
tryShow "orPrm::WTYPE_VIEW value" { expr {[info exists ::orPrm::WTYPE_VIEW] ? $::orPrm::WTYPE_VIEW : "unset"} }

set page "[string trimright $url /]/"
puts "opening: $page"
if {[catch {
    set wid [orPrm::CreateWidget $::orPrm::WTYPE_VIEW $::orPrm::WF_CEF]
    puts "widget id: $wid"
    orPrm::LoadResource $wid $page
    catch { orPrm::SetTitle $wid "LCSC Mall (CEF)" }
    puts "CEF view created"
} e]} {
    puts "CEF view FAILED: $e"
}

puts ">>> Is a new 'LCSC Mall (CEF)' view/tab visible? Is our styled UI shown?"
tryShow "IsSchematicViewActive (after CEF)" { IsSchematicViewActive }

puts "===== end ====="

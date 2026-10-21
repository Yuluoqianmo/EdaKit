# edakit -- tab / active-window diagnostic v2 (pure ASCII).
# Click the "LCSC Mall" tab first, then run in Capture's command window:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_tab_diag.tcl"

puts "===== tab / active window diag v2 ====="

proc tryShow {label script} {
    if {[catch { uplevel #0 $script } e]} {
        puts "$label -> ERR: $e"
    } else {
        puts "$label -> '$e'"
    }
}

tryShow "IsSchematicViewActive" { IsSchematicViewActive }
tryShow "GetActiveWindow"       { GetActiveWindow }

# candidate: activate a window by partial name / extension
tryShow "capFindActivateWindow(noarg)" { capFindActivateWindow }
tryShow "capFindWindowExtension(noarg)" { capFindWindowExtension }
tryShow "capGetActiveWindow(noarg)" { capGetActiveWindow }
tryShow "capGetActiveDocument(noarg)" { capGetActiveDocument }
tryShow "capGetActiveView(noarg)" { capGetActiveView }

# Try to activate the schematic page window by name guesses
foreach name {PAGE1 "PAGE1*" DSN Schematic "Schematic Page"} {
    tryShow "capFindActivateWindow $name" [list capFindActivateWindow $name]
    tryShow "  -> IsSchematicViewActive" { IsSchematicViewActive }
}

# orPrm: CEF widget availability (used by Cadence itself for HTML panes)
foreach c {orPrm::CreateWidget orPrm::CreateModalDialog orPrm::LoadResource orPrm::SetTitle orPrm::GetNextId} {
    puts "CMD $c : [expr {[llength [info commands $c]] ? "yes" : "no"}]"
}
tryShow "package require orPrm" { package require orPrm }
puts "orPrm after require: [expr {[llength [info commands orPrm::CreateWidget]] ? "yes" : "no"}]"
tryShow "orPrm::WF_CEF" { expr {[info exists ::orPrm::WF_CEF] ? $::orPrm::WF_CEF : "unset"} }
tryShow "orPrm::WF_WEBKIT" { expr {[info exists ::orPrm::WF_WEBKIT] ? $::orPrm::WF_WEBKIT : "unset"} }

puts "===== end ====="

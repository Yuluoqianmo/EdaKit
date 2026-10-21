# edakit -- menu command diagnostic (pure ASCII on purpose).
# In Capture's command window:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_menu_diag.tcl"

puts "===== menu diag ====="

foreach c {GetMenu GetSubMenu GetMenuItemCount GetMenuItemId GetMenuItemString GetMenuString \
           GetMenuState GetSystemMenu Menu MenuCommand orPrmGetMenuId populateMenuItems \
           GetAppTypeModelAppMenu RefreshMenu PluginMenuId} {
    if {[llength [info commands $c]]} {
        if {[catch {$c} e]} {
            puts "USAGE $c : $e"
        } else {
            puts "USAGE $c : (no-arg call OK)"
        }
    } else {
        puts "USAGE $c : MISSING"
    }
}

puts "---- try native capture command through Tcl helpers ----"
foreach expr {{DboTclUtils_EvalTCLCommand {place part}} {capOrigCommandExec {place part}}} {
    if {[catch {eval $expr} e]} {
        puts "> $expr -> ERR: $e"
    } else {
        puts "> $expr -> '$e'"
    }
}

puts "---- dialog commands ----"
foreach c {PlacePartWithDialog PlacePartClickPlace PlacePartSelectPartByNameAndLib} {
    if {[llength [info commands $c]]} {
        if {[catch {$c} e]} { puts "TRY $c : $e" } else { puts "TRY $c : returned '$e'" }
    }
}

puts "===== end ====="

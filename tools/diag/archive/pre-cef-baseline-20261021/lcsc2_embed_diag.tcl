# edakit -- embedded browser probe (pure ASCII on purpose).
# iDesign-style "inside OrCAD" UI needs Capture's own HTML pane. Capture 17.2
# ships OpenURL (used by the OrCAD MarketPlace) and OpenStartPage. Test them.
#
# Before running, start the mall (menu: Open LCSC Mall), copy the URL from the
# browser address bar, then in Capture's command window:
#   set ::mallUrl "http://127.0.0.1:PORT/"
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_embed_diag.tcl"

puts "===== embedded browser probe ====="

foreach pat {*URL* *Html* *Web* *Browser* *StartPage* *Dialog*} {
    puts "CMDS $pat : [lsort [info commands $pat]]"
}

if {![info exists ::mallUrl] || $::mallUrl eq ""} {
    puts "SET ::mallUrl FIRST (e.g. set ::mallUrl \"http://127.0.0.1:8080/\")"
    return
}
puts "mallUrl = $::mallUrl"
puts "OpenURL present: [expr {[llength [info commands OpenURL]] ? "yes" : "NO"}]"
puts "OpenStartPage present: [expr {[llength [info commands OpenStartPage]] ? "yes" : "NO"}]"

puts "---- try OpenURL ----"
if {[catch { OpenURL $::mallUrl "LCSC Mall" } e]} {
    puts "OpenURL(url, label) -> ERR: $e"
} else {
    puts "OpenURL(url, label) -> OK: $e"
    puts ">>> Did a pane/window open inside Capture? Does the mall UI render?"
}

puts "---- try OpenURL with 3 args ----"
catch { OpenURL $::mallUrl "LCSC Mall" 1 } e2
puts "OpenURL 3 args -> $e2"

puts "---- try OpenStartPage (control: does an HTML pane exist at all?) ----"
catch { OpenStartPage } e3
puts "OpenStartPage -> $e3"

puts "===== end ====="

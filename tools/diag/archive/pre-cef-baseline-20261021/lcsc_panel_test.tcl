# edakit -- panel flow with a NORMALIZED library (pure ASCII).
# Before running: delete ALL parts on this page (Ctrl+A, Delete), and close the
# Place Part panel (X). Then run:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc_panel_test.tcl"
# After 'panel ready', move the mouse over the canvas and click once.

puts "===== panel flow test (normalized lib) ====="

set lib "C:/Users/32657/AppData/Local/edakit/cmp_bad_lib.olb"
if {![file exists $lib]} {
    puts "missing $lib -- run lcsc_compare_diag.tcl first"
    return
}
puts "library: $lib  (roundtripped copy of LCSC_TEST.OLB)"

catch { PlacePartAddLib $lib } e1
puts "AddLib -> $e1"
catch { MenuCommand 13958 } e2
puts "Menu 13958 -> $e2"

proc panelArm {} {
    set libi 0
    catch { set libi [PlacePartGetLibIndex] }
    catch { PlacePartSelectLibIndex $libi }
    catch { PlacePartSelectPartIndex 0 }
    puts "selected lib=$libi part=0"
    catch { PlacePartClickPlace } e
    puts "ClickPlace -> $e   >>> MOVE MOUSE OVER CANVAS AND CLICK ONCE <<<"
}
after 900 panelArm

puts "===== end (wait for the message, then click) ====="

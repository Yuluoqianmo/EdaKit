# edakit -- place panel index probe (pure ASCII).
# The Place Part panel must already be open and showing our place_*.olb.
# Run in Capture's command window, then MOVE THE MOUSE OVER THE SCHEMATIC:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc2_place_diag.tcl"

puts "===== place panel index probe ====="
puts "lib index now: [PlacePartGetLibIndex]  part index now: [PlacePartGetPartIndex]"

# 1) select by index (what the plugin will do)
puts "---- SelectLibIndex 4 / SelectPartIndex 1 ----"
catch { PlacePartSelectLibIndex 4 } e1 ; puts "  lib  -> $e1"
after 400
catch { PlacePartSelectPartIndex 1 } e2 ; puts "  part -> $e2"
after 400
catch { PlacePartClickPlace } e3 ; puts "  click -> $e3"

puts ">>> Move the mouse over the schematic now. Symbol following?"
puts "===== end ====="

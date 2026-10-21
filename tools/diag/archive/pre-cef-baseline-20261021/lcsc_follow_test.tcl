# edakit -- v12 symbol + follow-cursor panel test (pure ASCII).
# BEFORE RUNNING (important):
#   1. Fully restart Capture (clears the in-session library cache and Design
#      Cache leftovers).  Open a NEW blank schematic page.
#   2. Run this in the command window:
#      source ".../lcsc_follow_test.tcl"
#   3. After 'ARMED', move the mouse over the canvas and CLICK once.
#
# What it does:
#   * rebuilds lcsc_test.olb from the v12 symbol XML (numbers all self-drawn,
#     native pin numbers globally off -- fixes the double-number bug)
#   * normalizes the library (OLB2XML -> XML2OLB), which we know draws right
#   * opens the Place Part panel, selects the part, arms click-to-place

puts "===== v12 + follow-cursor test ====="

set xml "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/RP2040_v12.olb.xml"
set olb "C:/Users/32657/AppData/Local/edakit/lcsc_test.olb"
set rt  "C:/Users/32657/AppData/Local/edakit/lcsc_test.norm.xml"

if {![file exists $xml]} { puts "missing $xml"; return }

# 1) fresh library from v12 XML
catch { file delete -force $olb }
catch { XMATIC_XML2OLB $xml $olb } e1
puts "write -> exists=[file exists $olb] err='$e1'"

# 2) normalize (Capture's own rewrite) -- proven to draw correctly
catch { file delete -force $rt }
catch { XMATIC_OLB2XML $olb $rt } e2
if {[file exists $rt]} {
    catch { file rename -force $olb "${olb}.old" }
    catch { file delete -force "${olb}.old" }
    catch { XMATIC_XML2OLB $rt $olb } e3
    catch { file delete -force $rt }
    puts "normalize -> exists=[file exists $olb] err='$e3'"
}

# 3) open the panel and select our part
catch { PlacePartAddLib $olb } e4
puts "AddLib -> $e4"
catch { MenuCommand 13958 } e5
puts "Menu 13958 -> $e5"

proc armV12 {} {
    set libi 0
    catch { set libi [PlacePartGetLibIndex] }
    catch { PlacePartSelectLibIndex $libi }
    catch { PlacePartSelectPartIndex 0 }
    puts "selected lib=$libi part=0"
    catch { PlacePartClickPlace } e
    puts "ClickPlace -> $e  >>> MOVE MOUSE OVER CANVAS AND CLICK ONCE <<<"
}
after 900 armV12

puts "===== end (wait for ARMED message) ====="

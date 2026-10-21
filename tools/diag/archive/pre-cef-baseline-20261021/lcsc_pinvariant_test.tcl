# edakit -- pin-geometry variant test (pure ASCII).
# The 57-pin symbol looks right in the PART EDITOR but pins render scattered
# once PLACED on a schematic. This places four variants side by side so we can
# see which pin definition survives placement:
#   V1: pin length 10 units, IsLong=1   (current)
#   V2: pin length 10 units, IsLong=0
#   V3: pin length 30 units, IsLong=0   (same as Cadence's own discrete R)
#   V4: pin length 30 units, IsLong=1
#
# Run in Capture's command window (a schematic page must be ACTIVE):
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc_pinvariant_test.tcl"
# Then take a screenshot of the whole page (they are placed in a row).

puts "===== pin variant test ====="

set base "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/pin_variants"
set out  "C:/Users/32657/AppData/Local/edakit"

set jobs {
    1 v1_cur.xml              1.0
    2 v2_short_flag.xml       3.6
    3 v3_len30.xml            6.2
    4 v4_len30_longflag.xml   8.8
}

foreach {n f x} $jobs {
    set olb "$out/pinv_$n.olb"
    catch { file delete -force $olb }
    if {[catch { XMATIC_XML2OLB "$base/$f" $olb } e]} {
        puts "V$n XML2OLB ERR: $e"
        continue
    }
    if {![file exists $olb]} {
        puts "V$n: no .olb written"
        continue
    }
    catch { PlacePart $x 2.0 $olb "RP2040" "" FALSE } e
    puts "V$n placed at ($x, 2.0): $e"
}

catch { ZoomRedraw }
catch { ZoomAll }
catch { ZoomRedraw }
puts ">>> V1..V4 are in a row at y=2 inch. Screenshot the whole page."
puts "===== end ====="

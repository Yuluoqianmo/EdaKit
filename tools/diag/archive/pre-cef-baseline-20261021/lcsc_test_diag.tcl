# edakit -- lcsc_test.olb roundtrip + direct placement (pure ASCII).
# Run in Capture's command window with a schematic page ACTIVE:
#   source "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/tools/diag/lcsc_test_diag.tcl"
#
# 1) dumps lcsc_test.olb back to XML (rt.xml) so we can compare byte-level pin data
# 2) places the SAME library part directly with PlacePart at (1, 1) inch
# If the direct one looks correct while the panel one looks scattered, the
# panel path is reprocessing pins differently.

puts "===== lcsc_test.olb diag ====="

set app "C:/Users/32657/AppData/Local/edakit"
set olb "$app/lcsc_test.olb"
set rt  "$app/lcsc_rt.xml"

if {[file exists $olb]} {
    puts "olb: [file size $olb] bytes, mtime [clock format [file mtime $olb] -format {%Y-%m-%d %H:%M:%S}]"
} else {
    puts "olb MISSING: $olb"
}

catch { file delete -force $rt }
catch { XMATIC_OLB2XML $olb $rt } e
if {[file exists $rt]} {
    set fp [open $rt r]
    fconfigure $fp -encoding utf-8
    set body [read $fp]
    close $fp
    set pins [regexp -all -inline {<SymbolPinScalar>} $body]
    set longs [regexp -all -inline {<IsLong><Defn val="([01])"/>} $body]
    puts "roundtrip: $rt  pins=[llength $pins]"
    set vals {}
    foreach {- v} $longs { lappend vals $v }
    puts "IsLong values: [lsort -unique $vals]"
    if {[regexp {hotptX="(-?\d+)" hotptY="(-?\d+)" name="([^"]*)" position="(\d+)" startX="(-?\d+)" startY="(-?\d+)"} $body -> hx hy nm pos sx sy]} {
        puts "first pin: $nm hotpt=($hx,$hy) start=($sx,$sy) len=[expr {abs($hx-$sx)+abs($hy-$sy)}]"
    }
} else {
    puts "OLB2XML produced no file (err='$e')"
}

puts "---- direct PlacePart from lcsc_test.olb at (1,1) ----"
catch { PlacePart 1.0 1.0 "[string map {\\ /} $olb]" "RP2040" "" FALSE } e2
puts "err='$e2'"
catch { ZoomRedraw }
catch { ZoomAll }
catch { ZoomRedraw }
puts ">>> Is the part at the top-left corner drawn CORRECTLY (pins on the body)?"
puts "===== end ====="

# edakit -- compare two in-session libraries (pure ASCII).
# Run with a schematic page ACTIVE:
#   source ".../lcsc_compare_diag.tcl"
#
# Roundtrips PINV_1.OLB (drawn correctly) and LCSC_TEST.OLB (drawn scattered)
# back to XML under DIFFERENT output names, then places each from its own new
# path so PlacePart's per-path cache is bypassed. Watch the two parts.

puts "===== compare diag ====="

set app "C:/Users/32657/AppData/Local/edakit"

foreach {tag olb x} {good PINV_1.OLB 1.0 bad LCSC_TEST.OLB 4.0} {
    set rt "$app/cmp_${tag}.xml"
    file delete -force $rt
    catch { XMATIC_OLB2XML "$app/$olb" $rt } e
    puts "$tag roundtrip ($olb): exists=[file exists $rt] err='$e'"
    # fresh library name so the panel/PlacePart cache is not reused
    set fresh "$app/cmp_${tag}_lib.olb"
    file delete -force $fresh
    catch { XMATIC_XML2OLB $rt $fresh } e2
    puts "$tag rewrite -> $fresh exists=[file exists $fresh] err='$e2'"
    catch { PlacePart $x 1.0 "$fresh" "RP2040" "" FALSE } e3
    puts "$tag placed at ($x,1.0): $e3"
}

catch { ZoomRedraw }
catch { ZoomAll }
catch { ZoomRedraw }
puts ">>> LEFT = roundtrip of the GOOD library, RIGHT = roundtrip of LCSC_TEST."
puts ">>> Which one draws correctly?"
puts "===== end ====="

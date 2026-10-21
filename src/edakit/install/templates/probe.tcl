# =============================================================================
# edakit capability probe  --  run this inside OrCAD Capture
#
#   source "C:/path/to/probe.tcl"
#
# Or, if the command window is unusable, copy it into
#   <SPB>/tools/capture/tclscripts/capAutoLoad/
# and restart Capture -- it runs at startup and prints to the startup log.
#
# It does three things:
#   1. Checks whether the commands needed to write .olb / place parts exist
#   2. If XMATIC_* is missing, tries to load Capture's DBO Tcl extension and
#      checks again (some installs simply do not load it by default, and a
#      bare MISSING would be a false alarm)
#   3. Prints environment details (CDSROOT, Tcl version, loaded extensions)
#
# PURE ASCII ONLY. Capture's Tcl reads files using the system code page
# (cp936 on a Chinese Windows). UTF-8 Chinese bytes decoded as GBK can yield
# '{' / '}' / '\' as trail bytes and break the parser with "missing close-brace".
#
# Everything runs inside catch -- a probe must never take Capture down.
# =============================================================================

namespace eval ::lcsc2probe {
    variable LAST
}

proc ::lcsc2probe::has {name} {
    return [expr {[llength [info commands $name]] > 0 || [llength [info commands ::$name]] > 0}]
}

proc ::lcsc2probe::say {msg} {
    puts $msg
}

# Directories that might hold the DLL providing XMATIC_* (a short list,
# deliberately no recursive scan of the whole disk).
proc ::lcsc2probe::searchDirs {} {
    set dirs {}

    foreach v {CDSROOT CONCEPTHDL_CDS_ROOT} {
        if {[info exists ::env($v)] && $::env($v) ne ""} {
            set r $::env($v)
            lappend dirs $r
            foreach sub {
                {tools capture}
                {tools capture bin}
                {tools capture tclscripts}
                {tools capture tclscripts capAutoLoad}
                {tools bin}
                {tools lib}
                {bin}
            } {
                lappend dirs [eval file join [list $r] $sub]
            }
        }
    }

    # walk up a couple of levels from this script
    catch {
        set here [file dirname [file normalize [info script]]]
        lappend dirs $here
        lappend dirs [file dirname $here]
        lappend dirs [file dirname [file dirname $here]]
    }

    set out {}
    unset -nocomplain seen
    array set seen {}
    foreach d $dirs {
        set n [string tolower $d]
        if {$n eq "" || [info exists seen($n)]} { continue }
        set seen($n) 1
        lappend out $d
    }
    return $out
}

proc ::lcsc2probe::findDlls {} {
    set out {}
    unset -nocomplain seen
    array set seen {}
    foreach d [searchDirs] {
        if {![file isdirectory $d]} { continue }
        if {[catch {glob -nocomplain -directory $d -types f *.dll} files]} { continue }
        foreach f $files {
            set b [string tolower [file tail $f]]
            if {[string match *dbotcl* $b] || [string match *xmatic* $b] || [string match *captcl* $b]} {
                set n [string tolower $f]
                if {[info exists seen($n)]} { continue }
                set seen($n) 1
                lappend out $f
            }
        }
    }
    return $out
}

proc ::lcsc2probe::tryLoad {dll} {
    set base [file rootname [file tail $dll]]

    set cands [list $base]
    if {[string match -nocase lib* $base] && [string length $base] > 3} {
        lappend cands [string range $base 3 end]
    }

    set errs {}
    foreach pkg $cands {
        if {![catch {load $dll $pkg} err]} { return "loaded as $pkg" }
        lappend errs $err
    }
    if {![catch {load $dll} e2]} { return "loaded (auto)" }
    lappend errs $e2
    return "failed: [lindex $errs 0]"
}

proc ::lcsc2probe::run {} {
    variable LAST

    say ""
    say "================================================================"
    say "  edakit capability probe"
    say "================================================================"
    say "  Tcl        : [info patchlevel]"
    say "  script     : [info script]"
    say "  pid        : [pid]"
    foreach v {CDSROOT CONCEPTHDL_CDS_ROOT HOME} {
        if {[info exists ::env($v)]} { say [format "  %-10s : %s" $v $::env($v)] }
    }

    # ---- 1. command check ----
    set cmds {
        XMATIC_XML2OLB            {XML -> OLB library build (required to place)}
        XMATIC_OLB2XML            {OLB -> XML read back (for accumulating lib)}
        PlacePart                 {place a part on the schematic (required)}
        PlacePartEx               {native interactive placement (preferred)}
        PlaceNew                  {native PSpice Model App placement entry}
        InsertXMLMenu             {top-level EdaKit menu insertion}
        RegisterAction            {register menu items}
        capCreatePartsFromData    {build part from data (fallback)}
        capPlacePartInteractive   {interactive placement (follow cursor, optional)}
        PlacePartInteractive      {interactive placement (alias, optional)}
        capPlacePart              {placement (alias, optional)}
        NewDisplayProp            {write part properties}
        axlOpenDesign             {Allegro SKILL function, MISSING is normal}
    }

    say ""
    say "  ---- commands ----"
    foreach {c desc} $cmds {
        if {[has $c]} {
            say [format "  %-26s OK       %s" $c $desc]
        } else {
            say [format "  %-26s MISSING  %s" $c $desc]
        }
    }

    # ---- 2. try to load the DBO Tcl extension ----
    if {![has XMATIC_XML2OLB]} {
        say ""
        say "  XMATIC_XML2OLB not registered -- trying to load Capture's DBO Tcl extension ..."

        set dlls [findDlls]
        if {[llength $dlls] == 0} {
            say "    no *DboTcl* / *xmatic* / *captcl*.dll found in the usual places"
            say "    directories checked:"
            foreach d [searchDirs] {
                if {[file isdirectory $d]} { say "      $d" }
            }
        } else {
            foreach dll $dlls {
                set r [tryLoad $dll]
                say [format "    %-70s %s" $dll $r]
            }
        }

        if {[has XMATIC_XML2OLB]} {
            say "    => XMATIC_XML2OLB is available after loading"
        } else {
            say "    => still missing."
        }
    }

    # ---- 3. loaded extensions ----
    say ""
    say "  ---- loaded extensions (info loaded) ----"
    if {[catch {info loaded} loaded]} {
        say "    (unavailable)"
    } else {
        if {[llength $loaded] == 0} {
            say "    (none)"
        } else {
            foreach pair $loaded { say "    [lindex $pair 0]" }
        }
    }

    # ---- 4. verdict ----
    say ""
    say "  ---- verdict ----"
    if {[has XMATIC_XML2OLB] && [has XMATIC_OLB2XML]} {
        say {  [READY]   both .olb build and read-back work -- the full flow is possible.}
        set LAST "full"
    } elseif {[has XMATIC_XML2OLB]} {
        say {  [PARTIAL] can build .olb but cannot read it back -- the accumulating}
        say {            project library degrades to overwrite-each-time.}
        set LAST "no-readback"
    } else {
        say {  [BLOCKED] XMATIC_XML2OLB is not available -- symbols cannot be written as .olb.}
        say "            Please send the whole output above (especially the 'trying to load' lines)."
        set LAST "no-xmatic"
    }
    if {[has PlacePart]} {
        say "  PlacePart: OK"
    } else {
        say "  PlacePart: MISSING -- placement will fail, please send this output."
    }
    say "================================================================"
    say ""
}

catch { ::lcsc2probe::run }

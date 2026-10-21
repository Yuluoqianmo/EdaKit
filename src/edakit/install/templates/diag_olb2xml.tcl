# =============================================================================
# edakit -- diagnose XMATIC_OLB2XML
#
# Run inside OrCAD Capture's command window:
#
#   set lcsc_olb "D:/cadence/ref.olb"
#   set lcsc_xml "D:/cadence/ref.xml"
#   source "C:/path/to/diag_olb2xml.tcl"
#
# It checks the input file, the output directory, runs the conversion inside a
# catch, and then reports what actually landed on disk. If the conversion
# silently does nothing (some builds return a DboState handle without writing
# anything), this tells you where to look next.
#
# PURE ASCII ONLY -- Capture reads .tcl with the system code page.
# =============================================================================

if {![info exists lcsc_olb]} { set lcsc_olb "D:/cadence/ref.olb" }
if {![info exists lcsc_xml]} { set lcsc_xml "D:/cadence/ref.xml" }

namespace eval ::lcsc2diag {}

# NOTE: never put [bracketed] text inside a double-quoted string in Tcl --
# that is command substitution. All labels below go through format+braces.
proc ::lcsc2diag::line {level msg} {
    puts [format {  [%-4s] %s} $level $msg]
}

proc ::lcsc2diag::say {msg} { puts $msg }

proc ::lcsc2diag::run {olb xml} {
    say ""
    say "================================================================"
    say "  XMATIC_OLB2XML diagnostic"
    say "================================================================"
    line info "input  (.olb) : $olb"
    line info "output (.xml) : $xml"
    say ""

    # ---- 1. command availability ----
    if {[llength [info commands XMATIC_OLB2XML]]} {
        line ok "XMATIC_OLB2XML is defined"
    } else {
        line FAIL "XMATIC_OLB2XML is NOT defined -- run probe.tcl first"
        return
    }

    # ---- 2. input file ----
    set okInput 1
    if {[file exists $olb]} {
        set sz [file size $olb]
        line ok "input exists, size = $sz bytes"
        if {$sz == 0} {
            line warn "input is 0 bytes -- the library is empty"
            set okInput 0
        }
    } else {
        line FAIL "input file does not exist: $olb"
        say "         -> open Capture, confirm the library really lives at this path"
        say "         -> File > Open > Library, then read the full path from the title bar"
        set okInput 0

        # Look for .olb files that DO exist -- user probably saved it elsewhere
        say ""
        say "  Searching for existing .olb files ..."
        set dirs [list [pwd]]
        lappend dirs [file dirname $olb]
        foreach v {HOME USERPROFILE CDSROOT} {
            if {[info exists ::env($v)] && $::env($v) ne ""} {
                lappend dirs $::env($v)
                lappend dirs [file join $::env($v) ".."]
            }
        }
        unset -nocomplain seen
        array set seen {}
        set found 0
        foreach d $dirs {
            if {![file isdirectory $d]} { continue }
            if {[catch {glob -nocomplain -directory $d -types f *.olb} files]} { continue }
            # one level down too -- libraries often sit in a subfolder
            catch {
                foreach sub [glob -nocomplain -directory $d -types d *] {
                    foreach f2 [glob -nocomplain -directory $sub -types f *.olb] {
                        lappend files $f2
                    }
                }
            }
            foreach f $files {
                set key [string tolower $f]
                if {[info exists seen($key)]} { continue }
                set seen($key) 1
                incr found
                if {$found <= 40} {
                    say "    [format {%10d} [file size $f]] B  [file mtime $f]  $f"
                }
            }
        }
        if {$found == 0} {
            say "    (none found in the current directory or the usual data folders)"
            say ""
            say "  You probably have not created the reference library yet. In Capture:"
            say "    1. File > New > Library        (a Library1.olb appears on the left)"
            say "    2. right-click that library > New Part"
            say "       name REF, Parts per Pkg = 1"
            say "    3. Place > Rectangle, then Place > Pin twice (numbers 1 and 2)"
            say "    4. File > Save As   ->  D:/cadence/ref.olb"
        } else {
            say ""
            say "  If one of the above is your reference library, rerun with:"
            say "    set lcsc_olb <that full path>"
            say "    source <this script>"
        }
    }

    # ---- 3. output directory (the most common silent failure) ----
    set outDir [file dirname $xml]
    if {[file isdirectory $outDir]} {
        line ok "output directory exists: $outDir"
    } else {
        line warn "output directory does NOT exist: $outDir"
        if {![catch {file mkdir $outDir} err]} {
            say "         -> created it for you"
        } else {
            line warn "could not create it: $err"
        }
    }
    if {[file exists $xml]} {
        set old [file size $xml]
        line info "an old file is already there, size = $old"
        catch { file delete -force $xml }
        say "         -> deleted it so the result is unambiguous"
    }

    if {!$okInput} {
        say ""
        say "  Stopped: fix the input file first, then run this again."
        say "================================================================"
        return
    }

    # ---- 4. run it ----
    say ""
    say "  running: XMATIC_OLB2XML {$olb} {$xml}"
    set t0 [clock milliseconds]
    set ret ""
    if {[catch {set ret [XMATIC_OLB2XML $olb $xml]} err]} {
        line FAIL "the command raised an error:"
        say "         $err"
    } else {
        say "  returned: [string range $ret 0 80]"
    }
    say "  took: [expr {[clock milliseconds] - $t0}] ms"

    # ---- 5. what landed on disk ----
    say ""
    if {[file exists $xml]} {
        set sz [file size $xml]
        line ok "output written, size = $sz bytes"
        if {$sz < 100} {
            line warn "suspiciously small; likely an empty library"
            catch {
                set fp [open $xml r]
                fconfigure $fp -encoding utf-8
                say "         content: [string range [read $fp] 0 300]"
                close $fp
            }
        }
    } else {
        line FAIL "no output file at $xml"
        say ""
        say "  Looking for .xml files nearby ..."
        foreach d [list [pwd] [file dirname $olb] $outDir] {
            if {![file isdirectory $d]} { continue }
            if {[catch {glob -nocomplain -directory $d -types f *.xml} files]} { continue }
            foreach f $files {
                say "    [file mtime $f]  $f"
            }
        }
        say ""
        say "  If nothing new appeared, this build may ignore the second argument."
        say "  Try it with a relative name and then look in the current directory:"
        say "    XMATIC_OLB2XML {$olb} ref.xml"
        say "    pwd"
    }

    say "================================================================"
    say ""
}

catch { ::lcsc2diag::run $lcsc_olb $lcsc_xml }

# =============================================================================
# edakit -- diagnose XMATIC_XML2OLB
#
# The reverse of diag_olb2xml: we hand it a library XML and expect a .olb.
# Same trap as before -- it returns a DboState handle even when nothing is
# written, so "it returned something" proves nothing.
#
# Run inside OrCAD Capture's command window:
#
#   set lcsc_xml "C:/.../dist/testlib/R0603.olb.xml"
#   set lcsc_out "D:/cadence/lcsc_test.olb"
#   set lcsc_ref "D:/cadence/ref.xml"          ;# optional, for the round-trip test
#   source "C:/.../dist/diag_xml2olb.tcl"
#
# It runs several variants and reports which one (if any) actually produces a
# file. That is the fastest way to learn this command's real contract.
#
# PURE ASCII ONLY.
# =============================================================================

if {![info exists lcsc_xml]} { set lcsc_xml "C:/Users/32657/AppData/Local/Claude-3p/local-agent-mode-sessions/436c78be/00000000/9e697ef4/outputs/edakit/dist/testlib/R0603.olb.xml" }
if {![info exists lcsc_out]} { set lcsc_out "D:/cadence/lcsc_test.olb" }
if {![info exists lcsc_ref]} {
    set lcsc_ref [file join [file dirname $lcsc_out] "ref.xml"]
}

namespace eval ::lcsc2d2 {}

proc ::lcsc2d2::say {msg} { puts $msg }

proc ::lcsc2d2::line {level msg} {
    puts [format {  [%-4s] %s} $level $msg]
}

# Snapshot of every file in a directory: {name -> "size mtime"}
proc ::lcsc2d2::snapshot {dir} {
    set snap [dict create]
    if {![file isdirectory $dir]} { return $snap }
    if {[catch {glob -nocomplain -directory $dir -types f *} files]} { return $snap }
    foreach f $files {
        catch { dict set snap [file tail $f] "[file size $f] [file mtime $f]" }
    }
    return $snap
}

# Which files appeared or changed since the snapshot
proc ::lcsc2d2::diff {before after} {
    set changed {}
    dict for {name info} $after {
        if {![dict exists $before $name] || [dict get $before $name] ne $info} {
            lappend changed [list $name $info]
        }
    }
    return $changed
}

proc ::lcsc2d2::checkDir {dir label} {
    if {[file isdirectory $dir]} {
        line ok "$label exists: $dir"
        return 1
    }
    line warn "$label does NOT exist: $dir"
    if {![catch {file mkdir $dir} err]} {
        say "         -> created it"
        return 1
    }
    line warn "could not create it: $err"
    return 0
}

proc ::lcsc2d2::attempt {label script} {
    say ""
    say "  --- $label ---"
    set t0 [clock milliseconds]
    set ret ""
    set raised 0
    if {[catch {set ret [uplevel 1 $script]} err]} {
        set raised 1
        line info "raised: $err"
    } else {
        say "  returned: [string range $ret 0 70]"
    }
    say "  took: [expr {[clock milliseconds] - $t0}] ms"
    return [list $raised $ret]
}

proc ::lcsc2d2::run {xml out ref} {
    say ""
    say "================================================================"
    say "  XMATIC_XML2OLB diagnostic"
    say "================================================================"
    line info "input  (.xml) : $xml"
    line info "output (.olb) : $out"
    line info "reference xml : $ref"
    say ""

    if {[llength [info commands XMATIC_XML2OLB]]} {
        line ok "XMATIC_XML2OLB is defined"
    } else {
        line FAIL "XMATIC_XML2OLB is NOT defined -- run probe.tcl first"
        return
    }

    # ---- input ----
    if {![file exists $xml]} {
        line FAIL "input XML does not exist: $xml"
        return
    }
    set xmlSize [file size $xml]
    line ok "input exists, size = $xmlSize bytes"
    catch {
        set fp [open $xml r]
        fconfigure $fp -encoding utf-8
        set head [string range [read $fp 400] 0 160]
        close $fp
        say "         head: [string map {\n { }} $head]"
    }

    set outDir [file dirname $out]
    if {![checkDir $outDir "output directory"]} { return }

    if {[file exists $out]} {
        line info "an old output file exists, size = [file size $out] -- deleting it"
        catch { file delete -force $out }
    }

    set beforeOut [snapshot $outDir]
    set beforePwd [snapshot [pwd]]

    # ---- variant 1: the documented order ----
    attempt "1) XMATIC_XML2OLB {xml} {olb}" [list XMATIC_XML2OLB $xml $out]
    set got1 [diff $beforeOut [snapshot $outDir]]
    set gotP [diff $beforePwd [snapshot [pwd]]]
    set ok1 0
    if {[file exists $out]} {
        line ok "file appeared: $out ([file size $out] bytes)"
        set ok1 1
    } else {
        line FAIL "no file at $out"
    }
    if {[llength $gotP]} {
        say "  files changed in the current directory:"
        foreach c $gotP { say "    [lindex $c 0]  ([lindex $c 1])" }
    }
    if {[llength $got1]} {
        say "  files changed in [file dirname $out]:"
        foreach c $got1 { say "    [lindex $c 0]  ([lindex $c 1])" }
    }

    if {!$ok1} {
        # ---- variant 1b: give the library a name ----
        # Our generator writes "<Defn/>" when it does not know the target path.
        # The reference file has <Defn name="D:/cadence/ref.olb"/>, so Capture
        # may well require the name to be there (and to match the output).
        set patched [file rootname $xml]_named.xml
        set patchedOK 0
        if {[catch {
            set fp [open $xml r]
            fconfigure $fp -encoding utf-8
            set body [read $fp]
            close $fp
            set at [string first "<Lib" $body]
            if {$at >= 0} {
                set dfn [string first "<Defn/>" $body $at]
                if {$dfn < 0} { set dfn [string first "<Defn />" $body $at] }
                if {$dfn >= 0} {
                    set endAt [string first ">" $body $dfn]
                    set libName [string map {\\ /} $out]
                    set body [string replace $body $dfn $endAt "<Defn name=\"$libName\"/>"]
                    set fo [open $patched w]
                    fconfigure $fo -encoding utf-8 -translation lf
                    puts -nonewline $fo $body
                    close $fo
                    set patchedOK 1
                }
            }
        } err]} {
            line warn "could not patch a named copy: $err"
        }
        if {$patchedOK} {
            catch { file delete -force $out }
            line info "patched copy with <Defn name...> written to [file tail $patched]"
            attempt "1b) with a library name in <Defn name=...>" [list XMATIC_XML2OLB $patched $out]
            if {[file exists $out]} {
                line ok "FILE APPEARED: $out ([file size $out] bytes)"
                say "         => the empty <Defn/> was the problem."
                set ok1 1
            }
        }

        if {!$ok1} {
            # ---- variant 2: reversed argument order ----
            set rev [file rootname $out]_rev.olb
            attempt "2) reversed: XMATIC_XML2OLB {olb} {xml}" [list XMATIC_XML2OLB $rev $xml]
            if {[file exists $rev]} {
                line ok "REVERSED ORDER WORKS: $rev ([file size $rev] bytes)"
            } else {
                line info "reversed order produced nothing either"
            }
            catch { file delete -force $rev; catch { file delete -force $out } }

            # ---- variant 3: target must already exist ----
            if {[file exists $ref]} {
                set dir [file dirname $out]
                set sibling ""
                # NOTE: catch returns 0 on success -- do not put the glob result
                # check inside the catch condition (it would silently never run).
                set olbs {}
                catch {set olbs [glob -nocomplain -directory $dir -types f *.olb]}
                if {[llength $olbs]} { set sibling [lindex $olbs 0] }
                if {$sibling ne ""} {
                    catch { file copy -force $sibling $out }
                    if {[file exists $out]} {
                        line info "seeded target from [file tail $sibling] before converting"
                        set sz0 [file size $out]
                        set mt0 [file mtime $out]
                        attempt "3) convert into an existing .olb" [list XMATIC_XML2OLB $xml $out]
                        if {[file exists $out]} {
                            set sz1 [file size $out]
                            set mt1 [file mtime $out]
                            if {$sz1 != $sz0 || $mt1 != $mt0} {
                                line ok "target WAS written: size $sz0 -> $sz1"
                            } else {
                                line FAIL "target untouched (still $sz1 bytes, same mtime) -- nothing was written"
                            }
                        }
                    }
                }
            }

            # ---- variant 4: round-trip the reference XML ----
            if {[file exists $ref]} {
                set rt [file join [file dirname $out] "roundtrip.olb"]
                catch { file delete -force $rt }
                attempt "4) round-trip: ref.xml -> roundtrip.olb" [list XMATIC_XML2OLB $ref $rt]
                if {[file exists $rt]} {
                    line ok "ROUND-TRIP WORKS: $rt ([file size $rt] bytes)"
                    say "         => the command itself is fine; our generated XML is what it rejects."
                } else {
                    line FAIL "round-trip produced nothing"
                    say "         => the command does not create new libraries at all, regardless of input."
                }
            } else {
                line info "no reference xml at $ref -- skipping the round-trip test"
            }
        }
        }

    say ""
    say "  ---- summary ----"
    if {$ok1} {
        say "  XML2OLB works with our file. Open $out in Capture and check the part."
    } else {
        say "  XML2OLB did not create a file. Please send everything above."
        say "  The round-trip line (variant 4) is the decisive one:"
        say "    works   -> our XML is rejected, I need to adjust the format"
        say "    fails   -> the command needs something else (an open project/library?),"
        say "               and I will switch to a different import route"
    }
    say "================================================================"
    say ""
}

catch { ::lcsc2d2::run $lcsc_xml $lcsc_out $lcsc_ref }

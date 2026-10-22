# =============================================================================
# edakit -- OrCAD Capture plugin (main logic)
#
# Installed to:
#   <SPB>/tools/capture/tclscripts/capAutoLoad/edakit/edakit.tcl
#
# It does three things:
#   1. Polls the placement queue and drops the picked part onto the schematic
#   2. Menu item "Open LCSC Mall" launches the mall window
#   3. Menu items for capability probe / log
#
# IMPORTANT -- this file must stay PURE ASCII.
# Capture's Tcl reads files using the system code page (cp936 on a Chinese
# Windows). UTF-8 Chinese bytes get decoded as GBK, and GBK trail bytes can be
# 0x7B '{', 0x7D '}' or 0x5C '\' -- which silently corrupts the parse and ends
# with "missing close-brace". Keep every .tcl file ASCII-only.
#
# Queue format is key=value plain text -- not JSON, because Capture's Tcl may
# not ship the json package.
# =============================================================================

# If this file is sourced twice (init script + a recursive capAutoLoad scan),
# do nothing the second time -- otherwise RegisterAction and the poll loop
# would be set up twice.
if {[info exists ::edakit_loaded] && $::edakit_loaded} { return }
set ::edakit_loaded 1

namespace eval edakit {
    variable exePath ""
    variable queueDir ""
    variable appDir ""
    variable pollMs 400
    variable sessionId "[pid]-[clock clicks]"
    variable busy 0
    variable pollId ""
    variable logLines {}
    variable xmaticTried 0
    variable menuRegistered 0
    variable menuTries 0

    # ------------------------------------------------------------- paths --
    proc locateAppDir {} {
        variable appDir
        if {$appDir ne ""} { return $appDir }
        if {[info exists ::env(LOCALAPPDATA)]} {
            set appDir [file join $::env(LOCALAPPDATA) edakit]
        } else {
            set appDir [file join $::env(USERPROFILE) .edakit]
        }
        file mkdir $appDir
        return $appDir
    }

    proc locateQueueDir {} {
        variable queueDir
        if {$queueDir ne ""} { return $queueDir }
        set queueDir [file join [locateAppDir] queue]
        file mkdir $queueDir
        return $queueDir
    }

    proc locateExe {} {
        variable exePath
        if {$exePath ne "" && [file exists $exePath]} { return $exePath }
        if {[info exists ::env(EDAKIT_EXE)] && [file exists $::env(EDAKIT_EXE)]} {
            set exePath $::env(EDAKIT_EXE)
            return $exePath
        }
        # deploy records its own path in %LOCALAPPDATA%/edakit/exe_path.txt
        set marker [file join [locateAppDir] exe_path.txt]
        if {[file exists $marker]} {
            if {![catch {
                set fp [open $marker r]
                set p [string trim [read $fp]]
                close $fp
            }]} {
                if {$p ne "" && [file exists $p]} {
                    set exePath $p
                    return $p
                }
            }
        }
        set here [file dirname [info script]]
        set cands [list [file join $here edakit.exe] \
                        [file join $here .. edakit.exe]]
        if {[info exists ::env(USERPROFILE)]} {
            lappend cands [file join $::env(USERPROFILE) edakit-build dist edakit.exe]
            lappend cands [file join $::env(USERPROFILE) edakit dist edakit.exe]
        }
        foreach cand $cands {
            if {[file exists $cand]} { set exePath $cand; return $cand }
        }
        return ""
    }

    proc log {msg} {
        variable logLines
        set ts [clock format [clock seconds] -format "%H:%M:%S"]
        lappend logLines "$ts $msg"
        if {[llength $logLines] > 200} { set logLines [lrange $logLines end-199 end] }
        catch { puts "edakit: $msg" }
    }

    # --------------------------------------------------------- kv helper --
    proc readKV {path} {
        set fp [open $path r]
        fconfigure $fp -encoding utf-8
        set data [read $fp]
        close $fp
        array set kv {}
        foreach line [split $data "\n"] {
            set line [string trim $line]
            if {$line eq "" || [string index $line 0] eq "#"} { continue }
            set pos [string first "=" $line]
            if {$pos < 0} { continue }
            set k [string trim [string range $line 0 [expr {$pos-1}]]]
            set v [string trim [string range $line [expr {$pos+1}] end]]
            set kv($k) $v
        }
        return [array get kv]
    }

    proc writeKV {path pairs} {
        set temp "$path.[pid].[clock clicks].tmp"
        set fp [open $temp w]
        fconfigure $fp -encoding utf-8 -translation lf
        foreach {k v} $pairs { puts $fp "$k=[string map [list "\n" " " "\r" " "] $v]" }
        close $fp
        for {set attempt 0} {$attempt < 6} {incr attempt} {
            if {![catch {file rename -force $temp $path} err]} { return }
            if {$attempt < 5} { after 10 }
        }
        catch {file delete $temp}
        error $err
    }

    # Safe array read -- a missing key must not kill the whole poll cycle.
    proc kvGet {arrName key {def ""}} {
        upvar 1 $arrName a
        if {[info exists a($key)] && $a($key) ne ""} { return $a($key) }
        return $def
    }

    # ---------------------------------------------------------- heartbeat --
    proc heartbeat {} {
        set hb [file join [locateQueueDir] heartbeat.txt]
        catch { writeKV $hb [list ts [clock seconds] pid [pid] ] }
    }

    # Per-process registration; never infer host death from a delayed heartbeat.
    proc registerHost {} {
        variable sessionId
        set dir [file join [locateAppDir] capture_hosts]
        file mkdir $dir
        writeKV [file join $dir "[pid].owner"] [list pid [pid] ts [clock seconds] session $sessionId]
        # Capture's footprint viewer reads this profile, not Allegro's env.
        if {[llength [info commands GetIniPath]]} {
            catch { writeKV [file join [locateAppDir] capture_ini_path.txt] [list path [GetIniPath]] }
        }
    }

    # ----------------------------------------------------------- polling --
    proc startPolling {} {
        variable pollId
        if {$pollId ne ""} { catch { after cancel $pollId } }
        registerHost
        heartbeat
        poll
    }

    proc poll {} {
        variable pollId
        variable pollMs
        variable menuRegistered
        variable menuTries
        catch { tryPendingPlace }
        catch { processQueue }
        catch { ::edakit::properties::poll }
        # Menu may not register when the plugin loads before Capture's menu
        # system is ready; retry roughly every 2 seconds for the first minute.
        if {!$menuRegistered && $menuTries < 30} {
            registerMenu
        }
        heartbeat
        set pollId [after $pollMs [namespace current]::poll]
    }

    # Is a schematic page the ACTIVE view? The embedded mall tab and any other
    # view make this 0; PlacePart/Place Part then fail with
    # "Message Not Processed" / "Command Requires SchematicView" (2026-10-19).
    proc schematicActive {} {
        if {[catch { IsSchematicViewActive } v]} { return 0 }
        return $v
    }

    # A placement that arrived while the mall tab was active is parked here and
    # runs as soon as the user's schematic page becomes active (poll loop).
    proc tryPendingPlace {} {
        variable pendingPlace
        if {![info exists pendingPlace] || $pendingPlace eq ""} { return }
        set job $pendingPlace
        lassign $job olb partName followCursor xMil yMil footprint respPath seq claimPath expires cid partXml projectOlb symbolDigest
        if {$expires ne "" && $expires > 0 && [clock seconds] > $expires} {
            set pendingPlace ""
            writeKV $respPath [list seq $seq ok 0 message "request expired" stage expired error_code request_expired]
            catch {file delete -force $claimPath}
            return
        }
        if {![schematicActive]} { return }
        set libraryLock [claimLibraryLock [locateQueueDir]]
        if {$libraryLock eq ""} { return }
        set pendingPlace ""
        log "schematic active again -- placing pending part '$partName'"
        set ok 1
        if {[catch {
            # Revalidate the immutable library after waiting (it may have been
            # removed or evicted). Never place from the mutable staging path.
            if {$symbolDigest ne ""} { set olb [buildOlb $cid $partXml $projectOlb $partName $symbolDigest] }
            placePart $olb $partName $followCursor $xMil $yMil $footprint
        } msg]} {
            set ok 0
            log "pending placement failed: $msg"
        }
        catch {file delete $libraryLock}
        writeKV $respPath [list seq $seq ok $ok message $msg stage place olb_reused $::edakit::lastOlbReused]
        catch {file delete -force $claimPath}

    }

    proc claimLibraryLock {qd} {
        set libraryLock [file join $qd capture-library.lock]
        set lockSource [file join $qd "capture-library.[pid].tmp"]
        writeKV $lockSource [list pid [pid]]
        set lockBusy [catch {file link -hard $libraryLock $lockSource}]
        catch {file delete $lockSource}
        if {$lockBusy} { return "" }
        return $libraryLock
    }

    proc processQueue {} {
        variable busy
        variable pendingPlace
        if {$busy || ([info exists pendingPlace] && $pendingPlace ne "")} { return }
        set busy 1
        if {[catch {processQueueUnlocked} err]} { writeDiag "queue polling failed: $err" }
        set busy 0
    }

    proc processQueueUnlocked {} {
        variable sessionId
        set qd [locateQueueDir]
        set reqs [lsort [glob -nocomplain -directory $qd -tails *.req]]
        if {![llength $reqs]} { return }
        foreach name $reqs {
            if {![regexp {^req_[A-Za-z0-9_-]{1,100}\.req$} $name]} { continue }
            set path [file join $qd $name]
            # Inspect routing before claiming; rename without -force is exclusive.
            if {[catch {array unset head; array set head [readKV $path]}]} { continue }
            set target [kvGet head target_session]
            if {$target ne "" && $target ne $sessionId && $target ne "[pid]"} { continue }
            # The accumulated OLB is shared by hosts. Serialize conversion/merge.
            set libraryLock [claimLibraryLock $qd]
            if {$libraryLock eq ""} { continue }
            set seq [string range $name 4 end-4]
            set claim "$path.[pid].work"
            if {[catch {file rename $path $claim}]} { catch {file delete $libraryLock}; continue }
            set path $claim
            set response [file join $qd "resp_${seq}.resp"]
            if {[file exists $response]} { catch {file delete $path}; catch {file delete $libraryLock}; continue }
            if {[catch { handleOne $path } err]} {
                log "error while handling $name: $err"
                catch {
                    writeKV [file join $qd "resp_${seq}.resp"] \
                        [list seq $seq ok 0 message "internal error: $err"]
                }
                catch { file delete -force $path }
            }
            catch {file delete $libraryLock}
            # Keep deferred jobs intact and let the event loop regain control.
            break
        }
    }

    # ---------------------------------------------------- handle one job --
    proc handleOne {path} {
        array set req [readKV $path]
        set seq [kvGet req seq "unknown"]
        if {![regexp {^[A-Za-z0-9_-]{1,100}$} $seq]} { error "invalid request identifier" }
        writeDiag "queue request_id=$seq received"
        set cid [kvGet req cid]
        set partName [kvGet req part_name $cid]
        set partXml [kvGet req olb_xml]
        set symbolDigest [kvGet req symbol_digest]
        set projectOlb [kvGet req project_olb]
        set footprint [kvGet req footprint]
        set followCursor [kvGet req follow_cursor 0]
        set xMil [kvGet req x_mil 500]
        set yMil [kvGet req y_mil 500]
        set stageOnly [kvGet req stage_only 0]
        set version [kvGet req protocol_version 1]
        set command [kvGet req command place]
        set expires [kvGet req expires 0]

        set qd [locateQueueDir]
        set respPath [file join $qd "resp_${seq}.resp"]

        set failMsg ""
        set ok 0
        set stage "start"
        set ::edakit::lastOlbReused 0

        if {$version ni {1 2} || $command ne "place"} {
            writeKV $respPath [list seq $seq ok 0 message "unsupported queue protocol or command" stage rejected error_code unsupported_command]
            file delete -force $path
            return
        }
        if {$expires > 0 && [clock seconds] > $expires} {
            writeKV $respPath [list seq $seq ok 0 message "request expired" stage expired error_code request_expired]
            file delete -force $path
            return
        }
        if {$cid eq ""} {
            set failMsg "request has no cid"
        } elseif {$stageOnly eq "1" || $stageOnly eq "true"} {
            # files are already staged; leave OrCAD alone
            set ok 1
            set failMsg "files staged (nothing placed)"
            set stage "stage"
        } else {
            if {[catch {
                set stage "check-xmatic"
                ensureXmatic
                if {![haveCommand XMATIC_XML2OLB]} {
                    error "XMATIC_XML2OLB is not available in this Capture -- cannot build .olb. Run menu 'LCSC -> Probe' for details."
                }
                set stage "build-olb"
                set olb [buildOlb $cid $partXml $projectOlb $partName $symbolDigest]
                set stage "place"
                if {![schematicActive]} {
                    # The mall tab / library view is active: PlacePart refuses
                    # to run outside a schematic view. Park the job; the poll
                    # loop places it the moment a schematic page is back.
                    variable pendingPlace
                    set pendingPlace [list $olb $partName $followCursor $xMil $yMil $footprint $respPath $seq $path $expires $cid $partXml $projectOlb $symbolDigest]
                    set ok 1
                    set stage "waiting-schematic"
                    set failMsg "ready: switch to the schematic tab to start placement"
                } else {
                    set failMsg [placePart $olb $partName $followCursor $xMil $yMil $footprint]
                    set ok 1
                }
            } err]} {
                set failMsg "failed at $stage: $err"
            }
        }

        catch {
            writeKV $respPath [list seq $seq ok $ok message $failMsg stage $stage olb_reused $::edakit::lastOlbReused request_id $seq error_code [expr {$ok ? "" : "capture_operation_failed"}]]
        }
        if {$stage ne "waiting-schematic"} { file delete -force $path }
        writeDiag "queue request_id=$seq stage=$stage ok=$ok"
        if {$ok} { log $failMsg } else { log "ERR $failMsg" }
    }

    proc haveCommand {name} {
        return [expr {[llength [info commands $name]] > 0 || [llength [info commands ::$name]] > 0}]
    }

    # Some installs do not load the DBO Tcl extension by default, so a plain
    # "is the command there" check gives a false MISSING. Try to load it once
    # before deciding. Everything is wrapped in catch -- a failed load must
    # never take down the poll loop.
    proc ensureXmatic {} {
        variable xmaticTried
        if {[haveCommand XMATIC_XML2OLB]} { return 1 }
        if {$xmaticTried} { return [haveCommand XMATIC_XML2OLB] }
        set xmaticTried 1

        set dirs {}
        foreach v {CDSROOT CONCEPTHDL_CDS_ROOT} {
            if {[info exists ::env($v)] && $::env($v) ne ""} {
                set r $::env($v)
                lappend dirs $r
                foreach sub {{tools capture} {tools capture bin} {tools capture tclscripts} {tools bin} {bin}} {
                    lappend dirs [eval file join [list $r] $sub]
                }
            }
        }

        foreach d $dirs {
            if {![file isdirectory $d]} { continue }
            if {[catch {glob -nocomplain -directory $d -types f *.dll} files]} { continue }
            foreach f $files {
                set b [string tolower [file tail $f]]
                if {![string match *dbotcl* $b] && ![string match *xmatic* $b]} { continue }
                set pkg [file rootname [file tail $f]]
                if {[catch {load $f $pkg}]} {
                    catch {load $f}
                }
                if {[haveCommand XMATIC_XML2OLB]} {
                    log "loaded $f -- XMATIC_XML2OLB is now available"
                    return 1
                }
            }
        }
        return 0
    }

    # -------------------------------------------------- accumulating OLB --
    # OLB(old) --OLB2XML--> base.xml
    #          --merge Part--> merged.xml   (done by the exe; Python is safer)
    #          --XML2OLB--> OLB(new)
    #          --PlacePart refers to it
    #
    # Real-machine findings (2026-10-19, Capture 17.2):
    #  - XMATIC_XML2OLB writes NOTHING (and returns a harmless DboState) when
    #    the target .olb already exists -- e.g. a library Capture created in
    #    an earlier placement. It only reports the state, so check the FILE.
    #  - Renaming the old file away DOES work even while Capture keeps it open,
    #    so writeOlb renames the target aside before writing.
    #  - PlacePart caches the library contents per PATH: after the .olb is
    #    rewritten on disk, placing from the same path still uses the old
    #    cached copy (observed: readback had RP2040, PlacePart said "Invalid
    #    Argument(s)"). Therefore placement always uses a NEW unique .olb path.
    proc olbHasPart {olbPath partName {strict 0}} {
        if {$partName eq "" || ![file exists $olbPath]} { return [expr {!$strict}] }
        set rt "${olbPath}.rt.xml"
        catch { file delete -force $rt }
        if {[catch { XMATIC_OLB2XML $olbPath $rt }]} { return [expr {!$strict}] }
        if {![file exists $rt]} { return [expr {!$strict}] }
        set fp [open $rt r]
        fconfigure $fp -encoding utf-8
        set body [read $fp]
        close $fp
        catch { file delete -force $rt }
        if {$strict} {
            foreach package [regexp -all -inline {<Package(?:\s[^>]*)?>\s*<Defn\s[^>]*>} $body] {
                if {[regexp {\sname="([^"]*)"} $package -> encoded]} {
                    set decoded [string map [list "&quot;" \" "&apos;" "'" "&lt;" "<" "&gt;" ">" "&amp;" "&"] $encoded]
                    if {$decoded eq $partName} { return 1 }
                }
            }
            return 0
        }
        return [expr {[string first "name=\"$partName\"" $body] >= 0}]
    }

    proc writeOlb {xmlPath olbPath} {
        if {![file exists $olbPath]} {
            XMATIC_XML2OLB $xmlPath $olbPath
            return [file exists $olbPath]
        }
        # Existing path: move the old file aside first. Deleting/overwriting a
        # loaded .olb is refused silently, but renaming is allowed.
        set aside "${olbPath}.old"
        catch { file delete -force $aside }
        if {[catch { file rename -force $olbPath $aside }]} {
            catch { file delete -force $olbPath }
        }
        XMATIC_XML2OLB $xmlPath $olbPath
        set wrote [file exists $olbPath]
        if {!$wrote && [file exists $aside] && ![file exists $olbPath]} {
            catch { file rename -force $aside $olbPath }
        }
        catch { file delete -force $aside }
        return [file exists $olbPath]
    }

    # Prune older per-placement copies (keep the 5 newest).
    proc prunePlaceCopies {work keep} {
        catch {
            set files [lsort -decreasing [glob -nocomplain -directory $work -tails place_*.olb]]
            foreach old [lrange $files $keep end] {
                file delete -force [file join $work $old]
            }
        }
    }

    # A library that Capture itself has rewritten (OLB2XML -> XML2OLB) renders
    # correctly when placed; one written straight from our XML sometimes draws
    # the pins scattered outside the body (2026-10-20, proven twice). So every
    # library we hand to PlacePart goes through one extra Capture roundtrip.
    proc normalizeOlb {olbPath} {
        set rt "${olbPath}.norm.xml"
        catch { file delete -force $rt }
        catch { XMATIC_OLB2XML $olbPath $rt }
        if {[file exists $rt] && [file size $rt] > 0} {
            set ok [writeOlb $rt $olbPath]
            catch { file delete -force $rt }
            return $ok
        }
        catch { file delete -force $rt }
        return 0
    }

    # Cache only positively verified, normalized single-part libraries.
    # Binary snapshots detect external edits without requiring Tcl crypto packages.
    proc sameBinaryFile {a b} {
        if {![file isfile $a] || ![file isfile $b]} { return 0 }
        if {[file size $a] != [file size $b]} { return 0 }
        set f [open $a r]; fconfigure $f -translation binary -encoding binary
        set left [read $f]; close $f
        set f [open $b r]; fconfigure $f -translation binary -encoding binary
        set right [read $f]; close $f
        return [expr {$left eq $right}]
    }

    proc placementCacheFile {key} {
        # Distinct basenames too: some host library registries identify by name.
        return [file join [locateAppDir] olb_cache $key "ek_[string range $key 0 23].olb"]
    }

    proc cachedPlacementOlb {key partXml projectOlb partName} {
        if {![regexp {^[a-f0-9]{64}$} $key] || ![file exists $projectOlb]} { return "" }
        set dir [file join [locateAppDir] olb_cache $key]
        set meta [file join $dir ready.meta]
        if {![file exists $meta]} { return "" }
        array set entry [readKV $meta]
        if {[kvGet entry version] ne "2" || [kvGet entry part_name] ne $partName ||
            [kvGet entry project_olb] ne $projectOlb} { return "" }
        set cached [placementCacheFile $key]
        if {![sameBinaryFile $partXml [file join $dir source.xml]] ||
            ![sameBinaryFile $cached [file join $dir verified.olb]]} { return "" }
        # Capture caches a loaded library by path, even when PlaceNew returns 1.
        # Each content key owns a stable path that is never switched to another part.
        catch {file mtime $meta [clock seconds]}
        return $cached
    }

    proc rememberPlacementOlb {key partXml projectOlb partName olb} {
        if {![regexp {^[a-f0-9]{64}$} $key]} { return }
        set root [file join [locateAppDir] olb_cache]
        set dir [file join $root $key]
        file mkdir $dir
        set meta [file join $dir ready.meta]
        catch {file delete -force $meta}
        file copy -force $partXml [file join $dir source.xml]
        file copy -force $olb [placementCacheFile $key]
        file copy -force $olb [file join $dir verified.olb]
        writeKV $meta [list version 2 part_name $partName project_olb $projectOlb]
        # Best-effort disk cache bound; loaded libraries may be held open by Capture.
        set entries {}
        foreach entry [glob -nocomplain -directory $root -types d *] {
            set ready [file join $entry ready.meta]
            if {[file exists $ready]} { lappend entries [list [file mtime $ready] $entry] }
        }
        set entries [lsort -integer -decreasing -index 0 $entries]
        foreach entry [lrange $entries 128 end] {
            set oldDir [lindex $entry 1]
            set cachedName [file tail [placementCacheFile [file tail $oldDir]]]
            catch {file delete -force [file join $oldDir ready.meta]}
            foreach name [list source.xml part.olb verified.olb $cachedName] {
                catch {file delete -force [file join $oldDir $name]}
            }
            catch {file delete $oldDir}
        }
    }

    proc buildOlb {cid partXml projectOlb {partName ""} {symbolDigest ""}} {
        variable lastOlbReused
        set lastOlbReused 0
        set app [locateAppDir]
        set exe [locateExe]
        set work [file join $app staging $cid]
        file mkdir $work
        set baseXml [file join $work "${cid}.base.xml"]
        set mergedXml [file join $work "${cid}.merged.xml"]

        if {$projectOlb eq ""} {
            set projectOlb [file join $app project.olb]
        }
        file mkdir [file dirname $projectOlb]

        set cached ""
        if {[catch {set cached [cachedPlacementOlb $symbolDigest $partXml $projectOlb $partName]} err]} {
            writeDiag "OLB cache invalid: $err; rebuilding"
        }
        if {$cached ne ""} {
            set lastOlbReused 1
            writeDiag "OLB cache HIT cid=$cid part=$partName"
            return $cached
        }
        writeDiag "OLB cache MISS cid=$cid part=$partName"

        # 1) existing library -> XML
        catch { file delete -force $baseXml }
        if {[file exists $projectOlb]} {
            catch { XMATIC_OLB2XML $projectOlb $baseXml }
            set baseXml [expr {[file exists $baseXml] ? $baseXml : ""}]
        } else {
            set baseXml ""
        }

        # 2) merge (handed to the exe)
        catch { file delete -force $mergedXml }
        if {$exe ne ""} {
            if {$baseXml ne ""} {
                exec $exe olb-merge --base $baseXml --part $partXml --out $mergedXml
            } else {
                exec $exe olb-merge --base "" --part $partXml --out $mergedXml
            }
        } else {
            # no exe -> fall back to a single-part library
            set mergedXml $partXml
        }

        # 2b) part-name check: PlacePart uses the part name; the real name in the
        #     library is the <Package><Defn name=...> value.
        if {$partName ne "" && [file exists $mergedXml]} {
            set fp [open $mergedXml r]
            fconfigure $fp -encoding utf-8
            set body [read $fp]
            close $fp
            if {[string first "name=\"$partName\"" $body] < 0} {
                set found "?"
                if {[regexp {<Package>\s*<Defn[^>]*name="([^"]*)"} $body -> found] == 0} {
                    set found "(none)"
                }
                error "part '$partName' not found in merged library XML (first package: '$found')"
            }
        }

        # 3) accumulate into the project library (best effort -- used for later
        #    merges and for the user's own Place Part dialog).
        catch {
            if {[writeOlb $mergedXml $projectOlb] && ![olbHasPart $projectOlb $partName]} {
                log "WARN: $projectOlb did not keep part '$partName' (file likely locked by Capture)"
            }
        }

        # 4) A shared temporary path for Capture's required normalization roundtrip.
        # This mutable file must never be passed to PlaceNew: Capture keeps the
        # first loaded definition for a path, even if it has since been replaced.
        set placeOlb [file join [locateAppDir] lcsc_test.olb]
        if {![writeOlb $partXml $placeOlb]} {
            error "Capture did not write $placeOlb -- run menu 'LCSC -> Probe' for details"
        }
        set normalized [normalizeOlb $placeOlb]
        if {![olbHasPart $placeOlb $partName]} {
            error "Capture did not keep part '$partName' in $placeOlb -- run menu 'LCSC -> Probe' for details"
        }
        if {$normalized && [olbHasPart $placeOlb $partName 1]} {
            if {[catch {rememberPlacementOlb $symbolDigest $partXml $projectOlb $partName $placeOlb} err]} {
                writeDiag "OLB cache store skipped: $err"
            }
        }
        set reusable ""
        catch {set reusable [cachedPlacementOlb $symbolDigest $partXml $projectOlb $partName]}
        if {$reusable ne ""} { return $reusable }
        # Legacy requests or failed cache writes still need a fresh immutable path.
        set snapshot [file join $work "place_[clock seconds]_[pid]_[clock clicks].olb"]
        file copy $placeOlb $snapshot
        return $snapshot
    }

    # --------------------------------------------------------- placement --
    # Capture 17.2 user-verified (2026-10-20): activate schematic, clear
    # selection, redraw, then PlaceNew. PlacePartEx returned without a visible
    # cursor symbol on this installation; do not use it as a fallback.
    proc placePart {olb partName followCursor xMil yMil footprint} {
        # Capture wants forward slashes
        set olbFwd [string map {\\ /} $olb]

        # The footprint name is NOT passed to PlacePart -- it already lives in
        # the symbol XML as the "PCB Footprint" property. Just log it so the
        # user knows which .dra/.psm to build.
        if {$footprint ne ""} {
            log "matching footprint $footprint (in the footprint lib; load its .il in Allegro)"
        }

        if {$followCursor eq "1" || $followCursor eq "true"} {
            foreach cmd {PlaceNew capGetMostRecentSchFrameID DboTclHelper_sGetConstCharPtr ui::SchematicActivate UnSelectAll capGetIsSchematicEditingDisabled} {
                if {![haveCommand $cmd]} {
                    error "Native cursor placement requires $cmd. Run Capability Probe."
                }
            }
            set frame [DboTclHelper_sGetConstCharPtr [capGetMostRecentSchFrameID]]
            ui::SchematicActivate $frame
            if {![schematicActive]} { error "Schematic activation failed" }
            if {[capGetIsSchematicEditingDisabled]} { error "Schematic editing is disabled" }
            UnSelectAll
            catch {ZoomRedraw}
            writeDiag "cursor CALL PlaceNew [list $olbFwd $partName 0] (frame=$frame)"
            set result [PlaceNew $olbFwd $partName 0]
            writeDiag "cursor RETURN <$result> (observe cursor and click to place)"
            if {$result ne "1"} {
                error "PlaceNew rejected '$partName' (returned <$result>); placement was not started"
            }
            return "armed: $partName -- click the schematic to place; Esc ends placement"
        }

        # 1) Coordinates: PlacePart takes INCHES, not mils. The request carries
        #    mils (500 = 0.5"), and 500 *inches* put the part far outside the
        #    page, where ZoomAll never shows it (real-machine finding
        #    2026-10-19: PlacePart 0 0 / 0.5 0.5 = visible at page corner,
        #    PlacePart 500 500 = never seen).
        #    Each placement steps right/down so parts do not pile on top of
        #    each other; when the row is full it wraps.
        variable slot
        if {![info exists slot]} { set slot 0 }
        set col [expr {$slot % 4}]
        set row [expr {$slot / 4}]
        incr slot
        set xMil [expr {0.5 * 1000 + $col * 3000}]
        set yMil [expr {0.5 * 1000 + $row * 3000}]
        set x [expr {$xMil / 1000.0}]
        set y [expr {$yMil / 1000.0}]

        # 2) The canvas cursor would be nicer than a grid slot, but
        #    getPlaceLocation returns empty on this install -- try anyway.
        set usedCursor 0
        if {[llength [info commands getPlaceLocation]]} {
            set loc ""
            catch { set loc [getPlaceLocation] }
            if {$loc ne ""} {
                log "getPlaceLocation -> $loc"
                set nums [regexp -all -inline -- {-?[0-9]+(?:\.[0-9]+)?} $loc]
                if {[llength $nums] >= 2} {
                    set x [expr {double([lindex $nums 0]) / 1000.0}]
                    set y [expr {double([lindex $nums 1]) / 1000.0}]
                    set usedCursor 1
                }
            }
        }

        log "PlacePart $x $y (inch) $olbFwd '$partName' (cursor=$usedCursor)"
        PlacePart $x $y $olbFwd $partName "" FALSE
        # PlacePart does not refresh the canvas. The part IS in the design but
        # stays invisible until a redraw/zoom (observed 2026-10-19).
        catch { ZoomRedraw }
        catch { ZoomAll }
        catch { ZoomRedraw }
        log "placed at ($x, $y) inch"
        return "placed $partName"
    }

    # ------------------------------------------------------ menu actions --
    # NOTE: accessory-menu callbacks are invoked with arguments by Capture
    # (Cadence's own capAppLaunchMenu.tcl uses {args} on every handler).
    # Declaring them with no parameters made every click fail with
    # "wrong # args" -- the menu looked dead. Always use {args}.
    proc urlFile {} {
        return [file join [locateAppDir] url.txt]
    }

    proc portOf {url} {
        if {[regexp {:([0-9]+)/?$} $url -> p]} { return $p }
        return ""
    }

    # Is something listening on that port? (the mall server writes url.txt on
    # start; a stale file from a killed server must not be trusted)
    proc serverAlive {url} {
        set p [portOf $url]
        if {$p eq ""} { return 0 }
        if {[catch {
            set s [socket 127.0.0.1 $p]
            close $s
        }]} {
            return 0
        }
        # Return outside catch: Tcl catch treats return as code 2, not success.
        return 1
    }

    # Return the base URL of a running mall server, starting one if needed.
    proc ensureServer {} {
        registerHost
        set exe [locateExe]
        if {$exe eq ""} { return "" }
        set uf [urlFile]
        set url ""
        if {[file exists $uf]} {
            catch {
                set fp [open $uf r]
                set url [string trim [read $fp]]
                close $fp
            }
            if {$url ne "" && ![serverAlive $url]} { set url "" }
        }
        if {$url ne ""} { return $url }
        catch { file delete -force $uf }
        # `serve` = local server, no external browser. PyInstaller's first
        # launch can take 15-20 seconds while Windows Defender scans the exe.
        # Keep the host marker alive and allow a bounded 45-second startup
        # window so the menu does not report a false failure.
        writeDiag "starting mall server: $exe (host=[pid])"
        if {[catch { exec $exe serve --capture-pid [pid] & } err]} {
            writeDiag "direct server launch failed: $err"
            if {[catch { exec {*}[list cmd /c start "" $exe serve --capture-pid [pid]] } err2]} {
                writeDiag "fallback server launch failed: $err2"
            }
        }
        for {set i 0} {$i < 180} {incr i} {
            after 250
            if {[file exists $uf]} {
                catch {
                    set fp [open $uf r]
                    set url [string trim [read $fp]]
                    close $fp
                }
                if {$url ne ""} { return $url }
            }
        }
        writeDiag "mall server startup timed out after 45s (exe=$exe)"
        return ""
    }

    # Legacy viewer remains available as an explicit fallback.
    proc openMallLegacy {args} {
        set url [ensureServer]
        if {$url eq ""} {
            showText "EdaKit" "Embedded mall server could not be started. Run Capability Probe and check the exe path."
            return
        }
        if {![haveCommand OpenURL]} {
            showText "EdaKit" "This Capture installation has no embedded OpenURL viewer."
            return
        }
        set page "[string trimright $url /]/embed?session=$::edakit::sessionId"
        if {[catch {OpenURL $page "EdaKit Mall"} err]} {
            writeDiag "OpenURL failed: $err"
            showText "EdaKit" "Could not open embedded mall: $err"
            return
        }
        writeDiag "mall opened embedded: $page"
    }

    # Owned CEF dock. Same URL only raises the panel: never reset query state.
    proc openCefMall {page} {
        variable cefWidget
        variable cefPage
        package require orPrmWebComp
        foreach cmd {CreateControlBar LoadResource SetTitle ShowWidget DestroyWidget} {
            if {![llength [info commands ::orPrm::$cmd]]} { error "Missing orPrm::$cmd" }
        }
        foreach key {WDOCK_RIGHT WDALLOW_RIGHT WF_CEF} {
            if {![info exists ::orPrm::$key]} { error "Missing orPrm::$key" }
        }
        if {[info exists cefWidget]} {
            if {![catch {
                if {![info exists cefPage] || $cefPage ne $page} {
                    ::orPrm::LoadResource $cefWidget $page
                    set cefPage $page
                }
                ::orPrm::ShowWidget $cefWidget 1
            } err]} {
                writeDiag "CEF dock reused id=$cefWidget"
                return $cefWidget
            }
            # Keep ownership if cleanup fails; do not pile up duplicate docks.
            ::orPrm::DestroyWidget $cefWidget
            unset cefWidget
            unset -nocomplain cefPage
        }
        set id [::orPrm::CreateControlBar EdaKitWorkbench $::orPrm::WDOCK_RIGHT $::orPrm::WDALLOW_RIGHT 700 $::orPrm::WF_CEF [list]]
        if {$id eq ""} { error "CEF returned an empty widget id" }
        set cefWidget $id
        if {[catch {
            ::orPrm::LoadResource $id $page
            set cefPage $page
            ::orPrm::SetTitle $id "EdaKit Workbench"
            ::orPrm::ShowWidget $id 1
        } err]} {
            if {![catch {::orPrm::DestroyWidget $id}]} {
                unset cefWidget
                unset -nocomplain cefPage
            }
            error $err
        }
        writeDiag "CEF dock created id=$id page=$page"
        return $id
    }

    proc openMall {args} {
        set url [ensureServer]
        if {$url eq ""} {
            showText "EdaKit" "Embedded mall server could not be started. Check the exe path and log."
            return
        }
        if {[catch {openCefMall "[string trimright $url /]/embed?session=$::edakit::sessionId"} err]} {
            writeDiag "CEF dock failed: $err; opening legacy viewer"
            openMallLegacy
        }
    }

    # Any menu click / diagnostic output also lands in this file, so problems
    # are visible even when there is no Tk and the console output is scrolled
    # away. Path: %LOCALAPPDATA%\edakit\edakit.log
    proc diagFile {} {
        return [file join [locateAppDir] edakit.log]
    }

    proc writeDiag {msg} {
        catch {
            set fp [open [diagFile] a]
            fconfigure $fp -encoding utf-8 -translation lf
            set ts [clock format [clock seconds] -format "%Y-%m-%d %H:%M:%S"]
            puts $fp "$ts $msg"
            close $fp
        }
        catch { puts "edakit: $msg" }
    }

    # Show text to the user through whatever channel this Capture has.
    # Tk is NOT guaranteed: capAppLaunchMenu.tcl exists precisely because some
    # installs ship Capture with a Tcl that has no Tk -- tk_messageBox then
    # raises "invalid command name" and the menu click looks like a no-op.
    # Order: Tk message box -> Session Log (DBO) -> stdout.
    proc showText {title text} {
        if {[llength [info commands tk_messageBox]] > 0} {
            if {![catch { tk_messageBox -icon info -title $title -message $text }]} {
                return
            }
        }
        set shown 0
        if {[llength [info commands DboState_WriteToSessionLog]] > 0} {
            if {![catch {
                set lMsg [DboTclHelper_sMakeCString $text]
                DboState_WriteToSessionLog $lMsg
            }]} {
                set shown 1
            }
        }
        # Always echo to stdout and the diag file -- console may be hidden.
        catch { puts "$title:\n$text" }
        writeDiag "--- $title ---\n$text"
        if {!$shown} {
            # Last resort: a text file the user can open.
            catch {
                set p [file join [locateAppDir] last_message.txt]
                set fp [open $p w]
                fconfigure $fp -encoding utf-8
                puts $fp "$title"
                puts $fp $text
                close $fp
            }
        }
    }

    proc showProbe {args} {
        set out ""
        # Try loading first -- otherwise some installs report a false MISSING.
        catch { ensureXmatic }
        foreach cmd {XMATIC_XML2OLB XMATIC_OLB2XML capCreatePartsFromData PlacePart \
                     PlacePartEx PlaceNew InsertXMLMenu} {
            lappend out [format "%-26s %s" $cmd [expr {[haveCommand $cmd] ? "OK" : "MISSING"}]]
        }
        set exe [locateExe]
        lappend out ""
        lappend out "exe:   [expr {$exe ne "" ? $exe : "(not found)"}]"
        lappend out "queue: [locateQueueDir]"
        showText "edakit capability probe" [join $out "\n"]
    }

    proc showLog {args} {
        variable logLines
        showText "edakit log" [join $logLines "\n"]
    }

    # Dynamic top-level menu; Cadence capAutoLoad examples use the same
    # nested list format. Stable IDs make insertion repeatable on retry.
    proc menuTrue {args} { return true }

    proc buildMenus {args} {
        InsertXMLMenu [list [list "EdaKit"] "" "" [list "popup" "EdaKit" "0"]]
        InsertXMLMenu [list [list "EdaKit" "Mall"] "" "" [list "action" "LCSC Mall" "0" "EdaKitMall" "EdaKitEnabled"]]
        InsertXMLMenu [list [list "EdaKit" "Properties"] "" "" [list "action" "Component Properties" "0" "EdaKitProperties" "EdaKitEnabled"]]
        InsertXMLMenu [list [list "EdaKit" "Diagnostics"] "" "" [list "popup" "Diagnostics" "0"]]
        foreach {id label action} {
            Probe "Capability Probe" edakitProbe
            Log "Log" edakitLog
        } {
            InsertXMLMenu [list [list "EdaKit" "Diagnostics" $id] "" "" \
                [list "action" $label "0" "EdaKit$id" "EdaKitEnabled"]]
        }
    }

    proc registerMenu {} {
        variable menuRegistered
        variable menuTries
        if {$menuRegistered} { return 1 }
        incr menuTries
        if {[catch {
            RegisterAction "EdaKitEnabled" "::edakit::menuTrue" "" "::edakit::menuTrue" ""
            foreach {id callback} {
                Mall edakitMall
                Properties edakitProperties
                Probe edakitProbe Log edakitLog
            } {
                RegisterAction "EdaKit$id" "::edakit::menuTrue" "" $callback ""
            }
            buildMenus
        } err]} {
            if {$menuTries <= 2 || $menuTries % 20 == 0} {
                log "top-level menu registration attempt $menuTries failed: $err"
            }
            return 0
        }
        set menuRegistered 1
        log "EdaKit top-level menu registered"
        return 1
    }

}

source [file join [file dirname [info script]] properties.tcl]

# -------------------------------------------------------------- register --
# First attempt happens right away; the poll loop keeps retrying (see poll)
# in case RegisterAction needs the DBO extension to be loaded first.
if {[catch { ::edakit::registerMenu } err]} {
    puts "edakit: menu registration failed: $err"
}

# ------------------------------------------------- global menu wrappers --
# Capture invokes accessory-menu commands as plain global commands. Each one
# is wrapped in catch and always writes to the diag log, so a failing click
# leaves a trace instead of silently doing nothing.
proc edakitDispatch {what} {
    catch { ::edakit::writeDiag "menu action '$what' invoked" }
    if {[catch { ::edakit::$what } err]} {
        catch { ::edakit::writeDiag "menu action '$what' failed: $err" }
        catch { puts "edakit: menu action '$what' failed: $err" }
    }
}

# {args}: Capture calls accessory-menu commands WITH arguments.
proc edakitMall  {args} { edakitDispatch openMall }
proc edakitMallLegacy {args} { edakitDispatch openMallLegacy }
proc edakitProbe {args} { edakitDispatch showProbe }
proc edakitLog   {args} { edakitDispatch showLog }

# Start polling
if {[catch { ::edakit::startPolling } err]} {
    puts "edakit: failed to start polling: $err"
} else {
    puts "edakit: started, polling queue ([::edakit::locateQueueDir])"
}

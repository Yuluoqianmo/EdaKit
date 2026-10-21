# EdaKit cursor diagnostic. ASCII only; source does not place anything.
namespace eval ::edakitCursorDiag {
    variable timer ""
    proc log {msg} {
        puts "EDAKIT_CURSOR_DIAG: $msg"
        catch {
            set p [file join $::env(LOCALAPPDATA) edakit cursor_diag.log]
            set f [open $p a]
            fconfigure $f -encoding utf-8
            puts $f "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $msg"
            close $f
        }
    }
    proc run {{mode new}} {
        variable timer
        if {[lsearch -exact {new ex stock} $mode] < 0} { error "Use new, ex or stock" }
        if {$timer ne ""} { after cancel $timer }
        log "Scheduled mode=$mode; move mouse into schematic now; wait 3 seconds"
        set timer [after 3000 [list ::edakitCursorDiag::execute $mode]]
    }
    proc execute {mode} {
        variable timer
        set timer ""
        set lib [file join $::env(LOCALAPPDATA) edakit lcsc_test.olb]
        set part "0603WAF1002T5E"
        if {$mode eq "stock"} {
            set lib "D:/Cadence/SPB_17.2/tools/capture/library/discrete.olb"
            set part "R"
        }
        if {![file exists $lib]} { log "ERROR missing library: $lib"; return }
        if {[catch {
            set frame [DboTclHelper_sGetConstCharPtr [capGetMostRecentSchFrameID]]
            log "recent schematic frame=$frame"
            ui::SchematicActivate $frame
            log "active=[IsSchematicViewActive] editingDisabled=[capGetIsSchematicEditingDisabled]"
            if {![IsSchematicViewActive]} { error "Schematic is not active" }
            if {[capGetIsSchematicEditingDisabled]} { error "Schematic editing is disabled" }
            UnSelectAll
            catch {ZoomRedraw}
            if {$mode eq "ex"} {
                set cmd [list PlacePartEx $lib $part "" 0]
            } else {
                set cmd [list PlaceNew $lib $part 0]
            }
            log "CALL $cmd"
            set result [uplevel #0 $cmd]
            log "RETURN <$result>; observe cursor manually (not a success verdict)"
        } err]} {
            log "ERROR $err"
        }
    }
}
puts "Loaded. Run ::edakitCursorDiag::run new, then move mouse into schematic."

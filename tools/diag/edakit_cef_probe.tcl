# Source only defines isolated commands. Does not replace the EdaKit menu.
namespace eval ::edakitCefProbe {
    if {![info exists widgets]} { array set widgets {} }
}

proc ::edakitCefProbe::readURL {target} {
    if {$target eq "probe"} {
        set path [file join $::env(LOCALAPPDATA) edakit-cef-probe url.txt]
    } elseif {$target eq "workbench"} {
        set path [file join $::env(LOCALAPPDATA) edakit url.txt]
    } else { error "Target must be probe or workbench" }
    if {![file exists $path]} { error "URL file missing: $path. Start the corresponding server first." }
    set fp [::open $path r]
    set url [string trim [read $fp 2048]]
    close $fp
    if {![regexp {^http://127\.0\.0\.1:[0-9]+/?$} $url]} {
        error "Expected a local EdaKit root URL, got: $url"
    }
    return "[string trimright $url /]/"
}

proc ::edakitCefProbe::log {message} {
    puts "EDAKIT_CEF: $message"
    set dir [file join $::env(LOCALAPPDATA) edakit-cef-probe]
    if {[catch {
        file mkdir $dir
        set fp [::open [file join $dir capture.log] a]
        puts $fp "[clock format [clock seconds] -format {%Y-%m-%d %H:%M:%S}] $message"
        close $fp
    } err]} { puts "EDAKIT_CEF: log write failed: $err" }
}

proc ::edakitCefProbe::open {mode {target probe}} {
    variable widgets
    if {$mode ni {openurl view dock}} { error "Mode must be openurl, view or dock" }
    set url [readURL $target]
    log "OPEN mode=$mode target=$target url=$url"
    if {$mode eq "openurl"} {
        OpenURL "${url}?host=openurl" "EdaKit Probe OpenURL"
        return
    }
    if {[catch {
        package require orPrmWebComp
        foreach cmd {CreateWidget LoadResource SetTitle ShowWidget DestroyWidget} {
            if {![llength [info commands ::orPrm::$cmd]]} { error "Missing orPrm::$cmd" }
        }
        foreach constant {WF_CEF WTYPE_VIEW} {
            if {![info exists ::orPrm::$constant]} { error "Missing orPrm::$constant" }
        }
        if {$mode eq "dock"} {
            foreach constant {WDOCK_RIGHT WDALLOW_RIGHT} {
                if {![info exists ::orPrm::$constant]} { error "Missing orPrm::$constant" }
            }
            if {![llength [info commands ::orPrm::CreateControlBar]]} { error "Missing CreateControlBar" }
        }
        set key "$mode,$target"
        set reused 0
        if {[info exists widgets($key)]} {
            # Reuse owned widget; a manually closed stale handle may fail.
            if {![catch {
                ::orPrm::LoadResource $widgets($key) "${url}?host=cef-$mode"
                ::orPrm::ShowWidget $widgets($key) 1
            } reuseError]} {
                set id $widgets($key)
                set reused 1
                log "REUSED $key id=$id"
            } else {
                # Do not create another widget if destruction itself fails.
                ::orPrm::DestroyWidget $widgets($key)
                unset widgets($key)
            }
        }
        if {!$reused} {
        set settings [list]
        if {$mode eq "view"} {
            set id [::orPrm::CreateWidget $::orPrm::WTYPE_VIEW $::orPrm::WF_CEF $settings]
        } else {
            set id [::orPrm::CreateControlBar "EdaKitProbe_$target" $::orPrm::WDOCK_RIGHT $::orPrm::WDALLOW_RIGHT 700 $::orPrm::WF_CEF $settings]
        }
        if {$id eq ""} { error "Create returned an empty widget id" }
        set widgets($key) $id
        if {[catch {
            ::orPrm::LoadResource $id "${url}?host=cef-$mode"
            ::orPrm::SetTitle $id "EdaKit CEF $mode ($target)"
            ::orPrm::ShowWidget $id 1
        } loadError]} {
            if {![catch {::orPrm::DestroyWidget $id}]} { unset widgets($key) }
            error $loadError
        }
        log "CREATED $key id=$id. Creation does not confirm page rendering."
        }
    } err]} {
        log "FAILED mode=$mode target=$target error=$err"
        error $err
    }
    return $id
}

proc ::edakitCefProbe::closeAll {} {
    variable widgets
    foreach key [array names widgets] {
        if {[catch {::orPrm::DestroyWidget $widgets($key)} err]} {
            log "CLOSE FAILED $key: $err (handle retained)"
        } else { log "CLOSED $key"; unset widgets($key) }
    }
}

puts "EDAKIT_CEF: Ready. Use ::edakitCefProbe::open view probe"

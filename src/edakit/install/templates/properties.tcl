# ASCII only: Capture 17.2 may source plugin files using the system code page.
if {[info exists ::edakit::properties::loaded]} { return }
namespace eval ::edakit::properties {
    variable loaded 1
    variable running 0
    variable snapshots [dict create]
    proc directory {} {
        set d [file join [::edakit::locateAppDir] properties]
        file mkdir $d
        return $d
    }
    proc readWire {path} {
        set f [open $path r]; fconfigure $f -encoding ascii
        set text [read $f]; close $f
        set out [dict create]
        foreach line [split $text \n] {
            if {$line eq ""} { continue }
            if {![regexp {^([^=]+)=([a-fA-F0-9]*)$} $line -> key value] || [string length $value] % 2} { error "Invalid property frame" }
            dict set out $key [encoding convertfrom utf-8 [binary format H* $value]]
        }
        return $out
    }
    proc writeWire {path data} {
        set f [open "$path.tmp" w]; fconfigure $f -encoding ascii -translation lf
        dict for {key value} $data {
            binary scan [encoding convertto utf-8 $value] H* hex
            puts $f "$key=$hex"
        }
        close $f; file rename -force "$path.tmp" $path
    }
    proc stringCall {obj method} {
        set c [DboTclHelper_sMakeCString]
        set s [$obj $method $c]
        set value [DboTclHelper_sGetConstCharPtr $c]
        catch {$s -delete}; DboTclHelper_sDeleteCString $c
        return $value
    }
    proc active {} {
        set d [$::DboSession_s_pDboSession GetActiveDesign]
        if {$d eq "NULL" || $d eq ""} { error "Open a Capture design first" }
        return $d
    }
    proc props {obj} {
        set state [DboState]
        set iter [$obj NewEffectivePropsIter $state]
        set name [DboTclHelper_sMakeCString]; set value [DboTclHelper_sMakeCString]
        set type [DboTclHelper_sMakeDboValueType]; set edit [DboTclHelper_sMakeInt]
        set out [dict create]
        set s [$iter NextEffectiveProp $name $value $type $edit]
        while {[$s OK]} {
            set n [DboTclHelper_sGetConstCharPtr $name]
            set v [DboTclHelper_sGetConstCharPtr $value]
            dict set out $n [list $v [expr {![DboTclHelper_sGetInt $edit]}]]
            catch {$s -delete}
            set s [$iter NextEffectiveProp $name $value $type $edit]
        }
        catch {$s -delete}; delete_DboEffectivePropsIter $iter
        DboTclHelper_sDeleteCString $name; DboTclHelper_sDeleteCString $value
        catch {$state -delete}
        return $out
    }
    # Walk instantiated hierarchy, not source library pages. Repeated hierarchy
    # gets a separate path, even when symbols share the same source object.
    proc walk {parent path state outName} {
        upvar 1 $outName out
        if {[llength $path] > 100} { error "Hierarchy nesting exceeds 100" }
        set iter [$parent NewChildrenIter $state $::IterDefs_INSTS]
        set child [$iter NextOccurrence $state]
        while {$child ne "NULL"} {
            set occ [DboOccurrenceToDboInstOccurrence $child]
            set id [$occ GetId $state]
            set next [concat $path [list $id]]
            set part [$occ GetPartInst $state]
            if {$part ne "NULL" && [$part GetObjectType] == $::DboBaseObject_PLACED_INSTANCE} {
                dict set out [join $next /] [list $occ $part [stringCall $occ GetReference]]
            }
            walk $occ $next $state out
            set child [$iter NextOccurrence $state]
        }
        delete_DboOccurrenceChildrenIter $iter
    }
    proc collect {design} {
        set state [DboState]
        set root [$design GetRootOccurrence $state]
        if {$root eq "NULL"} { catch {$state -delete}; error "Design has no root occurrence" }
        set out [dict create]
        walk $root [list [$root GetId $state]] $state out
        catch {$state -delete}
        return [list $root $out]
    }
    proc readContextIds {scope} {
        set state [DboState]; set out [list]
        set parent [GetInstanceOccurrence]
        if {$parent eq "NULL"} { error "Activate a schematic page first" }
        if {$scope eq "selected"} {
            set parts [GetSelectedObjects]
        } else {
            set parts [list]; set page [GetActivePage]
            if {$page eq "NULL"} { catch {$state -delete}; error "Activate a schematic page first" }
            set iter [$page NewPartInstsIter $state]
            set part [$iter NextPartInst $state]
            while {$part ne "NULL"} { lappend parts $part; set part [$iter NextPartInst $state] }
            delete_DboPagePartInstsIter $iter
        }
        foreach part $parts {
            if {[$part GetObjectType] != $::DboBaseObject_PLACED_INSTANCE} { continue }
            set occ [$part GetObjectOccurrence $parent]
            if {$occ ne "NULL"} { lappend out [DboOccurrenceToDboInstOccurrence $occ] }
        }
        catch {$state -delete}
        return $out
    }
    # A CEF dock can take focus away from the schematic. Cache selection while
    # the schematic is active; compare pointer strings only against fresh rows.
    proc captureContext {} {
        variable contextDesign
        variable contextSelected
        variable contextPage
        variable contextParent
        set design [active]
        set selected [readContextIds selected]
        set page [readContextIds page]
        set contextSelected $selected
        set contextPage $page
        set contextParent [GetInstanceOccurrence]
        set contextDesign "$design|[stringCall $design GetName]"
    }
    proc selectedIds {scope} {
        variable contextDesign
        variable contextSelected
        variable contextPage
        if {[::edakit::schematicActive]} { captureContext }
        set design [active]
        if {![info exists contextDesign] || $contextDesign ne "$design|[stringCall $design GetName]"} { error "Activate a schematic page and select components, then reopen Properties" }
        if {$scope eq "selected"} { return $contextSelected }
        return $contextPage
    }
    proc groupKey {id reference} {
        if {[regexp {^[^?]+[0-9]+$} $reference]} { return [list [lrange [split $id /] 0 end-1] $reference] }
        return [list $id]
    }
    proc handle {req job} {
        variable snapshots
        set design [active]
        set designName [stringCall $design GetName]
        lassign [collect $design] root objects
        set token "$design|$designName"
        set action [dict get $req action]
        set out [dict create ok 1 action $action design $token root $root]
        if {$action eq "snapshot"} {
            set scope [dict get $req scope]; set ids [list]
            set groups [dict create]
            if {$scope ne "design"} {
                set ids [selectedIds $scope]
                dict for {id data} $objects {
                    lassign $data occ part reference
                    if {[lsearch -exact $ids $occ] >= 0} { dict set groups [groupKey $id $reference] 1 }
                }
            }
            set i 0; set original [dict create]
            dict for {id data} $objects {
                lassign $data occ part reference
                if {$scope ne "design" && ![dict exists $groups [groupKey $id $reference]]} { continue }
                set properties [props $occ]
                # The read-only identity always comes from the occurrence API.
                dict set properties Reference [list $reference 1]
                dict set out $i.id $id; dict set out $i.reference $reference
                set label $id
                set pageState [DboState]
                if {![catch {set owner [$part GetOwner $pageState]; set pageName [stringCall $owner GetName]}] && $pageName ne ""} { set label "$pageName / $id" }
                catch {$pageState -delete}
                dict set out $i.path $label
                set j 0
                dict for {name values} $properties {
                    dict set out $i.$j.name $name
                    dict set out $i.$j.value [lindex $values 0]
                    dict set out $i.$j.readonly [lindex $values 1]
                    incr j
                }
                dict set original $id [list $reference $properties]
                dict set out $i.props $j; incr i
            }
            dict set out rows $i
            # Native-side originals prevent accidental or crafted stale writes.
            dict set snapshots $job [list $token $root $original]
            if {[dict size $snapshots] > 20} { dict unset snapshots [lindex [dict keys $snapshots] 0] }
            return $out
        }
        if {[dict get $req design] ne $token || [dict get $req root] ne $root} { error "Active design changed; refresh the table" }
        set originalJob [dict get $req snapshot]
        if {![dict exists $snapshots $originalJob]} { error "Snapshot expired; refresh the table" }
        lassign [dict get $snapshots $originalJob] originalDesign originalRoot originalRows
        if {$originalDesign ne $token || $originalRoot ne $root} { error "Snapshot belongs to another design" }
        set count [dict get $req count]
        if {![string is integer -strict $count] || $count < 1 || $count > 2000} { error "Invalid change count" }
        set i 0
        while {$i < $count} {
            set id [dict get $req $i.id]
            dict set out $i.id $id
            dict set out $i.state error
            if {[catch {
                if {![dict exists $objects $id]} { error "Component no longer exists; refresh" }
                lassign [dict get $objects $id] occ part reference
                if {$reference ne [dict get $req $i.reference]} { error "Reference changed; refresh" }
                if {$action eq "locate"} {
                    # Selection is valid only in the currently active hierarchy.
                    set state [DboState]
                    set current [GetInstanceOccurrence]
                    if {$current eq "NULL" && [info exists ::edakit::properties::contextParent]} { set current $::edakit::properties::contextParent }
                    if {$current eq "NULL" || [DboOccurrenceToDboInstOccurrence [$part GetObjectOccurrence $current]] ne $occ} { catch {$state -delete}; error "Open this component's schematic hierarchy before locating" }
                    SelectObjectById [$part GetId $state]
                    catch {$state -delete}
                } elseif {$action eq "apply"} {
                    set name [dict get $req $i.name]
                    dict set out $i.name $name
                    if {[string tolower $name] in {reference {part reference} id path occurrence page schematic design {source library} {source package} {source part}} || $name eq "" || [string length $name] > 128 || [regexp {[\x00-\x1f]} $name]} { error "Read-only or invalid property" }
                    if {![dict exists $originalRows $id]} { error "Unknown snapshot component" }
                    lassign [dict get $originalRows $id] originalReference originalProps
                    set originalExists [dict exists $originalProps $name]
                    set originalValue ""
                    if {$originalExists} { set originalValue [lindex [dict get $originalProps $name] 0] }
                    if {$originalReference ne $reference || $originalExists != [dict get $req $i.exists] || $originalValue ne [dict get $req $i.old]} { error "Invalid snapshot original value" }
                    set current [props $occ]
                    set exists [dict exists $current $name]
                    set old ""; set readonly 0
                    if {$exists} { lassign [dict get $current $name] old readonly }
                    if {$readonly} { error "Property is read-only" }
                    set value [dict get $req $i.value]
                    if {$exists && $old eq $value} {
                        dict set out $i.state unchanged
                    } elseif {$exists != [dict get $req $i.exists] || $old ne [dict get $req $i.old]} {
                        dict set out $i.state conflict
                        error "Property changed in Capture; refresh before editing again"
                    } else {
                        set n [DboTclHelper_sMakeCString $name]; set v [DboTclHelper_sMakeCString $value]
                        set s [$occ SetEffectivePropStringValue $n $v]
                        set ok [$s OK]; catch {$s -delete}
                        DboTclHelper_sDeleteCString $n; DboTclHelper_sDeleteCString $v
                        if {!$ok} { error "Capture rejected the property value" }
                        catch {$part MarkModified}
                        catch {$design MarkModified}
                        set check [props $occ]
                        if {![dict exists $check $name] || [lindex [dict get $check $name] 0] ne $value} { error "Readback differs; inspect Capture and refresh" }
                        dict set out $i.state applied
                    }
                    dict set out $i.value $value
                } else { error "Invalid property action" }
                if {[dict get $out $i.state] eq "error"} { dict set out $i.state done }
            } message]} { dict set out $i.message $message }
            incr i
        }
        dict set out count $count
        return $out
    }
    proc poll {} {
        variable running
        if {$running} { return }
        set running 1
        if {[::edakit::schematicActive]} { catch {captureContext} }
        set failed [catch {
            set dir [directory]
            foreach path [lsort [glob -nocomplain -directory $dir *.req]] {
                if {![regexp {^([a-f0-9]{32})\.req$} [file tail $path] -> job]} { continue }
                set req [readWire $path]
                if {[dict get $req session] ne $::edakit::sessionId} { continue }
                set work "$path.work"
                file rename $path $work
                if {[catch {
                    if {[clock seconds] > [dict get $req expires]} { error "Property request expired; refresh" }
                    set out [handle $req $job]
                } message]} { set out [dict create ok 0 message $message] }
                writeWire [file join $dir $job.resp] $out
                file delete $work
                break
            }
        } message]
        if {$failed} { catch {::edakit::writeDiag "Property queue: $message"} }
        set running 0
    }
    proc openPanel {{scope design}} {
        ::edakit::writeDiag "Property menu open requested"
        if {[::edakit::schematicActive]} { catch {captureContext} }
        # Use exactly the mall's working service and native CEF lifecycle.
        # Capture may not dispatch plain Tcl after callbacks while a dock closes.
        set url [::edakit::ensureServer]
        if {$url eq ""} { error "Local EdaKit server is unavailable" }
        showPanel $url $scope
    }
    proc showPanel {url scope} {
        return [::edakit::openWorkbench $url properties $scope]
    }
}
proc edakitProperties {args} {
    if {[catch {::edakit::properties::openPanel} e]} {
        ::edakit::writeDiag "Property menu failed: $e"
        ::edakit::showText "EdaKit Properties" $e
    }
}

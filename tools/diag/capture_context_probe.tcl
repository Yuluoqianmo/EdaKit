# Read-only Capture console probe. ASCII for legacy Tcl source encodings.
if {![namespace exists ::edakit::properties]} {error "Load EdaKit before running this probe"}
set probeState [DboState]
set probeParent [GetInstanceOccurrence]
set probePage [GetActivePage]
puts "EdaKit context probe (read only)"
puts "parent=$probeParent page=$probePage"
if {[catch {$probeParent GetId $probeState} probeId]} {
    puts "Native occurrence ID unavailable; fingerprint will use full-read fallback"
} else {puts "nativeOccurrenceId=$probeId"}
if {[catch {::edakit::properties::pageFingerprint} probeKey]} {
    puts "Fingerprint unavailable: full-read fallback will be used"
} else {puts "fingerprint=$probeKey"}
catch {$probeState -delete}
unset probeState probeParent probePage

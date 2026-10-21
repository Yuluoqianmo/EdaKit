"""Prepare an isolated, normalized Capture library acceptance script.

Run the emitted build_library.tcl inside Capture; Python does not drive its UI.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from edakit.easyeda.parse import parse_component
from edakit.symbol.capture_lib import generate_lib_xml, normalize_capture_symbol, u


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--part', default='RP2040_P7')
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    comp = parse_component('C2040', json.loads(
        (ROOT/'tests/data/C2040.json').read_text(encoding='utf-8')))
    prepared = normalize_capture_symbol(comp.symbol)
    raw_xml = folder/'input.olb.xml'
    raw_olb = folder/'intermediate.olb'
    norm_xml = folder/'normalized.xml'
    final_olb = folder/'C2040_P7.olb'
    final_xml = folder/'final.roundtrip.xml'
    raw_xml.write_text(generate_lib_xml(comp.symbol,
        lib_path=final_olb.as_posix(), package_name=args.part,
        footprint='C2040_QFN56_EP'), encoding='utf-8')
    # Convert into a fresh final library after Capture has normalized its XML.
    # Do not overwrite an OLB that Capture may already have loaded.
    from edakit.symbol.tcl import _tcl_str
    def q(path):
        return '"' + _tcl_str(path.as_posix()) + '"'
    commands = [
        'if {[llength [info commands XMATIC_XML2OLB]] == 0} {error "XMATIC_XML2OLB unavailable"}',
        f'if {{[file exists {q(final_olb)}]}} {{error "Final OLB exists; preserve it and use a new directory"}}',
        f'XMATIC_XML2OLB {q(raw_xml)} {q(raw_olb)}',
        f'XMATIC_OLB2XML {q(raw_olb)} {q(norm_xml)}',
        f'if {{![file exists {q(norm_xml)}]}} {{error "Capture normalization XML missing"}}',
        f'XMATIC_XML2OLB {q(norm_xml)} {q(final_olb)}',
        f'XMATIC_OLB2XML {q(final_olb)} {q(final_xml)}',
        f'if {{![file exists {q(final_olb)}] || ![file exists {q(final_xml)}]}} {{error "Final library/readback missing"}}',
        'puts "EDAKIT_NORMALIZED_LIBRARY_READY"',
    ]
    (folder/'build_library.tcl').write_text('\n'.join(commands)+'\n', encoding='utf-8')
    (folder/'place_native.tcl').write_text(native_placement_script(final_olb, args.part), encoding='utf-8')
    report = [{'number': a.number, 'source_name': a.name, 'capture_name': b.name,
               'electrical_type': b.electrical_type,
               'hotpoint_capture_units': [u(b.x_mm), -u(b.y_mm)]}
              for a, b in zip(comp.symbol.pins, prepared.pins)]
    (folder/'pin-normalization.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(folder/'build_library.tcl')


def native_placement_script(library: Path, part: str) -> str:
    """Use the user-verified plugin placement path, with a fresh library path."""
    from edakit.symbol.tcl import _tcl_str
    lib = _tcl_str(library.resolve().as_posix())
    name = _tcl_str(part)
    return f'''# Run in Capture after activating the test schematic page.
foreach cmd {{PlaceNew capGetMostRecentSchFrameID DboTclHelper_sGetConstCharPtr ui::SchematicActivate UnSelectAll capGetIsSchematicEditingDisabled}} {{
    if {{[llength [info commands $cmd]] == 0}} {{error "Missing native command: $cmd"}}
}}
if {{![file isfile "{lib}"]}} {{error "Normalized library missing"}}
set edakitTestFrame [DboTclHelper_sGetConstCharPtr [capGetMostRecentSchFrameID]]
ui::SchematicActivate $edakitTestFrame
if {{[capGetIsSchematicEditingDisabled]}} {{error "Schematic editing is disabled"}}
UnSelectAll
catch {{ZoomRedraw}}
set edakitTestCopy [file join [file dirname "{lib}"] "native_[pid]_[clock clicks].olb"]
file copy "{lib}" $edakitTestCopy
set edakitTestResult [PlaceNew $edakitTestCopy "{name}" 0]
if {{$edakitTestResult ne "1"}} {{error "PlaceNew rejected placement: $edakitTestResult"}}
puts "EDAKIT_NATIVE_ARMED: click schematic to place; Esc to finish"
'''


if __name__ == '__main__':
    main()

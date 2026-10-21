"""Prepare isolated Allegro acceptance inputs; never publish candidate libraries.

Run from the source environment. --probe checks only startup/SKILL execution,
not footprint construction. The output directory must not already exist.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from edakit.easyeda.model import Footprint, Pad, Pin, Symbol
from edakit.easyeda.parse import parse_component
from edakit.footprint.padstack import merge_padstacks
from edakit.footprint.skill import generate_skill
from edakit.footprint.validation import validate_pin_mapping


def skill_string(value: Path) -> str:
    return value.resolve().as_posix().replace('"', '\\"')


def manual_skill(candidate: str, drawing: Path) -> str:
    """Use a manually created, specifically named package drawing."""
    expected = drawing.resolve().as_posix().lower()
    guard = [
        '    (unless (axlIsSymbolEditor) (error "EdaKit: create a Package Symbol first"))',
        '    (unless (equal (lowerCase (axlDesignType t)) "package") (error "EdaKit: expected package symbol"))',
        '    (printf "EdaKit: drawing=%L cwd=%L resolved=%L\\n" (axlGetDrawingName) (getWorkingDir) (simplifyFilename (axlGetDrawingName)))',
        f'    (unless (equal (lowerCase (simplifyFilename (axlGetDrawingName))) (lowerCase (simplifyFilename "{expected}"))) (error "EdaKit: wrong test drawing path; see resolved path above"))',
    ]
    lines = []
    for line in candidate.splitlines():
        if '(when (isFile ' in line and '.dra"' in line:
            continue
        if '(unless (axlOpenDesign ' in line:
            lines.extend(guard)
            continue
        lines.append(line)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cadence", type=Path, default=Path("D:/Cadence/SPB_17.2"))
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    if not 5 <= args.timeout <= 60:
        parser.error("timeout must be between 5 and 60 seconds")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    pads = [Pad(number=str(i), x_mm=x, w_mm=0.8, h_mm=0.9,
                layers=["TOP"], layer_ids=["1"])
            for i, x in ((1, -0.9), (2, 0.9))]
    simple = Footprint(name="EK_NATIVE_2PIN", pads=pads,
                       padstacks=merge_padstacks(pads),
                       lines=[("TOP_SILK", [(-0.3, -0.55), (0.3, -0.55),
                                            (0.3, 0.55), (-0.3, 0.55)])])
    symbol = Symbol(name="EK_NATIVE_2PIN", pins=[Pin(number="1", name="A"),
                                                Pin(number="2", name="K")])
    comp = parse_component("C2040", json.loads(
        (ROOT / "tests/data/C2040.json").read_text(encoding="utf-8")))
    # Manual New Drawing can interpret the final dotted name segment as an
    # extension. Use an explicit test alias, preserving the source identity.
    source_footprint_name = comp.footprint.name
    comp.footprint.name = "C2040_QFN56_EP"
    cases = [("two_pin", symbol, simple), ("C2040", comp.symbol, comp.footprint)]
    for label, sym, fp in cases:
        report = validate_pin_mapping(sym, fp)
        if label == "C2040":
            report["source_footprint_name"] = source_footprint_name
            report["test_alias_only"] = True
        folder = output / label
        folder.mkdir()
        candidate = generate_skill(fp, output_dir=folder, refdes_prefix=sym.prefix)
        (folder / "candidate.il").write_text(candidate, encoding="utf-8")
        (folder / "manual_build.il").write_text(
            manual_skill(candidate, folder / (fp.name + ".dra")), encoding="utf-8")
        (folder / "pinmap.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"status": "prepared_only", "native_build_verified": False,
              "output": str(output), "cases": [case[0] for case in cases]}
    if args.probe:
        executable = args.cadence / "tools/bin/allegro.exe"
        reference = args.cadence / "share/pcb/examples/board_design/symbols/smdres.dra"
        if not executable.is_file() or not reference.is_file():
            raise FileNotFoundError("Allegro executable or official reference drawing missing")
        shutil.copy2(reference, output / "probe.dra")
        (output / "pcbenv").mkdir()
        marker = output / "probe.txt"
        # Only inspect a private copy of the official reference; never save it.
        (output / "probe.il").write_text(
            f'(let ((p (outfile "{skill_string(marker)}"))) '
            '(fprintf p "SKILL_STARTED\\nDESIGN %L\\n" (axlCurrentDesign)) (close p))\n',
            encoding="ascii")
        (output / "probe.scr").write_text(
            f'skill load("{skill_string(output / "probe.il")}")\nexit\n', encoding="ascii")
        environment = os.environ.copy()
        environment["ALLEGRO_PCBENV"] = str(output / "pcbenv")
        command = [str(executable), "-product", "Allegro_PCB_Designer", "-s",
                   str(output / "probe.scr"), str(output / "probe.dra")]
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        with (output / "process-output.txt").open("wb") as stream:
            process = subprocess.Popen(command, cwd=output, env=environment,
                                       startupinfo=startup, stdout=stream, stderr=subprocess.STDOUT)
            result["pid"] = process.pid
            try:
                result["returncode"] = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                # Terminate only the process created here; leave user sessions alone.
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                result["timed_out"] = True
        result["skill_started"] = marker.is_file() and "SKILL_STARTED" in marker.read_text(errors="replace")
        result["status"] = "startup_probe_passed" if result["skill_started"] else "startup_probe_failed"
        result["note"] = "Startup probe only; no native footprint acceptance implied."
    (output / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "startup_probe_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

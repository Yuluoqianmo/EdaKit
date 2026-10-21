"""Reuse deterministic Capture inputs, without regenerating timestamped XML."""
import hashlib
import json
from pathlib import Path
from ..storage import atomic_write

# Bump when Capture XML generation semantics change.
CAPTURE_FORMAT_VERSION = 8

# Change the library identity as well as the disk cache key: Capture can retain
# older definitions in an open design even after the source OLB is rebuilt.
CAPTURE_PART_REVISION = "P8"


def prepare_xml(work: Path, cid: str, inputs: dict, generate):
    key = hashlib.sha256(json.dumps({"version": CAPTURE_FORMAT_VERSION, **inputs},
        ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    path = work / f"{cid}.capture-{key}.olb.xml"
    receipt = path.with_suffix(path.suffix + ".cache.json")
    try:
        metadata = json.loads(receipt.read_text(encoding="utf-8"))
        if metadata["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest():
            return path, True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    xml = generate()
    atomic_write(path, xml)
    atomic_write(receipt, json.dumps({"sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest()}))
    return path, False

"""Deterministic, bounded Capture OLB package identifiers."""
import hashlib
import re


def capture_part_name(name: str, cid: str, *, revision: str = "") -> str:
    original = (name or "").strip() or cid or "PART"
    if revision and not re.fullmatch(r"[A-Z0-9]{1,6}", revision):
        raise ValueError("Invalid Capture symbol revision")
    short_suffix = "_" + revision if revision else ""
    # Keep already working names intact, including short Unicode model names.
    if len((original + short_suffix).encode("utf-8")) <= 31 and not any(ord(c) < 32 for c in original):
        return original + short_suffix
    identifier = (cid or "").strip().upper()
    if not re.fullmatch(r"C\d{1,16}", identifier):
        identifier = hashlib.sha256((cid + "\0" + original).encode("utf-8")).hexdigest()[:12].upper()
    suffix = "_" + identifier + short_suffix
    prefix = re.sub(r"[^A-Za-z0-9_-]", "_", original)[:31 - len(suffix)]
    return (prefix or "P") + suffix

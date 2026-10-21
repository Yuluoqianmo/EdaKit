"""Shared Capture/Allegro package library identity."""
import hashlib
import re


def footprint_name(name: str) -> str:
    if re.fullmatch(r'[A-Za-z0-9_-]{1,31}', name):
        return name
    stem = re.sub(r'[^A-Za-z0-9_-]', '_', name).strip('_') or 'PKG'
    return stem[:20] + '_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:10]

"""Versioned, paired library identities for production generation."""
from dataclasses import asdict
import hashlib
import json
import re

NAMING_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode('ascii')).hexdigest()


def library_names(component):
    cid = component.cid.upper()
    if not re.fullmatch(r'C[0-9]{1,11}', cid):
        cid = 'X' + hashlib.sha256(cid.encode('utf-8')).hexdigest()[:10].upper()
    pcb = digest({'format': 1, 'footprint': asdict(component.footprint) if component.footprint else None,
                  'prefix': component.symbol.prefix if component.symbol else ''})
    symbol = digest({'format': 9, 'symbol': asdict(component.symbol) if component.symbol else None,
                     'pcb': pcb})
    return {'symbol': f'EK_{cid}_S_{symbol[:8]}_P9',
            'footprint': f'EK_{cid}_F_{pcb[:10]}',
            'geometryDigest': pcb, 'symbolDigest': symbol, 'namingVersion': NAMING_VERSION}

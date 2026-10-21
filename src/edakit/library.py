"""Versioned, paired library identities for production generation."""
from dataclasses import asdict
import hashlib
import json
import re
from .footprint.identity import geometry

NAMING_VERSION = 2


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode('ascii')).hexdigest()


def package_label(component):
    """Readable classification; dimensions are only taken from explicit labels."""
    fp = component.footprint
    if fp is None:
        return 'PKG'
    source = fp.name.upper()
    prefix = (component.symbol.prefix if component.symbol else 'U').strip().rstrip('?*') or 'U'
    passive = re.fullmatch(r'(?:R|RES|C|CAP|L|IND)[_-]?(\d{4})(?:[_-].*)?', source)
    if passive and prefix in {'R', 'C', 'L'}:
        return prefix + passive[1]
    match = re.match(r'(LQFN|QFN|DFN|TSSOP|SSOP|MSOP|TSOP|PSOP|SOIC|SOP|LQFP|TQFP|PQFP|QFP|BGA|SOT|SC|TO|DIP|SIP|FPC|CON|USB|LED)(?=[\d_-]|$)', source)
    family = match[1] if match else re.sub('[^A-Z0-9]', '', prefix)[:4] or 'PKG'
    family = {'LQFN': 'QFN', 'TSSOP': 'SOP', 'SSOP': 'SOP', 'MSOP': 'SOP',
              'TSOP': 'SOP', 'PSOP': 'SOP', 'SOIC': 'SOP',
              'LQFP': 'QFP', 'TQFP': 'QFP', 'PQFP': 'QFP'}.get(family, family)
    label = family + str(len(fp.padstacks))
    subtype = re.match(r'(?:SOT|SC|TO)[_-]?(\d+)(?:$|[_-])', source)
    if subtype:
        label = family + subtype[1] + '_' + str(len(fp.padstacks))
    pitch = re.search(r'(?:^|[_-])P(\d+(?:\.\d+)?)', source)
    if pitch:
        value = pitch[1].rstrip('0').rstrip('.') if '.' in pitch[1] else pitch[1]
        label += '_' + value.replace('.', 'D')
    dims = re.search(r'[_-]L(\d+(?:\.\d+)?)[_-]W(\d+(?:\.\d+)?)', source)
    if dims:
        def dimension(v):
            return (v.rstrip('0').rstrip('.') if '.' in v else v).replace('.', 'D')
        label += '_' + dimension(dims[2]) + 'X' + dimension(dims[1])
    suffix = '_EP' if re.search(r'(?:^|[_-])EP(?:$|[_-])', source) else ''
    return label[:20-len(suffix)] + suffix


def library_names(component):
    cid = component.cid.upper()
    if not re.fullmatch(r'C[0-9]{1,11}', cid):
        cid = 'X' + hashlib.sha256(cid.encode('utf-8')).hexdigest()[:10].upper()
    label = package_label(component)
    prefix = (component.symbol.prefix if component.symbol else '').strip().rstrip('?*') or 'U'
    pcb = digest({'format': 2, 'footprint': geometry(component.footprint),
                  'prefix': prefix, 'packageClass': label})
    symbol = digest({'format': 9, 'symbol': asdict(component.symbol) if component.symbol else None,
                     'pcb': pcb})
    return {'symbol': f'EK_{cid}_S_{symbol[:8]}_P9',
            'footprint': f'{label}_{pcb[:10].upper()}',
            'geometryDigest': pcb, 'symbolDigest': symbol, 'namingVersion': NAMING_VERSION}

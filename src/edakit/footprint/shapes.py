"""Native shape symbols used by custom copper padstacks.

Each SSM contains one connected, void-free copper outline at the pad origin.
The build manifest includes every dependency so publication cannot lose it.
"""
import hashlib
import json
import math
from .identity import native_precision, normalized
from .geometry import polygon


def shape_name(layer):
    data = json.dumps(normalized(layer.polygon_mm), separators=(',', ':'))
    return 'eks_' + hashlib.sha256(data.encode()).hexdigest()[:20]


def shape_scripts(footprint, folder):
    from .skill import _s, _pt, _check
    from .coordinates import native_cartesian
    result = {}
    for pad in native_precision(native_cartesian(footprint)).padstacks:
        for layer in pad.layers:
            if layer.shape != 'SHAPE':
                continue
            name = shape_name(layer)
            if name in result:
                continue
            poly = polygon(layer.polygon_mm)
            vertices = list(poly.exterior.coords)
            coords = ' '.join(_pt(x, y) for x, y in vertices)
            x1,y1,x2,y2 = poly.bounds
            base = (folder / name).resolve().as_posix()
            result[name] = '\n'.join([
                _check('(axlSetSymbolType "shape")', 'shape symbol type'),
                _check('(axlDBChangeDesignUnits "millimeters" 4)', 'shape units'),
                # The private package seed already spans these small pad
                # coordinates. Do not shrink extents around template settings.
                _check(f'(axlDBCreateShape (axlPathStart (list {coords})) t "ETCH/TOP")', 'custom copper'),
                _check('(axlSaveDesign ?noMru t)', 'shape save'),
                _check(f'(axlCompileSymbol ?symbol "{_s(base)}" ?type "shape")', 'shape compile'),
            ]) + '\n'
    return result

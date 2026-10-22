"""Reflect source canvas Y once at the native right-handed CAD boundary."""
from copy import deepcopy


def native_cartesian(footprint):
    fp = deepcopy(footprint)
    if getattr(fp, '_native_cartesian', False):
        return fp
    fp._native_cartesian = True
    def points(values):
        return [(x, -y) for x,y in values]
    for pad in fp.pads:
        pad.y_mm = -pad.y_mm
        pad.rotation_deg = -pad.rotation_deg
        pad.polygon_mm = points(pad.polygon_mm)
        pad.hole_points_mm = points(pad.hole_points_mm)
    for pad in fp.padstacks:
        pad.y_mm = -pad.y_mm
        pad.rotation_deg = -pad.rotation_deg
        pad.drill_offset_y_mm = -pad.drill_offset_y_mm
        for layer in pad.layers:
            layer.polygon_mm = points(layer.polygon_mm)
    fp.lines = [(layer, points(pts)) for layer,pts in fp.lines]
    fp.circles = [(layer,x,-y,r) for layer,x,y,r in fp.circles]
    seen = set()
    for primitive in [*fp.primitives, *fp.solid_regions]:
        if id(primitive) in seen:
            continue
        seen.add(id(primitive))
        if primitive.kind == 'SVGNODE':
            continue
        geom = primitive.geom
        for key in ('y_mm', 'y2_mm'):
            if key in geom:
                geom[key] = -geom[key]
        if 'points_mm' in geom:
            geom['points_mm'] = [v if i % 2 == 0 else -v for i,v in enumerate(geom['points_mm'])]
        if 'rings_mm' in geom:
            geom['rings_mm'] = [points(ring) for ring in geom['rings_mm']]
        for arc in geom.get('arcs', []):
            arc['start'] = (arc['start'][0], -arc['start'][1])
            arc['end'] = (arc['end'][0], -arc['end'][1])
            arc['clockwise'] = not arc['clockwise']
    return fp

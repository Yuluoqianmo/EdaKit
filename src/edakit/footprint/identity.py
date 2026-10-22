"""Geometry identities at the native backend's 0.0001 mm precision."""
from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass
import hashlib
import json


def normalized(value):
    if isinstance(value, float):
        return round(value, 4) or 0.0
    if isinstance(value, dict):
        return {k: normalized(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalized(v) for v in value]
    return value


def ordered(values):
    return sorted(values, key=lambda v: json.dumps(v, sort_keys=True))


def native_precision(fp):
    """Round before computing derived bounds as well as before emitting coordinates."""
    def convert(value):
        if is_dataclass(value):
            for field in fields(value):
                setattr(value, field.name, convert(getattr(value, field.name)))
            return value
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [convert(v) for v in value]
        return normalized(value)
    return convert(deepcopy(fp))


def pad_definition(ps, drill_plated=True):
    layers = []
    for layer in ps.layers:
        data = asdict(layer)
        # Standard shapes are emitted from width/height, not the source's
        # absolute corner coordinates (which differ at every pin position).
        if layer.shape in {'RECT', 'CIRCLE', 'OBLONG', 'ROUNDED_RECT'}:
            data.pop('polygon_mm')
        layers.append(normalized(data))
    return {'format': 3, 'layers': ordered(layers),
            'drill': normalized(ps.drill_mm), 'plated': ps.hole_plated and drill_plated,
            'slot': normalized([ps.slot_width_mm, ps.slot_height_mm]),
            'drillOffset': normalized([ps.drill_offset_x_mm, ps.drill_offset_y_mm]),
            'mechanical': ps.mechanical}


def pad_name(ps, drill_plated=True):
    data = json.dumps(pad_definition(ps, drill_plated), sort_keys=True)
    return 'EK_' + hashlib.sha256(data.encode()).hexdigest()[:20]


def geometry(fp):
    if fp is None:
        return None
    tracks = [p for p in fp.primitives if p.kind == 'TRACK' and p.geom.get('points_mm')]
    circles = [p for p in fp.primitives if p.kind == 'CIRCLE' and 'r_mm' in p.geom]
    return normalized({
        'pins': ordered([{'number': p.name, 'x': normalized(p.x_mm), 'y': normalized(p.y_mm),
                         'rotation': normalized(p.rotation_deg), 'pad': pad_definition(p)}
                        for p in fp.padstacks]),
        'lines': ordered([normalized([layer, pts, tracks[i].geom['width_mm'] if i < len(tracks) else .12])
                          for i, (layer, pts) in enumerate(fp.lines)]),
        'circles': ordered([normalized([*circle, circles[i].geom['stroke_mm'] if i < len(circles) else .12])
                            for i, circle in enumerate(fp.circles)]),
        'regions': ordered([normalized(p.geom) for p in fp.solid_regions]),
        'apertures': ordered([normalized(asdict(p)) for p in fp.pads
                             if p.layers and all(l in {'TOP_PASTE','BOTTOM_PASTE','TOP_SOLDERMASK','BOTTOM_SOLDERMASK'} for l in p.layers)]),
        # Unsupported input must never match a previously compiled supported part.
        'unsupported': ordered([{'kind': p.kind, 'geom': p.geom, 'raw': p.raw}
                                for p in fp.primitives if p.kind in {'ARC', 'HOLE', 'RECT', 'RECTANGLE', 'VIA', 'COPPERAREA', 'KEEPOUT'}]),
    })

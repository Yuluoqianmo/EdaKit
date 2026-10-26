"""Preview classification uses the same source-to-Allegro mapping as export."""
from dataclasses import replace
from ..footprint.skill import SOLID_DRAW


MODES = {'all': '全部图层', 'pads': '焊盘与钻孔', 'silk': '丝印', 'assembly': '装配外形'}


def category(layer):
    native = SOLID_DRAW.get(layer, '')
    if 'SILKSCREEN' in native:
        return 'silk'
    if 'ASSEMBLY' in native:
        return 'assembly'
    return 'other'


def filtered(fp, mode):
    if mode not in MODES:
        raise ValueError('未知预览图层')
    if mode == 'all':
        return fp
    return replace(fp,
        pads=fp.pads if mode == 'pads' else [],
        padstacks=fp.padstacks if mode == 'pads' else [],
        lines=[x for x in fp.lines if category(x[0]) == mode],
        circles=[x for x in fp.circles if category(x[0]) == mode],
        primitives=[x for x in fp.primitives if category(x.geom.get('layer', '')) == mode],
        solid_regions=[x for x in fp.solid_regions if category(x.geom.get('layer', '')) == mode])

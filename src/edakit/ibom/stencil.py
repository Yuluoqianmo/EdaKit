"""Stencil catalogue and single-board envelope checks (dimensions are millimetres)."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class Spec:
    value: str
    outer: tuple[float, float]
    effective: tuple[float, float]

    @property
    def label(self):
        return self.value+'  ·  有效 '+dimensions(tuple(v/10 for v in self.effective), 'cm')


def dimensions(pair, unit='mm'):
    return ' × '.join(f'{v:g}' for v in pair)+' '+unit


CATALOGUE = tuple(Spec(outer+' cm', tuple(float(x)*10 for x in outer.split('×')),
                       tuple(float(x)*10 for x in area.split('×')))
                  for outer, area in (
                      ('37×47', '20×30'), ('30×40', '14×24'), ('42×52', '24×34'),
                      ('45×55', '27×37'), ('58.4×58.4', '38×38'), ('55×65', '34×44'),
                      ('73.6×73.6', '50×50'), ('40×60', '22×40'), ('40×80', '22×60'),
                      ('40×100', '22×76'), ('40×120', '22×100'), ('40×140', '22×120')))


def parse_dimensions(value):
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(mm|cm)\s*', value, re.I)
    if not match:
        return None
    factor = 10 if match[3].lower() == 'cm' else 1
    result = tuple(float(match[i])*factor for i in (1, 2))
    return result if all(math.isfinite(v) and v > 0 for v in result) else None


def lookup(value):
    for spec in CATALOGUE:
        if value == spec.label or parse_dimensions(value) == spec.outer:
            return spec
    return None


def fit(spec, board, angle=None):
    """No manufacturing margin or top/bottom nesting is assumed by this check."""
    if spec is None or board is None:
        return None
    ew, eh = spec.effective
    width, height = board
    rotated = angle == 90
    if rotated:
        width, height = height, width
    fits = width <= ew and height <= eh
    if angle is None and not fits and height <= ew and width <= eh:
        width, height = height, width
        rotated, fits = True, True
    return dict(fits=fits, rotated=rotated, board=(width, height),
                margin=((ew-width)/2, (eh-height)/2))

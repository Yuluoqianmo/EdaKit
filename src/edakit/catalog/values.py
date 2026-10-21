"""Interpret a complete passive value as a parameter, never as a model substring.

The wm API matches parameter *labels*, e.g. 100nF rather than 0.1uF.
Keep this shared by product queries and package facets. Unknown/mixed text stays
literal; a suffix without a unit requires an unambiguous selected category.
"""
from decimal import Decimal, InvalidOperation
import re


# Real wm IDs from the category tree, not the Chinese site's catalog IDs.
_FAMILIES = {
    "Resistance": frozenset({501, 1198, 1199, 1200, 1201, 1202, 1203, 1336}),
    "Capacitance": frozenset({495, *range(1139, 1153), 1485}),
    "Inductance": frozenset({498, 1178, 1179, 1180, 1181, 1182}),
}
_PREFIX = {"": 0, "R": 0, "r": 0, "p": -12, "n": -9,
           "u": -6, "m": -3, "k": 3, "K": 3, "M": 6, "G": 9}


def value_catalog_ids(parameter: str) -> list[int]:
    """Explicit units without a selected category still need leaf IDs upstream."""
    return sorted(_FAMILIES[parameter] - {501, 495, 498})


def passive_value(keyword: str, catalog_ids: list[int]) -> tuple[str, str] | None:
    """Return (parameter name, canonical label) only for a complete value."""
    if len(keyword) > 80:
        return None
    text = re.sub(r"\s+", "", keyword).replace("µ", "u").replace("μ", "u")
    text = text.replace("Ω", "Ω")
    text = re.sub(r"(?i:ohms?)$|欧姆$|欧$", "Ω", text)
    selected = next((name for name, ids in _FAMILIES.items()
                     if catalog_ids and set(catalog_ids) <= ids), None)
    # Full unit wins only in the same selected family (or with no category).
    explicit = re.search(r"[ΩFfHh]$", text)
    family = {"Ω": "Resistance", "F": "Capacitance", "H": "Inductance"}.get(
        explicit.group().upper() if explicit else "")
    if family and catalog_ids and family != selected:
        return None
    family = family or selected
    if not family:
        return None
    if explicit:
        text = text[:-1]
    # Embedded decimal: 4K7, 2R2, 4u7. '4K7' without a category stays literal.
    embedded = re.fullmatch(r"(\d+)([RrpPkKnNumMGuU])(\d+)", text)
    if embedded:
        number, prefix, fraction = embedded.groups()
        number += "." + fraction
    else:
        match = re.fullmatch(r"(\d+(?:\.\d+)?|\.\d+)([RrpPkKnNumMGuU]?)", text)
        if not match:
            return None
        number, prefix = match.groups()
    prefix = {"P": "p", "N": "n", "U": "u"}.get(prefix, prefix)
    if not explicit and not prefix:
        # Bare digits can be package/model numbers (0603, 104, ...).
        return None
    if family == "Resistance" and prefix not in ("", "R", "r", "m", "k", "K", "M", "G"):
        return None
    if family != "Resistance" and prefix in ("R", "r", "K", "k", "M", "G"):
        return None
    try:
        value = Decimal(number) * (Decimal(10) ** _PREFIX[prefix])
    except (InvalidOperation, KeyError):
        return None
    choices = ([('G', 9), ('M', 6), ('k', 3), ('', 0), ('m', -3)]
               if family == "Resistance" else
               [('', 0), ('m', -3), ('u', -6), ('n', -9), ('p', -12)])
    unit = {"Resistance": "Ω", "Capacitance": "F", "Inductance": "H"}[family]
    if value == 0:
        return family, "0" + unit
    for suffix, exponent in choices:
        scaled = value / (Decimal(10) ** exponent)
        if scaled >= 1 or exponent == choices[-1][1]:
            label = format(scaled, 'f')
            if '.' in label:
                label = label.rstrip('0').rstrip('.')
            return family, label + suffix + unit
    return None

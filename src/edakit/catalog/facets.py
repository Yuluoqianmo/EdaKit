"""Catalog-dependent filters; upstream keys and values remain unchanged on the wire."""
from __future__ import annotations

from typing import Any
from .glossary import parameter_display, value_label
PRIORITY = ["Resistance", "Capacitance", "Inductance", "CPU Core", "Tolerance",
            "Power(Watts)", "Voltage Rating", "Current Rating", "CPU Maximum Speed",
            "Voltage - Supply", "DC Resistance(DCR)", "Interface"]


def normalize_facets(raw: dict[str, Any], catalog_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """No values inferred from products, ranges, or current-page contents."""
    fields = []
    params = raw.get("paramNameValueMap") or {}
    for key, group in params.items():
        if not isinstance(group, dict):
            continue
        values = [{"value": str(x["name"]), "label": value_label(key, str(x["name"]))}
                  for x in group.get("paramDetailList") or [] if x.get("name") not in (None, "", "-")]
        if values:
            display = parameter_display(key, [v["value"] for v in values], catalog_ids or [])
            fields.append({"key": key, "kind": "param", "values": values, **display})
    fields.sort(key=lambda f: (PRIORITY.index(f["key"]) if f["key"] in PRIORITY else 100, f["key"]))
    packages = sorted({str(x["name"]).strip() for x in raw.get("Package") or []
                       if x.get("name") and str(x["name"]).strip() != "-"})
    if packages:
        fields.insert(1 if fields else 0, {"key": "Package", "label": "封装", "kind": "package",
                                        "values": [{"value": v, "label": v} for v in packages]})
    brands = [{"value": str(x["id"]), "label": str(x["name"])}
              for x in raw.get("Manufacturer") or [] if x.get("id") is not None and x.get("name")]
    if brands:
        fields.insert(min(4, len(fields)), {"key": "Manufacturer", "label": "品牌", "kind": "brand", "values": brands})
    return fields


def clean_params(params: dict[str, list[str]] | None) -> dict[str, list[str]]:
    if params is None:
        return {}
    if not isinstance(params, dict) or len(params) > 40:
        raise ValueError("筛选参数格式错误或数量过多")
    result = {}
    for key, values in params.items():
        if not isinstance(key, str) or not key or len(key) > 120 or not isinstance(values, list) or len(values) > 50:
            raise ValueError("筛选参数格式错误")
        if any(not isinstance(v, str) or not v or len(v) > 300 for v in values):
            raise ValueError("筛选值格式错误")
        if values:
            result[key] = list(dict.fromkeys(values))
    return result

"""生成 Capture 库 XML，供 ``XMATIC_XML2OLB`` 转成 .OLB。

=== 关于 schema 的头号说明 ===
OrCAD Capture 的库 XML schema **没有公开文档**。与其猜，本模块走「schema 自发现」:

  1. 你在 Capture 里手建一个参考元件，导出成 .olb;
  2. 跑 ``edakit learn-schema --olb ref.olb --roundtrip-xml ref.xml --out profile.json``,
     工具从 ``XMATIC_OLB2XML`` 的产物里抽出 profile (标签名/属性名);
  3. 之后 ``generate_olb_xml`` 就按这份 profile 填空。

没有 profile 时用下面那份 ``DEFAULT_PROFILE`` —— 标签名是推测值，**大概率要按你的
真实 schema 改名**。即: 不校准也能出结构完整的 XML，但能否被 XMATIC 吃下，取决于校准。
这是项目里唯一必须上机才能定的东西 (见技术方案 R1)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

from ..easyeda.model import Symbol

# 推测的默认 schema。字段名请按 learn-schema 的产物覆盖。
DEFAULT_PROFILE: dict[str, Any] = {
    "root": "CaptureLibrary",
    "root_attrs": {"Version": "1.0"},
    "part": "Part",
    "graphics": "Graphics",
    "rect": "Rectangle",
    "circle": "Circle",
    "polyline": "Polyline",
    "polygon": "Polygon",
    "text": "Text",
    "pins": "Pins",
    "pin": "Pin",
    "properties": "Properties",
    "property": "Property",
    "prop_names": {
        "description": "Description",
        "footprint": "PCB Footprint",
        "manufacturer": "Manufacturer",
        "mpn": "Manufacturer Part Number",
    },
}

# EasyEDA 引脚电气类型 → Capture 引脚类型。
# 未定义默认 Passive (与技术方案一致: 不按名字臆测 Power)。
PIN_TYPE_MAP = {
    "input": "Input",
    "output": "Output",
    "bidirectional": "Bidirectional",
    "power": "Power",
    "unspecified": "Passive",
    "passive": "Passive",
}


def load_schema_profile(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return dict(DEFAULT_PROFILE)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    merged = dict(DEFAULT_PROFILE)
    merged.update(data)
    return merged


def generate_olb_xml(
    sym: Symbol,
    *,
    footprint_name: str = "",
    profile: dict[str, Any] | None = None,
) -> str:
    """把一个 Symbol 渲染成 Capture 库 XML 字符串。"""
    p = profile or DEFAULT_PROFILE
    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    attrs = " ".join(f"{k}={quoteattr(str(v))}" for k, v in p["root_attrs"].items())
    out.append(f"<{p['root']} {attrs}>")
    out.append(f'  <{p["part"]} Name={quoteattr(sym.name)} RefDesPrefix={quoteattr(sym.prefix or "U")}>')
    out.append(f'    <{p["graphics"]}>')
    for prim in sym.primitives:
        rendered = _graphic(prim, p)
        if rendered is not None:
            out.append(rendered)
    out.append(f"    </{p['graphics']}>")

    out.append(f'    <{p["pins"]}>')
    for pin in sym.pins:
        ptype = PIN_TYPE_MAP.get(pin.electrical_type, "Passive")
        out.append(
            f'      <{p["pin"]} Number={quoteattr(pin.number)} '
            f'Name={quoteattr(pin.name)} X={quoteattr(f"{pin.x_mm:.4f}")} '
            f'Y={quoteattr(f"{pin.y_mm:.4f}")} '
            f'Orientation={quoteattr(f"{pin.orientation_deg:.1f}")} '
            f'Length={quoteattr(f"{pin.length_mm:.4f}")} '
            f'Type={quoteattr(ptype)} '
            f'Visible={quoteattr("1" if pin.visible else "0")} />'
        )
    out.append(f"    </{p['pins']}>")

    prop_names = p["prop_names"]
    props: dict[str, str] = {}
    if sym.description:
        props[prop_names["description"]] = sym.description
    if footprint_name:
        props[prop_names["footprint"]] = footprint_name
    if sym.manufacturer:
        props[prop_names["manufacturer"]] = sym.manufacturer
    if sym.mpn:
        props[prop_names["mpn"]] = sym.mpn
    props.update({k: v for k, v in sym.extra_props.items() if k not in props})
    out.append(f'    <{p["properties"]}>')
    for name, value in props.items():
        out.append(f'      <{p["property"]} Name={quoteattr(name)} Value={quoteattr(str(value))} />')
    out.append(f"    </{p['properties']}>")

    out.append(f"  </{p['part']}>")
    out.append(f"</{p['root']}>")
    return "\n".join(out) + "\n"


def _graphic(prim, p: dict[str, Any]) -> str | None:
    g = prim.geom
    k = prim.kind
    if k == "R" and "x2_mm" in g:
        x1, y1 = f"{g['x_mm']:.4f}", f"{g['y_mm']:.4f}"
        x2, y2 = f"{g['x2_mm']:.4f}", f"{g['y2_mm']:.4f}"
        return (
            f'      <{p["rect"]} X1={quoteattr(x1)} Y1={quoteattr(y1)} '
            f"X2={quoteattr(x2)} Y2={quoteattr(y2)} />"
        )
    if k == "C" and "r_mm" in g:
        cx, cy, r = f"{g['x_mm']:.4f}", f"{g['y_mm']:.4f}", f"{g['r_mm']:.4f}"
        return f'      <{p["circle"]} CX={quoteattr(cx)} CY={quoteattr(cy)} R={quoteattr(r)} />'
    if k in ("PL", "PG", "PT") and g.get("points_mm"):
        pts = g["points_mm"]
        pairs = " ".join(f"{pts[i]:.4f},{pts[i + 1]:.4f}" for i in range(0, len(pts) - 1, 2))
        tag = p["polygon"] if k == "PG" else p["polyline"]
        return f'      <{tag} Points={quoteattr(pairs)} />'
    if k == "T" and "text" in g:
        tx, ty = f"{g['x_mm']:.4f}", f"{g['y_mm']:.4f}"
        return (
            f'      <{p["text"]} X={quoteattr(tx)} Y={quoteattr(ty)} '
            f"Value={quoteattr(str(g['text']))} />"
        )
    return None


def _find_tag(xml_text: str, *names: str) -> str | None:
    """在 XML 文本里找出实际出现的标签名（去掉命名空间前缀）。

    注意别再用「捕获命名空间前缀的那个组」这种写法 —— 前缀是可选的，没前缀时
    那个组是 None，会把 profile 里的好默认值覆盖成 None。
    """
    alt = "|".join(re.escape(n) for n in names)
    m = re.search(rf"<\s*(?:[\w.-]+:)?({alt})\b", xml_text, re.IGNORECASE)
    return m.group(1) if m else None


def build_profile_from_olb_xml(xml_text: str) -> dict[str, Any]:
    """从 XMATIC_OLB2XML 的输出里抽出一份 schema profile。

    只做「抄骨架」: 把**确实出现过**的几个关键标签名抄下来，没找到的保留默认值。

    注意: 这只覆盖 profile 里已经列到的那些键。真正要把生成器改对，靠的是
    ``analyze_olb_xml`` 产出的完整结构清单（见 learn-schema 命令）。
    """
    prof = dict(DEFAULT_PROFILE)

    root = _find_tag(xml_text, "CaptureLibrary", "Library", "OLB")
    if root:
        prof["root"] = root

    found = _find_tag(xml_text, "Part")
    if found:
        prof["part"] = found

    found = _find_tag(xml_text, "PinList", "Pins", "PINLIST", "Pinslist")
    if found:
        prof["pins"] = found

    found = _find_tag(xml_text, "Props", "Properties", "PROPERTIES")
    if found:
        prof["properties"] = found

    found = _find_tag(xml_text, "Pin")
    if found:
        prof["pin"] = found

    found = _find_tag(xml_text, "Design", "Aliases", "Graphics")
    if found:
        prof["graphics"] = found

    return prof


def _local(tag: str) -> str:
    """去掉命名空间前缀：'{http://x}Pin' / 'ns:Pin' → 'Pin'。"""
    tag = tag.rsplit("}", 1)[-1]
    return tag.rsplit(":", 1)[-1]


def analyze_olb_xml(xml_text: str, *, max_samples: int = 3) -> dict[str, Any]:
    """把一份参考库 XML 的**完整结构**抄下来（元素路径 / 属性名 / 样例值 / 出现次数）。

    这是 ``learn-schema`` 真正有用的部分。``build_profile_from_olb_xml`` 只能认出
    DEFAULT_PROFILE 已经列到的键，而这里把**实际用到的标签与属性全量列出来**，
    这样就能拿它反推生成器该改哪些标签名，而不用靠猜。

    返回::

        {
          "root": "CaptureLibrary",
          "elementCount": 128,
          "elements": [
            {"path": "CaptureLibrary/Part/Pin",
             "count": 57,
             "attrs": {"Number": ["1", "2", "3"], "Name": ["GPIO0", ...]},
             "attrCount": {"Number": 57, "Name": 57}},
            ...
          ]
        }
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    acc: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def walk(el: ET.Element, prefix: str) -> None:
        path = f"{prefix}/{_local(el.tag)}" if prefix else _local(el.tag)
        slot = acc.get(path)
        if slot is None:
            slot = {"path": path, "count": 0, "attrs": {}, "attrCount": {}, "text": []}
            acc[path] = slot
            order.append(path)
        slot["count"] += 1
        for k, v in el.attrib.items():
            lk = _local(k)
            slot["attrCount"][lk] = slot["attrCount"].get(lk, 0) + 1
            samples = slot["attrs"].setdefault(lk, [])
            if v not in samples and len(samples) < max_samples:
                samples.append(v)
        if el.text and el.text.strip():
            t = el.text.strip()
            if t not in slot["text"] and len(slot["text"]) < max_samples:
                slot["text"].append(t)
        for child in el:
            walk(child, path)

    walk(root, "")

    elements = []
    for path in order:
        slot = acc[path]
        entry: dict[str, Any] = {
            "path": path,
            "count": slot["count"],
            "attrs": slot["attrs"],
            "attrCount": slot["attrCount"],
        }
        if slot["text"]:
            entry["text"] = slot["text"]
        elements.append(entry)

    return {
        "root": _local(root.tag),
        "rootAttrs": {_local(k): v for k, v in root.attrib.items()},
        "elementCount": sum(e["count"] for e in elements),
        "elements": elements,
    }


def render_schema_report(analysis: dict[str, Any], *, source: str = "") -> str:
    """把 analyze_olb_xml 的结果画成人读文本。"""
    lines = [
        "Capture 库 XML 结构清单",
        "=" * 64,
    ]
    if source:
        lines.append(f"来源: {source}")
    lines.append(f"根元素: {analysis['root']}  {analysis['rootAttrs'] or ''}")
    lines.append(f"元素总数: {analysis['elementCount']}")
    lines.append("")
    lines.append("路径（缩进表示层级） / 出现次数 / 属性(样例值)")
    lines.append("-" * 64)

    for e in analysis["elements"]:
        depth = max(0, e["path"].count("/"))
        name = e["path"].rsplit("/", 1)[-1]
        lines.append(f"{'  ' * depth}{name}   ×{e['count']}")
        for attr, samples in e["attrs"].items():
            n = e["attrCount"].get(attr, 0)
            shown = ", ".join(repr(s) for s in samples)
            more = f" …(共 {n} 种取值)" if n > len(samples) else ""
            lines.append(f"{'  ' * depth}    @{attr} = {shown}{more}")
        if e.get("text"):
            shown = ", ".join(repr(s) for s in e["text"])
            lines.append(f"{'  ' * depth}    #text = {shown}")

    lines += [
        "",
        "-" * 64,
        "怎么用这份清单：",
        "  把本文件发回给开发方。生成器 (symbol/olb_xml.py) 会按这里的真实标签名/属性名",
        "  改写，之后生成的 .olb.xml 才会被 XMATIC_XML2OLB 接受。",
        "  注意：清单里的标签名是**去掉命名空间前缀**后的；如果原文带前缀（如 ns0:Part），",
        "  改写生成器时要连同 xmlns 声明一起补上。",
    ]
    return "\n".join(lines) + "\n"

"""EasyEDA shape 解析。

EasyEDA 的几何用一套自有 canvas 指令表示，不是 SVG:
每条形如 ``指令名~字段~...``，段内 ``~`` 分隔，子段 ``^^`` 分隔。

    P~show~3~9~525~230~0~gge461~0^^525~230^^M 525 230 h -10~#880000^^1~511~233.75~0~GPIO7~end~Tahoma~5.8pt~#0000FF
    R~285~100~~~230~380~#000000~1~0~none~gge864~0
    PAD~RECT~3984.252~3012.9925~12.2047~12.2047~1~~57~0~3978.1494 3006.8904 ...
    TRACK~1~3~~3971.4922 2999.2134 ...~gge12576~0
    SVGNODE~{"gId":"g1_outline","nodeType":1,"layerid":"19","attrs":{...}}

!! 字段序不是官方文档 !!
每个指令的字段序由「真实元件数据 + easyeda2kicad 参照实现」校准得出 (见 tests)，
关键字段的出处都在注释里标了。解析器永远保留 raw 原文，绝不丢信息。
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ParseError
from . import units
from .model import (
    FOOTPRINT_LAYERS,
    PIN_ELECTRICAL_TYPES,
    Component,
    Footprint,
    Model3D,
    Pad,
    Pin,
    Primitive,
    Symbol,
)


# --------------------------------------------------------------------------- #
# 低层
# --------------------------------------------------------------------------- #
def split_shape(line: str) -> Primitive:
    """把一行 shape 原文切成 Primitive。sub 用 '^^' 切，fields 用 '~' 切主段。"""
    line = line.strip()
    parts = line.split("^^")
    main = parts[0].split("~")
    return Primitive(
        kind=main[0] if main else "",
        fields=main,
        sub=parts[1:],
        raw=line,
    )


def _f(s: Any, default: float = 0.0) -> float:
    """容错浮点。空串很常见，直接当默认值。"""
    if s is None:
        return default
    s = str(s).strip()
    if s == "":
        return default
    try:
        return float(s)
    except ValueError:
        m = re.match(r"[-+]?[0-9.]+", s)
        return float(m.group()) if m else default


def _points(blob: str) -> list[tuple[float, float]]:
    """解析 'x1 y1 x2 y2 ...' 坐标串 (画布单位)。"""
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+", blob or "")
    out: list[tuple[float, float]] = []
    for i in range(0, len(nums) - 1, 2):
        out.append((float(nums[i]), float(nums[i + 1])))
    return out


def layer_name(code: Any) -> str:
    """EasyEDA 层号 → 语义名。未知层原样返回 LAYER_<n>。"""
    key = str(code).strip()
    return FOOTPRINT_LAYERS.get(key, f"LAYER_{key}")


# --------------------------------------------------------------------------- #
# 坐标变换
# --------------------------------------------------------------------------- #
class _Transform:
    """画布 → mm 的坐标变换。

    符号: 减 BBox 中心 + Y 翻转; 封装: 减画布原点, 不翻转。
    """

    def __init__(self, ox: float, oy: float, *, flip_y: bool) -> None:
        self.ox = ox
        self.oy = oy
        self.flip_y = flip_y

    def x(self, v: float) -> float:
        return (v - self.ox) * units.FOOTPRINT_UNIT_TO_MM

    def y(self, v: float) -> float:
        mm = (v - self.oy) * units.FOOTPRINT_UNIT_TO_MM
        return -mm if self.flip_y else mm

    def pt(self, p: tuple[float, float]) -> tuple[float, float]:
        return (self.x(p[0]), self.y(p[1]))


def _symbol_origin(data: dict[str, Any]) -> tuple[float, float]:
    """符号画布原点 = BBox 中心; 无 BBox 时退回 head.x/y。"""
    bbox = data.get("BBox") or {}
    bw, bh = _f(bbox.get("width")), _f(bbox.get("height"))
    if bw or bh:
        return (_f(bbox.get("x")) + bw / 2.0, _f(bbox.get("y")) + bh / 2.0)
    head = data.get("head", {}) or {}
    return (_f(head.get("x")), _f(head.get("y")))


def _footprint_origin(ds: dict[str, Any]) -> tuple[float, float]:
    """封装画布原点: canvas.split('~')[16]/[17] 权威, 退回 head.x/y。"""
    canvas = str(ds.get("canvas", "")).split("~")
    if len(canvas) > 17:
        return (_f(canvas[16]), _f(canvas[17]))
    head = ds.get("head", {}) or {}
    return (_f(head.get("x")), _f(head.get("y")))


# --------------------------------------------------------------------------- #
# 符号指令
# --------------------------------------------------------------------------- #
def parse_symbol_pin(prim: Primitive, tf: _Transform) -> Pin:
    """引脚 'P'。

    主段: P~<display>~<elecType>~<number>~<x>~<y>~<rotation>~<gId>~<locked>
    子段: [0]=起点; [1]=引脚线 'path~#color'; [2]=名文本; [3]=号文本
          文本子段: <show>~<x>~<y>~<rot>~<text>~<align>~<font>~<size>~<color>
    """
    f = prim.fields
    pin = Pin()
    if len(f) >= 7:
        pin.visible = (f[1] or "").strip().lower() != "hide"
        pin.electrical_type = PIN_ELECTRICAL_TYPES.get((f[2] or "").strip(), "unspecified")
        pin.x_mm = tf.x(_f(f[4]))
        pin.y_mm = tf.y(_f(f[5]))
        pin.rotation_deg = _f(f[6])
        pin.orientation_deg = (pin.rotation_deg + 180.0) % 360.0
    # 名在 sub[2] (即 ^^ 分段 [3]) 的第 5 个字段
    if len(prim.sub) >= 3:
        seg = prim.sub[2].split("~")
        if len(seg) >= 5:
            pin.name = seg[4]
    # 号在 sub[3] (即 ^^ 分段 [4]) 的第 5 个字段
    if len(prim.sub) >= 4:
        seg = prim.sub[3].split("~")
        if len(seg) >= 5:
            pin.number = seg[4]
    # 引脚长度: 从引脚线 'M x y h -10' 的 h/v 值取
    if len(prim.sub) >= 2:
        path = prim.sub[1].split("~")[0]
        m = re.search(r"[hv]\s*(-?[0-9.]+)", path)
        if m:
            pin.length_mm = abs(m.group(1) and float(m.group(1)) or 0.0) * units.FOOTPRINT_UNIT_TO_MM
    prim.geom = {
        "x_mm": pin.x_mm,
        "y_mm": pin.y_mm,
        "length_mm": pin.length_mm,
        "number": pin.number,
        "name": pin.name,
    }
    return pin


def parse_symbol_primitive(prim: Primitive, tf: _Transform) -> Primitive:
    """给常见符号图元填 geom (mm)。字段序经真实数据校准。"""
    f = prim.fields
    k = prim.kind
    if k == "R":  # R~x~y~~(rx~ry)~w~h~stroke~sw~style~fill~id~locked
        if len(f) >= 7:
            x, y = tf.x(_f(f[1])), tf.y(_f(f[2]))
            w, h = _f(f[5]) * units.FOOTPRINT_UNIT_TO_MM, _f(f[6]) * units.FOOTPRINT_UNIT_TO_MM
            prim.geom = {
                "x_mm": x,
                "y_mm": y,
                "x2_mm": x + w,
                # Y 已翻转 → 矩形向负方向延伸
                "y2_mm": y - h,
                "w_mm": w,
                "h_mm": h,
                "rotation": _f(f[3]),
            }
    elif k == "C":  # C~x~y~radius~...
        if len(f) >= 4:
            prim.geom = {
                "x_mm": tf.x(_f(f[1])),
                "y_mm": tf.y(_f(f[2])),
                "r_mm": _f(f[3]) * units.FOOTPRINT_UNIT_TO_MM,
            }
    elif k == "E":  # E~x~y~rx~ry~...
        if len(f) >= 5:
            prim.geom = {
                "x_mm": tf.x(_f(f[1])),
                "y_mm": tf.y(_f(f[2])),
                "rx_mm": _f(f[3]) * units.FOOTPRINT_UNIT_TO_MM,
                "ry_mm": _f(f[4]) * units.FOOTPRINT_UNIT_TO_MM,
            }
    elif k in ("PL", "PG", "PT"):  # PL~<points>~...
        if len(f) >= 2:
            pts = [tf.pt(p) for p in _points(f[1])]
            prim.geom = {"points_mm": [v for p in pts for v in p], "n": float(len(pts))}
    elif k == "T":  # T~<align>~x~y~rotation~color~font~size~...~text(index 12)
        if len(f) >= 13:
            prim.geom = {
                "x_mm": tf.x(_f(f[2])),
                "y_mm": tf.y(_f(f[3])),
                "rotation": _f(f[4]),
                "text": f[12],
                "font_size": f[7],
            }
    return prim


# --------------------------------------------------------------------------- #
# 封装指令
# --------------------------------------------------------------------------- #
def parse_footprint_pad(prim: Primitive, tf: _Transform) -> Pad:
    """焊盘 'PAD'。字段序 (easyeda2kicad EeFootprintPad):

    fields 包含指令本身: 0 PAD, 1 shape, 2 cx, 3 cy, 4 w, 5 h,
    6 layer_id, 7 net, 8 number, 9 hole_radius, 10 points,
    11 rotation, 12 id, 13 hole_length, ...。net 不是引脚功能名。
    """
    f = prim.fields
    pad = Pad()
    if len(f) < 8:
        return pad
    pad.shape = (f[1] or "RECT").upper()
    pad.x_mm = tf.x(_f(f[2]))
    pad.y_mm = tf.y(_f(f[3]))
    pad.w_mm = _f(f[4]) * units.FOOTPRINT_UNIT_TO_MM
    pad.h_mm = _f(f[5]) * units.FOOTPRINT_UNIT_TO_MM
    pad.layer_ids = [str(f[6]).strip()] if f[6] else []
    pad.layers = [layer_name(x) for x in pad.layer_ids]
    pad.number = (f[8] if len(f) > 8 else "").strip()
    # f[9] 是 EasyEDA 的 hole_radius (半径!)，Capture/Allegro padstack 的 drill 要直径。
    pad.hole_mm = 2.0 * _f(f[9]) * units.FOOTPRINT_UNIT_TO_MM if len(f) > 9 else 0.0
    if len(f) > 10 and f[10].strip():
        pad.polygon_mm = [tf.pt(p) for p in _points(f[10])]
    pad.rotation_deg = _f(f[11]) if len(f) > 11 else 0.0
    pad.is_smd = pad.hole_mm <= 0.0
    prim.geom = {
        "x_mm": pad.x_mm,
        "y_mm": pad.y_mm,
        "w_mm": pad.w_mm,
        "h_mm": pad.h_mm,
        "number": pad.number,
    }
    return pad


def parse_footprint_primitive(prim: Primitive, tf: _Transform) -> Primitive:
    f = prim.fields
    k = prim.kind
    if k == "TRACK":  # TRACK~stroke_width~layer_id~net~~points~id~locked
        #   字段序来自 easyeda2kicad EeFootprintTrack: (stroke_width, layer_id, net, points, ...)
        if len(f) >= 5:
            pts = [tf.pt(p) for p in _points(f[4])]
            prim.geom = {
                "layer": layer_name(f[2]),
                "width_mm": _f(f[1]) * units.FOOTPRINT_UNIT_TO_MM,
                "points_mm": [v for p in pts for v in p],
            }
    elif k == "CIRCLE":  # CIRCLE~cx~cy~radius~stroke_width~layer_id~...
        if len(f) >= 6:
            prim.geom = {
                "x_mm": tf.x(_f(f[1])),
                "y_mm": tf.y(_f(f[2])),
                "r_mm": _f(f[3]) * units.FOOTPRINT_UNIT_TO_MM,
                "stroke_mm": _f(f[4]) * units.FOOTPRINT_UNIT_TO_MM,
                "layer": layer_name(f[5]),
            }
    elif k == "ARC":  # ARC~stroke_width~layer_id~net~path~helper~...
        if len(f) >= 4:
            prim.geom = {
                "layer": layer_name(f[2]),
                "width_mm": _f(f[1]) * units.FOOTPRINT_UNIT_TO_MM,
                "path": f[4] if len(f) > 4 else "",
            }
    elif k == "HOLE":  # HOLE~cx~cy~radius~...
        if len(f) >= 4:
            prim.geom = {
                "x_mm": tf.x(_f(f[1])),
                "y_mm": tf.y(_f(f[2])),
                "hole_mm": _f(f[3]) * units.FOOTPRINT_UNIT_TO_MM,
            }
    elif k == "SOLIDREGION":  # SOLIDREGION~layer_id~net~path~region_type~id~~...
        if len(f) >= 4:
            path = f[3]
            # This converter currently supports only absolute M/L/Z outlines.
            # Reject other commands downstream instead of treating curve controls as vertices.
            commands = re.findall(r"[A-Za-z]", path)
            supported = all(command.upper() in {"M", "L", "Z"} for command in commands)
            pts = [tf.pt(p) for p in _points(path)] if supported else []
            prim.geom = {
                "layer": layer_name(f[1]),
                "path": path,
                "path_supported": supported,
                "points_mm": [v for p in pts for v in p],
                "region_type": f[4] if len(f) > 4 else "solid",
            }
    elif k == "SVGNODE":
        prim.geom = _parse_svgnode(prim.raw)
    return prim


def _parse_svgnode(raw: str) -> dict[str, Any]:
    """SVGNODE 里携带 3D 模型的 uuid / 原点 / 旋转 / 尺寸 (画布单位)。"""
    try:
        j = json.loads(raw.split("~", 1)[1])
    except (IndexError, json.JSONDecodeError):
        return {}
    attrs = j.get("attrs", {})
    out: dict[str, Any] = {}
    if "uuid" in attrs:
        out["uuid"] = attrs["uuid"]
    origin = attrs.get("c_origin", "")
    if origin:
        xy = origin.split(",")
        out["c_origin_units"] = [_f(xy[0]), _f(xy[1] if len(xy) > 1 else 0)]
    if "z" in attrs:
        out["z_units"] = _f(attrs["z"])
    rot = attrs.get("c_rotation", "")
    if rot:
        out["rotation_deg"] = [_f(x) for x in rot.split(",")]
    for key in ("c_width", "c_height"):
        if key in attrs:
            out[key + "_units"] = _f(attrs[key])
    return out


# --------------------------------------------------------------------------- #
# 顶层: JSON → Component
# --------------------------------------------------------------------------- #
def parse_component(cid: str, payload: dict[str, Any]) -> Component:
    """把一个 /components 响应 (result 字段) 解析成 Component。"""
    if "dataStr" not in payload and "packageDetail" not in payload:
        raise ParseError("响应缺少 dataStr/packageDetail，无法解析 (可能上游变更)")

    comp = Component(cid=cid, uuid=payload.get("uuid", ""), title=payload.get("title", ""))
    comp.raw = payload
    comp.symbol = parse_symbol(cid, payload)
    comp.footprint = parse_footprint(payload)
    comp.model3d = parse_model3d(payload, comp.footprint)
    return comp


def parse_symbol(cid: str, payload: dict[str, Any]) -> Symbol | None:
    data = payload.get("dataStr")
    if not data:
        return None
    sym = Symbol(cid=cid, name=(payload.get("title") or "").strip())
    head = data.get("head", {}) or {}
    c_para = head.get("c_para", {}) or {}
    sym.prefix = c_para.get("pre", "")
    sym.manufacturer = c_para.get("Manufacturer", "")
    sym.mpn = c_para.get("Manufacturer Part", "")
    sym.description = c_para.get("Description", "") or payload.get("description", "")
    sym.datasheet = c_para.get("Datasheet", "")
    bbox = data.get("BBox") or {}
    if bbox:
        sym.width_mm = _f(bbox.get("width")) * units.FOOTPRINT_UNIT_TO_MM
        sym.height_mm = _f(bbox.get("height")) * units.FOOTPRINT_UNIT_TO_MM
    sym.origin = _symbol_origin(data)
    tf = _Transform(sym.origin[0], sym.origin[1], flip_y=True)
    for k, v in c_para.items():
        if isinstance(v, (str, int, float)):
            sym.extra_props.setdefault(k, str(v))

    for line in data.get("shape", []) or []:
        prim = split_shape(line)
        if prim.kind == "P":
            sym.pins.append(parse_symbol_pin(prim, tf))
        else:
            parse_symbol_primitive(prim, tf)
        sym.primitives.append(prim)
    return sym


def parse_footprint(payload: dict[str, Any]) -> Footprint | None:
    pkg = payload.get("packageDetail")
    if not pkg:
        return None
    data = pkg.get("dataStr", {}) or {}
    head = data.get("head", {}) or {}
    c_para = head.get("c_para", {}) or {}
    fp = Footprint(name=c_para.get("package") or (payload.get("title") or "").strip())
    fp.height_mm = _f(head.get("height")) * units.FOOTPRINT_UNIT_TO_MM
    fp.model_3d_name = c_para.get("3DModel", "")

    ox, oy = _footprint_origin(data)
    tf = _Transform(ox, oy, flip_y=False)
    fp.origin = (ox, oy)

    for line in data.get("shape", []) or []:
        prim = split_shape(line)
        if prim.kind == "PAD":
            pad = parse_footprint_pad(prim, tf)
            if pad.number or pad.layers:
                fp.pads.append(pad)
            prim.geom.update({"x_mm": pad.x_mm, "y_mm": pad.y_mm})
        else:
            parse_footprint_primitive(prim, tf)
        if prim.kind == "TRACK" and prim.geom.get("points_mm"):
            flat = prim.geom["points_mm"]
            pts = [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]
            fp.lines.append((str(prim.geom.get("layer", "")), pts))
        if prim.kind == "CIRCLE" and "r_mm" in prim.geom:
            fp.circles.append(
                (
                    str(prim.geom.get("layer", "")),
                    prim.geom["x_mm"],
                    prim.geom["y_mm"],
                    prim.geom["r_mm"],
                )
            )
        if prim.kind == "SOLIDREGION":
            fp.solid_regions.append(prim)
        fp.primitives.append(prim)

    fp.is_smd = all(p.is_smd for p in fp.pads) if fp.pads else True
    from ..footprint.padstack import merge_padstacks

    fp.padstacks = merge_padstacks(fp.pads)
    return fp


def parse_model3d(payload: dict[str, Any], footprint: Footprint | None) -> Model3D | None:
    """从封装的 SVGNODE 里抽 3D 模型元数据。

    c_origin 是绝对画布坐标; 这里换成相对封装原点的 mm (即模型应以何处为基准摆放)。
    """
    if not footprint:
        return None
    ox, oy = footprint.origin
    for prim in footprint.primitives:
        if prim.kind == "SVGNODE" and prim.geom.get("uuid"):
            g = prim.geom
            org = g.get("c_origin_units", [ox, oy])
            rot = g.get("rotation_deg", [0.0, 0.0, 0.0])
            return Model3D(
                uuid=str(g["uuid"]),
                origin_mm=(
                    (org[0] - ox) * units.FOOTPRINT_UNIT_TO_MM,
                    (org[1] - oy) * units.FOOTPRINT_UNIT_TO_MM,
                ),
                z_mm=_f(g.get("z_units", 0.0)) * units.FOOTPRINT_UNIT_TO_MM,
                rotation_deg=(rot[0], rot[1], rot[2]) if len(rot) == 3 else (0.0, 0.0, 0.0),
                width_mm=_f(g.get("c_width_units", 0.0)) * units.FOOTPRINT_UNIT_TO_MM,
                height_mm=_f(g.get("c_height_units", 0.0)) * units.FOOTPRINT_UNIT_TO_MM,
            )
    return None


def doc_type_of(payload: dict[str, Any]) -> int | None:
    dt = (payload.get("dataStr") or {}).get("head", {}).get("docType")
    if dt is None:
        return None
    try:
        return int(dt)
    except (ValueError, TypeError):
        return None

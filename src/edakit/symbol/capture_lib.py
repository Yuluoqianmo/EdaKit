"""生成 OrCAD Capture **真实方言**的库 XML（`<Lib>` / `<Package>` / `<LibPart>`）。

== 为什么有这份文件 ==
之前 `olb_xml.py` 里那套 `<CaptureLibrary><Part><Pins><Pin>` 是**猜的**。2026-10-19
用户从 Capture 17.2 里真实导出（`XMATIC_OLB2XML`）了一份参考库，真方言长这样：

    <Lib xsi:noNamespaceSchemaLocation="olb.xsd">
      <Defn name="D:/cadence/ref.olb"/>
      <DefaultValues> …24 个字体 + 页面设置 + 字段映射… </DefaultValues>
      <Package>
        <Defn name="ref" pcbFootprint="" refdesPrefix="U" isHomogeneous="1" …/>
        <LibPart>
          <Defn CellName="ref"/>
          <NormalView>
            <Defn suffix=".Normal"/>
            <SymbolDisplayProp>… Part Reference …</SymbolDisplayProp>
            <SymbolDisplayProp>… Value …</SymbolDisplayProp>
            <SymbolColor><Defn val="48"/></SymbolColor>
            <SymbolBBox><Defn x1="0" x2="50" y1="0" y2="50"/></SymbolBBox>
            <IsPinNumbersVisible><Defn val="1"/></IsPinNumbersVisible>
            <IsPinNamesRotated><Defn val="1"/></IsPinNamesRotated>
            <IsPinNamesVisible><Defn val="1"/></IsPinNamesVisible>
            <ContentsLibName><Defn name=""/></ContentsLibName>
            <ContentsViewName><Defn name=""/></ContentsViewName>
            <ContentsViewType><Defn type="0"/></ContentsViewType>
            <PartValue><Defn name=""/></PartValue>
            <Reference><Defn name="U"/></Reference>
            <Rect><Defn fillStyle="1" hatchStyle="-1" lineStyle="0" lineWidth="0"
                        x1="0" x2="50" y1="0" y2="50"/></Rect>
            <SymbolPinScalar>
              <Defn hotptX="80" hotptY="30" name="GND" position="1"
                    startX="50" startY="30" type="4" visible="1"/>
              <IsLong><Defn val="0"/></IsLong>
              … 另外 8 个 Is* 开关 …
            </SymbolPinScalar>
          </NormalView>
          <PhysicalPart>
            <Defn/>
            <PinNumber><Defn number="1" position="0"/></PinNumber>
            <PinNumber><Defn number="2" position="1"/></PinNumber>
          </PhysicalPart>
        </LibPart>
      </Package>
    </Lib>

== 单位 ==
坐标是整数，单位 **10 mil = 0.254 mm**（参考库里 50×50 的矩形 = 500×500 mil，
引脚长 30 单位 = 300 mil，都合常理）。所以 `unit = mm / 0.254`。

== 引脚几何 ==
  startX/startY = 引脚贴着元件本体的那一端
  hotptX/hotptY = 引脚另一端，也就是连接点（导线接这里）
  长度 = 两点距离。我们模型里 `pin.x_mm/y_mm` 就是连接点，本体端 =
  连接点 + length × (cosθ, sinθ)，θ = `pin.orientation_deg`。

== 还没摸清、先用保守默认值的 ==
  * `type` 使用下方已校准的 PortType 映射，Power=7。
  * `Text` 等其余图元：结构没采到样，默认不生成（`include_text=False`）。
    元件名靠 PartValue 显示，位号靠 Reference 显示，不影响辨识。
"""

from __future__ import annotations

import re
import time
import copy
import math
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from ..easyeda.model import Symbol

# 1 个 Capture 符号单位 = 10 mil = 0.254 mm
CAPTURE_UNIT_MM = 0.254

# 引脚电气类型 → Capture 的 OrCAD PortType 枚举。
# 依据（2026-10-19 调研，两处独立来源一致）：
#   * OpenOrCadParser `src/Enums/PortType.hpp`（解析真实 .OLB 二进制）：
#       Input=0 Bidirectional=1 Output=2 OpenCollector=3
#       Passive=4 ThreeState=5 OpenEmitter=6 Power=7
#   * 用户机器上 17.2 真实导出的库 `sample/test.xml`（orlib2ki）：
#       VCC/GND 引脚 type=7、TCK/TDI/TDO type=4 —— 与上表吻合。
# 注意：OLB2XML 回读出的 type 只是**原样回显我们写进去的数字**，不能用来反推语义，
# 之前按回读结果定的 output=1 / bidirectional=2 / power=5 是错的。
PIN_TYPE_CODE = {
    "input": 0,
    "bidirectional": 1,
    "output": 2,
    "open_collector": 3,
    "passive": 4,
    "three_state": 5,
    "tri_state": 5,
    "tristate": 5,
    "open_emitter": 6,
    "open": 6,
    "power": 7,
    # Capture 没有 unspecified；映射成 Passive（与 arthur / kicad2orcad 一致）
    "unspecified": 4,
}

_DEFAULTS_RE = re.compile(r"<DefaultValues\b.*?</DefaultValues>", re.DOTALL)

# 参考库里每个 SymbolPinScalar 后面跟着的 9 个布尔开关（顺序也照抄）
_PIN_BOOLS = (
    "IsLong",
    "IsClock",
    "IsDot",
    "IsLeftPointing",
    "IsRightPointing",
    "IsNetStyle",
    "IsNoConnect",
    "IsGlobal",
    "IsNumberVisible",
)


def u(mm: float) -> int:
    """mm → Capture 符号单位（整数）。"""
    return int(round(mm / CAPTURE_UNIT_MM))


def normalize_capture_symbol(source: Symbol) -> Symbol:
    """Prepare a copy for Capture: unique signal names and 100 mil hotpoints.

    Source electrical types and physical numbers remain authoritative. Do not
    infer Power from a name such as VDD. Labels consume the same prepared copy.
    """
    sym = copy.deepcopy(source)
    counts = Counter(p.name.casefold() for p in sym.pins)
    reserved = {p.name.casefold() for p in sym.pins}
    serials = Counter()
    def order(pin):
        return (0, int(pin.number)) if pin.number.isdigit() else (1, pin.number)
    for pin in sorted(sym.pins, key=order):
        key = pin.name.casefold()
        if counts[key] <= 1 or pin.electrical_type.lower() == 'power':
            continue
        while True:
            serials[key] += 1
            name = f'{pin.name}{serials[key]}'
            if name.casefold() not in reserved:
                break
        pin.name = name
        reserved.add(name.casefold())

    def snap(value):
        return 10 * math.floor(value / 10 + 0.5)

    groups = {}
    for pin in sym.pins:
        angle = pin.orientation_deg % 360
        if angle not in (0, 90, 180, 270):
            raise ValueError('Capture 格点对齐暂不支持非正交引脚。')
        horizontal = angle in (0, 180)
        fixed = u(pin.x_mm if horizontal else pin.y_mm)
        groups.setdefault((angle, fixed), []).append(pin)
    for (angle, fixed), pins in groups.items():
        horizontal = angle in (0, 180)
        values = sorted({u(p.y_mm if horizontal else p.x_mm) for p in pins})
        mapped = []
        for value in values:
            mapped.append(max(snap(value), mapped[-1] + 10) if mapped else snap(value))
        shift = snap(sum(a-b for a, b in zip(values, mapped)) / len(values))
        mapping = {a: b + shift for a, b in zip(values, mapped)}
        for pin in pins:
            old_fixed = pin.x_mm if horizontal else pin.y_mm
            direction = 1 if angle in (0, 90) else -1
            body = old_fixed + direction * pin.length_mm
            # Move the connection end outward so snapping cannot shorten the
            # visible lead or move it into the body.
            # Keep at least 100 mil of visible Line lead, including on tiny
            # source symbols. Snap the connection end outward from the body.
            limit = (body - direction * 2.54) / CAPTURE_UNIT_MM
            new_fixed = (10 * (math.floor(min(fixed, limit) / 10) if direction == 1
                               else math.ceil(max(fixed, limit) / 10))) * CAPTURE_UNIT_MM
            new_length = direction * (body - new_fixed)
            if new_length < -1e-8:
                raise ValueError(f'引脚 {pin.number} 长度不足以对齐 Capture 格点。')
            variable = mapping[u(pin.y_mm if horizontal else pin.x_mm)] * CAPTURE_UNIT_MM
            pin.x_mm, pin.y_mm = ((new_fixed, variable) if horizontal else (variable, new_fixed))
            pin.length_mm = max(0.0, new_length)
    return sym


def default_values_block() -> str:
    """内置的 DefaultValues 块（取自用户机器上 Capture 17.2 真实导出的参考库）。"""
    path = Path(__file__).parent / "templates" / "capture172_defaults.xml"
    return path.read_text(encoding="utf-8").strip()


def extract_default_values(ref_xml: str) -> str | None:
    """从一份参考库 XML 里抠出 `<DefaultValues>…</DefaultValues>` 原文。"""
    m = _DEFAULTS_RE.search(ref_xml)
    return m.group(0).strip() if m else None


def is_capture_lib_dialect(xml_text: str) -> bool:
    """判断这是不是 Capture 的 `<Lib>` 方言（而不是我们早先猜的 `<CaptureLibrary>`）。"""
    head = xml_text[:2000]
    return "<Lib" in head and "<Package" in xml_text


# --------------------------------------------------------------------------- #
# 顶/底边（竖直）引脚的横向疏排 —— **兜底方案，默认不启用**
# --------------------------------------------------------------------------- #
# 2026-10-19 调研结论：名字是否竖排由 `IsPinNamesRotated` 控制，而之前名字横排、
# 名称/编号位置也不对的真正原因是 `IsLong=0`（引脚被 Capture 当「Short」只画一半，
# 见 OpenOrCadParser）。改成 IsLong=1 + Y 翻转后按 EasyEDA 原始布局输出即可，
# 不再需要按名字宽度疏排（疏排会把本体拉宽、引脚挪位，反而失真）。
# 这个函数保留：万一 17.2 上竖排名仍不旋转，可临时启用它做几何兜底。
PIN_NAME_CHAR_MM = 1.2
PIN_NAME_GAP_MM = 0.8      # 相邻两个名字之间至少留的空隙
PIN_NAME_EDGE_MM = 2.54    # 疏排后最外侧引脚离本体边角至少留的距离


def pin_names_hidden(sym: Symbol) -> bool:
    """引脚名==编号（电阻、排针、连接器）时名字是冗余的，整体隐藏。"""
    return bool(sym.pins) and all(
        (p.name or "").strip() in ("", (p.number or "").strip()) for p in sym.pins
    )


def _name_width_mm(name: str) -> float:
    return len((name or "").strip()) * PIN_NAME_CHAR_MM


def _body_rect_index(sym: Symbol) -> int | None:
    """本体矩形 = 面积最大的 R 图元。"""
    best: int | None = None
    best_area = -1.0
    for i, prim in enumerate(sym.primitives):
        if prim.kind != "R":
            continue
        g = prim.geom
        area = abs(g.get("x2_mm", 0.0) - g.get("x_mm", 0.0)) * abs(
            g.get("y2_mm", 0.0) - g.get("y_mm", 0.0)
        )
        if area > best_area:
            best, best_area = i, area
    return best


def layout_vertical_pins(
    sym: Symbol, *, names_visible: bool = True
) -> tuple[dict[int, float], dict[int, dict]]:
    """给顶/底边的引脚按名字宽度做横向疏排，需要时加宽本体。

    返回 ``(pin_x, rect_geom)``：
      * ``pin_x`` —— {引脚下标: 新的 x_mm}。除被疏排的竖排引脚外，左右两侧的
        水平引脚因本体加宽也会跟着平移（否则它们的本体端会悬在框内）。
      * ``rect_geom`` —— {图元下标: 新的 geom}，只含被加宽的本体矩形。

    ``names_visible=False``（名字==编号，已整体隐藏）或没有成组的竖排引脚时，
    返回空映射 —— 电阻/排针这类元件输出保持原样。
    """
    import math

    if not names_visible or not sym.pins:
        return {}, {}
    rect_i = _body_rect_index(sym)
    if rect_i is None:
        return {}, {}
    rg = sym.primitives[rect_i].geom
    bx1, bx2 = sorted((float(rg["x_mm"]), float(rg["x2_mm"])))
    by1, by2 = sorted((float(rg["y_mm"]), float(rg["y2_mm"])))

    # 同一条边 = 同方向、同 y。顶边 12 根脚全在 y=50.8，自成一组。
    groups: dict[tuple[float, float], list[int]] = {}
    for i, p in enumerate(sym.pins):
        ang = p.orientation_deg % 360.0
        if abs(ang - 90.0) < 1e-6 or abs(ang - 270.0) < 1e-6:
            groups.setdefault((round(ang), round(p.y_mm, 2)), []).append(i)

    pin_x: dict[int, float] = {}
    spread_xs: list[float] = []
    spread = False
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        idxs.sort(key=lambda i: sym.pins[i].x_mm)
        xs = [sym.pins[i].x_mm for i in idxs]
        new = [xs[0]]
        for j in range(1, len(idxs)):
            need = (
                _name_width_mm(sym.pins[idxs[j - 1]].name)
                + _name_width_mm(sym.pins[idxs[j]].name)
            ) / 2 + PIN_NAME_GAP_MM
            new.append(max(xs[j], new[-1] + need))
        if all(abs(a - b) < 1e-6 for a, b in zip(xs, new)):
            continue  # 本来就放得下
        # 整组以原中点为轴左右摊开，尽量不破坏原来在符号里的位置
        shift = (xs[0] + xs[-1]) / 2 - (new[0] + new[-1]) / 2
        for i, x in zip(idxs, new):
            pin_x[i] = x + shift
            spread_xs.append(x + shift)
        spread = True

    if not spread:
        return {}, {}

    # 本体要盖住疏排后的引脚（左右各留 PIN_NAME_EDGE_MM），只加宽不缩窄
    nx1 = min([bx1] + [x - PIN_NAME_EDGE_MM for x in spread_xs])
    nx2 = max([bx2] + [x + PIN_NAME_EDGE_MM for x in spread_xs])
    dxl, dxr = nx1 - bx1, nx2 - bx2

    # 水平引脚跟着自己那侧的边平移
    for i, p in enumerate(sym.pins):
        if i in pin_x:
            continue
        ang = p.orientation_deg % 360.0
        if abs(ang) < 1e-6 or abs(ang - 180.0) < 1e-6:
            start_x = p.x_mm + (p.length_mm or 0.0) * math.cos(math.radians(ang))
            if abs(dxl) > 1e-6 and abs(start_x - bx1) < 0.01:
                pin_x[i] = p.x_mm + dxl
            elif abs(dxr) > 1e-6 and abs(start_x - bx2) < 0.01:
                pin_x[i] = p.x_mm + dxr

    new_geom = dict(rg)
    xa, xb = (nx1, nx2) if float(rg["x_mm"]) <= float(rg["x2_mm"]) else (nx2, nx1)
    new_geom["x_mm"], new_geom["x2_mm"] = xa, xb
    if "w_mm" in new_geom:
        new_geom["w_mm"] = nx2 - nx1
    return pin_x, {rect_i: new_geom}


def _pin_xml(
    index: int,
    pin,
    *,
    y_sign: int,
    x_mm: float | None = None,
    number_visible: bool = True,
    force_passive: bool = False,
) -> str:
    import math

    px = pin.x_mm if x_mm is None else x_mm
    hot_x = u(px)
    hot_y = u(pin.y_mm) * y_sign

    th = math.radians(pin.orientation_deg)
    body_x = u(px + pin.length_mm * math.cos(th))
    body_y = u(pin.y_mm + pin.length_mm * math.sin(th)) * y_sign

    code = 4 if force_passive else PIN_TYPE_CODE.get((pin.electrical_type or "passive").lower(), 4)
    name = escape(pin.name or "", {'"': "&quot;"})
    fields = [
        f'hotptX="{hot_x}"',
        f'hotptY="{hot_y}"',
        f'name="{name}"',
        f'position="{index}"',
        f'startX="{body_x}"',
        f'startY="{body_y}"',
        f'type="{code}"',
        f'visible="{1 if pin.visible else 0}"',
    ]
    out = [f"        <SymbolPinScalar>", f"          <Defn {' '.join(fields)}/>"]
    # Shape is a library policy, not inferred from the source lead length.
    is_long = 1
    for b in _PIN_BOOLS:
        out.append(f'          <{b}><Defn val="0"/></{b}>')
    out[2] = f'          <IsLong><Defn val="{is_long}"/></IsLong>'
    # Use Capture's native number display so the visibility controls work.
    out[-1] = (
        '          <IsNumberVisible><Defn val="%d"/></IsNumberVisible>'
        % (1 if number_visible else 0)
    )
    out.append("        </SymbolPinScalar>")
    return "\n".join(out)


def _rect_xml(g, *, y_sign: int = -1) -> str:
    x1, x2 = sorted((u(g["x_mm"]), u(g["x2_mm"])))
    y1, y2 = sorted((u(g["y_mm"]) * y_sign, u(g["y2_mm"]) * y_sign))
    return (
        "        <Rect>\n"
        f"          <Defn fillStyle=\"1\" hatchStyle=\"-1\" lineStyle=\"0\" "
        f'lineWidth="0" x1="{x1}" x2="{x2}" y1="{y1}" y2="{y2}"/>\n'
        "        </Rect>"
    )


def _line_xml(x1, y1, x2, y2):
    return ('        <Line>\n'
            f'          <Defn lineStyle="0" lineWidth="0" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"/>\n'
            '        </Line>')


def _polyline_xml(g, *, y_sign=-1, closed=False):
    values = g.get("points_mm", [])
    points = [(u(values[i]), u(values[i + 1]) * y_sign) for i in range(0, len(values) - 1, 2)]
    if closed and len(points) > 2 and points[0] != points[-1]:
        points.append(points[0])
    return [_line_xml(*a, *b) for a, b in zip(points, points[1:]) if a != b], points


def _ellipse_xml(g, *, y_sign=-1):
    rx, ry = g.get("rx_mm", g.get("r_mm", 0)), g.get("ry_mm", g.get("r_mm", 0))
    x1, x2 = sorted((u(g["x_mm"] - rx), u(g["x_mm"] + rx)))
    y1, y2 = sorted((u(g["y_mm"] - ry) * y_sign, u(g["y_mm"] + ry) * y_sign))
    return ('        <Ellipse>\n'
            f'          <Defn fillStyle="1" hatchStyle="-1" lineStyle="0" lineWidth="0" x1="{x1}" x2="{x2}" y1="{y1}" y2="{y2}"/>\n'
            '        </Ellipse>'), [(x1, y1), (x2, y2)]


# --------------------------------------------------------------------------- #
# CommentText is reserved for source graphics and diagnostic text probes.
PIN_LABEL_CHAR_W = 5


def _comment_text_xml(
    text: str,
    x: int,
    y: int,
    *,
    x1: int,
    x2: int,
    y1: int,
    y2: int,
    escapement: int = 0,
    orientation: int = 0,
    justification: int = 0,
    with_font: bool = True,
    height: int = -9,
    width: int = 4,
) -> str:
    """一个 `CommentText` 图元（17.2 真方言，<Text> 不存在）。

    ``escapement``/``orientation`` 是 LOGFONT 的字段，单位 1/10 度；
    顶/底边引脚名用 900（=90°）由 Capture 竖着画。
    """
    txt = escape(str(text), {'"': "&quot;"})
    out = [
        "        <CommentText>",
        f'          <Defn locX="{x}" locY="{y}" name="{txt}" '
        f'textJustification="{justification}" x1="{x1}" x2="{x2}" y1="{y1}" y2="{y2}"/>',
    ]
    if with_font:
        out.append(
            '          <TextFont><Defn charset="0" escapement="%d" height="%d" italic="0" '
            'name="Arial" orientation="%d" weight="400" width="%d"/></TextFont>'
            % (escapement, height, orientation, width)
        )
    out.append("        </CommentText>")
    return "\n".join(out)


def _text_xml(g, *, y_sign: int = -1) -> str:
    """模型里的文字图元 → `CommentText`。

    文本框按参考实现（arthur）的估法：每字符 5 单位宽、字高 9 单位。
    """
    x = u(g["x_mm"])
    y = u(g["y_mm"]) * y_sign
    width = max(len(str(g.get("text", ""))) * PIN_LABEL_CHAR_W, 10)
    return _comment_text_xml(
        str(g.get("text", "")), x, y,
        x1=x, x2=x + width, y1=y - 8, y2=y + 2,
    )


def _signed_body_edges(sym: Symbol, *, y_sign: int) -> tuple[int, int, int, int] | None:
    """以输出坐标（Y 已按 y_sign 翻转）返回本体矩形的 (x1, x2, y_top, y_bottom)。"""
    rect_i = _body_rect_index(sym)
    if rect_i is None:
        return None
    g = sym.primitives[rect_i].geom
    bx1, bx2 = sorted((float(g["x_mm"]), float(g["x2_mm"])))
    by1, by2 = sorted((float(g["y_mm"]), float(g["y2_mm"])))
    ys = sorted((u(by1) * y_sign, u(by2) * y_sign))
    return u(bx1), u(bx2), ys[0], ys[1]


def _augment_defaults_with_rotated_fonts(defaults: str, escapements: list[int]) -> str:
    """把旋转字体追加进 DefaultValues。

    Capture 的 CommentText 在二进制里只存一个「字体表下标」，XML 里的
    TextFont 要和 DefaultValues/DefaultFont 对得上才能稳定落盘。默认表里
    24 个字体全是 escapement=0，这里补上竖排用的 900（以及探针用的其他角度）。
    """
    if not escapements:
        return defaults
    used = {0}
    for m in re.finditer(r'<DefaultFont>\s*<Defn[^>]*escapement="(\d+)"', defaults):
        used.add(int(m.group(1)))
    next_idx = 0
    for m in re.finditer(r'<DefaultFont>\s*<Defn[^>]*index="(\d+)"', defaults):
        next_idx = max(next_idx, int(m.group(1)) + 1)
    extra = []
    for esc in escapements:
        if esc in used:
            continue
        extra.append(
            '    <DefaultFont>\n'
            f'      <Defn charset="0" escapement="{esc}" height="-9" index="{next_idx}" '
            f'italic="0" name="Arial" orientation="{esc}" weight="400" width="4"/>\n'
            "    </DefaultFont>"
        )
        used.add(esc)
        next_idx += 1
    if not extra:
        return defaults
    return defaults.replace("</DefaultValues>", "\n".join(extra) + "\n  </DefaultValues>")


def generate_package_xml(
    sym: Symbol,
    *,
    package_name: str,
    footprint: str = "",
    refdes_prefix: str = "",
    y_sign: int = -1,
    include_text: bool = False,
) -> str:
    """生成一个 `<Package>`（= 库里一个元件）。

    `y_sign=-1` 是**必须的默认值**：Capture 符号坐标 Y 向下，而我们的模型 Y 向上。
    两处独立参考实现都写 `y = -coord(...)`；之前用 +1 导致整个符号上下镜像
    （TESTEN/GND 跑到顶上、电源脚挤到底部）。这里对引脚、矩形、文字、BBox
    和位号/值的位置统一翻转，别再只翻引脚。
    """
    sym = normalize_capture_symbol(sym)
    prefix = (refdes_prefix or sym.prefix or "U").rstrip("?")

    # 引脚名==编号 → 名字是冗余的（电阻、排针、连接器都这样），隐藏掉，
    # 否则 Capture 会把「1」和「1」并排画两遍。
    hide_pin_names = pin_names_hidden(sym)

    # Names and numbers belong to SymbolPinScalar/PhysicalPart. Do not add
    # CommentText substitutes: users must be able to toggle native visibility.

    xs: list[int] = []
    ys: list[int] = []

    graphics: list[str] = []
    for prim in sym.primitives:
        k, g = prim.kind, prim.geom
        if k == "R" and "w_mm" in g:
            graphics.append(_rect_xml(g, y_sign=y_sign))
            xs += [u(g["x_mm"]), u(g["x2_mm"])]
            ys += [u(g["y_mm"]) * y_sign, u(g["y2_mm"]) * y_sign]
        elif k in ("PL", "PG", "PT") and g.get("points_mm"):
            lines, points = _polyline_xml(g, y_sign=y_sign, closed=k == "PG")
            graphics.extend(lines)
            xs.extend(x for x, y in points)
            ys.extend(y for x, y in points)
        elif k in ("C", "E") and "x_mm" in g:
            ellipse, points = _ellipse_xml(g, y_sign=y_sign)
            graphics.append(ellipse)
            xs.extend(x for x, y in points)
            ys.extend(y for x, y in points)
        elif k == "T" and "text" in g and include_text:
            graphics.append(_text_xml(g, y_sign=y_sign))

    pins_xml: list[str] = []
    pin_numbers: list[str] = []
    passive_two_terminal = prefix.upper() in {"C", "R", "L"} and len(sym.pins) == 2
    for i, pin in enumerate(sym.pins):
        pins_xml.append(
            _pin_xml(i, pin, y_sign=y_sign, force_passive=passive_two_terminal)
        )
        xs.append(u(pin.x_mm))
        ys.append(u(pin.y_mm) * y_sign)
        pin_numbers.append(
            f'        <PinNumber><Defn number={quoteattr(pin.number)} position="{i}"/></PinNumber>'
        )

    x1, x2 = (min(xs), max(xs)) if xs else (0, 0)
    y1, y2 = (min(ys), max(ys)) if ys else (0, 0)

    # —— SymbolBBox：OrCAD 的惯例是「虚线框 = 本体实线矩形」，两者重合；
    # 引脚从边线向外伸出，编号/名字在虚线框外（用户机器上的参考件
    # samples/ref_capture172.xml 就是这样：Rect 与 BBox 完全一致，
    # 引脚 hotptX=80 在 x2=50 之外）。2026-10-19 v7 真机反馈：BBox 若取
    # 引脚端点范围，虚线框会跑到引脚外面，顶部贴死窗口、引脚也不再「贴框」。
    body_edges = _signed_body_edges(sym, y_sign=y_sign)
    if body_edges is not None:
        x1, x2, y1, y2 = body_edges

    # 位号显示在方框下方，值显示在上方 —— 跟参考件的位置关系一致
    ref_y = y1 - 14
    val_y = y2 + 4

    ts = int(time.time())

    body = [
        "  <Package>",
        f'    <Defn alphabeticNumbering="2" isHomogeneous="1" name={quoteattr(package_name)} '
        f'pcbFootprint={quoteattr(footprint)} pcbLib="" '
        f'refdesPrefix={quoteattr(prefix)} timestamp="{ts}" timezone="1300"/>',
        "    <LibPart>",
        f"      <Defn CellName={quoteattr(package_name)}/>",
        "      <NormalView>",
        '        <Defn suffix=".Normal"/>',
        "        <SymbolDisplayProp>",
        f'          <Defn locX="{x1}" locY="{ref_y}" name="Part Reference" '
        'rotation="0" textJustification="0"/>',
        '          <PropFont><Defn charset="0" escapement="0" height="-9" italic="0" '
        'name="" orientation="0" weight="400" width="4"/></PropFont>',
        '          <PropColor><Defn val="48"/></PropColor>',
        '          <PropDispType><Defn ValueIfValueExist="0" val="1"/></PropDispType>',
        "        </SymbolDisplayProp>",
        "        <SymbolDisplayProp>",
        f'          <Defn locX="{x1}" locY="{val_y}" name="Value" '
        'rotation="0" textJustification="0"/>',
        '          <PropFont><Defn charset="0" escapement="0" height="-9" italic="0" '
        'name="" orientation="0" weight="400" width="4"/></PropFont>',
        '          <PropColor><Defn val="48"/></PropColor>',
        '          <PropDispType><Defn ValueIfValueExist="0" val="1"/></PropDispType>',
        "        </SymbolDisplayProp>",
        '        <SymbolColor><Defn val="48"/></SymbolColor>',
        f'        <SymbolBBox><Defn x1="{x1}" x2="{x2}" y1="{y1}" y2="{y2}"/></SymbolBBox>',
        '        <IsPinNumbersVisible><Defn val="1"/></IsPinNumbersVisible>',
        '        <IsPinNamesRotated><Defn val="1"/></IsPinNamesRotated>',
        f'        <IsPinNamesVisible><Defn val="{0 if hide_pin_names else 1}"/></IsPinNamesVisible>',
        '        <ContentsLibName><Defn name=""/></ContentsLibName>',
        '        <ContentsViewName><Defn name=""/></ContentsViewName>',
        '        <ContentsViewType><Defn type="0"/></ContentsViewType>',
        f'        <PartValue><Defn name={quoteattr(sym.name)}/></PartValue>',
        f'        <Reference><Defn name={quoteattr(prefix)}/></Reference>',
    ]
    body += graphics
    body += pins_xml
    # Capture preserves PackageUserProp in the OLB, but does not inherit it
    # onto placed symbols. Store instance defaults on the NormalView instead.
    # pcbFootprint above also sets the built-in "PCB Footprint" property.
    for name, value in (
        ("Description", sym.description),
        ("PCBFootprint", footprint),
        ("Manufacturer", sym.manufacturer),
        ("Manufacturer_PN", sym.mpn),
    ):
        body += [
            "        <SymbolUserProp>",
            f"          <Defn name={quoteattr(name)} val={quoteattr(value or '')}/>",
            "        </SymbolUserProp>",
        ]
    body += [
        "      </NormalView>",
        "      <PhysicalPart>",
        "        <Defn/>",
    ]
    body += pin_numbers
    body += [
        "      </PhysicalPart>",
        "    </LibPart>",
        "  </Package>",
    ]
    return "\n".join(body)


def generate_lib_xml(
    sym: Symbol,
    *,
    lib_path: str = "",
    package_name: str = "",
    footprint: str = "",
    refdes_prefix: str = "",
    defaults: str | None = None,
    y_sign: int = -1,
    include_text: bool = False,
) -> str:
    """生成完整的 `<Lib>` XML —— 可直接喂给 `XMATIC_XML2OLB`。"""
    pkg = package_name or sym.name or "PART"
    defaults = (defaults or default_values_block()).strip()

    # ⚠ <Defn name> 绝不能空：实测空的 <Defn/> 会让 XMATIC_XML2OLB 什么都不写，
    # 只回一个 DboState 句柄。这里兜底给个名字。
    lib_path = (lib_path or "").strip() or f"{pkg}.olb"

    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>',
            '<Lib xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="olb.xsd">',
            "",
            f"  <Defn name={quoteattr(lib_path)}/>",
            "",
            "  " + defaults.replace("\n", "\n  "),
            "",
            generate_package_xml(
                sym,
                package_name=pkg,
                footprint=footprint,
                refdes_prefix=refdes_prefix,
                y_sign=y_sign,
                include_text=include_text,
            ),
            "",
            "</Lib>",
            "",
        ]
    )


def generate_text_probe_xml(lib_path: str = "text_probe.olb") -> str:
    """生成一个「文字探针」库，用来在真机上标定 CommentText 的锚点/旋转语义。

    Capture 的文字图元在 OLB 二进制里只存 locX/locY + 字体表下标；XML 的
    `textJustification` 与 LOGFONT 的 escapement/orientation 到底怎么解释，
    只有真机截图能回答。这个元件里每个锚点都画了一个 4×4 的小方块作为
    「锚点标记」，标签文字则演示不同的 escapement / textJustification：

        左边一列（x=0）   ESC0 / ESC900 / ESC1800 / ESC2700 / NOFONT
        右边一列（x=200） J0 / J1 / J2 / J3（textJustification = 0..3）

    打开后对照：「ESCxxx」文字相对其左侧小方块往哪个方向延伸、字是正的
    还是转了、J0..J3 的 locX 是当左边界还是右边界 —— 一眼就能定。
    """
    labels = [
        ("ESC0", 0, 0, 0, 0, True),
        ("ESC900", 0, 40, 900, 0, True),
        ("ESC1800", 0, 80, 1800, 0, True),
        ("ESC2700", 0, 120, 2700, 0, True),
        ("NOFONT", 0, 160, 0, 0, False),
        ("J0", 200, 0, 0, 0, True),
        ("J1", 200, 40, 0, 1, True),
        ("J2", 200, 80, 0, 2, True),
        ("J3", 200, 120, 0, 3, True),
    ]
    texts = []
    for text, x, y, esc, just, with_font in labels:
        w = len(text) * PIN_LABEL_CHAR_W
        texts.append(_comment_text_xml(
            text, x, y,
            x1=x, x2=x + w, y1=y - 8, y2=y + 2,
            escapement=esc, orientation=esc,
            justification=just, with_font=with_font,
        ))
    markers = []
    for text, x, y, *_ in labels:
        markers.append(
            "        <Rect>\n"
            '          <Defn fillStyle="0" hatchStyle="-1" lineStyle="0" lineWidth="0" '
            f'x1="{x - 2}" x2="{x + 2}" y1="{y - 2}" y2="{y + 2}"/>\n'
            "        </Rect>"
        )

    defaults = _augment_defaults_with_rotated_fonts(
        default_values_block(), [900, 1800, 2700]
    )
    ts = int(time.time())
    body = [
        "  <Package>",
        f'    <Defn alphabeticNumbering="2" isHomogeneous="1" name="TEXT_PROBE" '
        f'pcbFootprint="" pcbLib="" refdesPrefix="TP" timestamp="{ts}" timezone="1300"/>',
        "    <LibPart>",
        "      <Defn CellName=\"TEXT_PROBE\"/>",
        "      <NormalView>",
        '        <Defn suffix=".Normal"/>',
        "        <SymbolDisplayProp>",
        '          <Defn locX="-40" locY="-60" name="Part Reference" rotation="0" textJustification="0"/>',
        '          <PropFont><Defn charset="0" escapement="0" height="-9" italic="0" '
        'name="Arial" orientation="0" weight="400" width="4"/></PropFont>',
        '          <PropColor><Defn val="48"/></PropColor>',
        '          <PropDispType><Defn ValueIfValueExist="0" val="1"/></PropDispType>',
        "        </SymbolDisplayProp>",
        '        <SymbolColor><Defn val="48"/></SymbolColor>',
        '        <SymbolBBox><Defn x1="-40" x2="430" y1="-40" y2="230"/></SymbolBBox>',
        '        <IsPinNumbersVisible><Defn val="1"/></IsPinNumbersVisible>',
        '        <IsPinNamesRotated><Defn val="1"/></IsPinNamesRotated>',
        '        <IsPinNamesVisible><Defn val="0"/></IsPinNamesVisible>',
        '        <ContentsLibName><Defn name=""/></ContentsLibName>',
        '        <ContentsViewName><Defn name=""/></ContentsViewName>',
        '        <ContentsViewType><Defn type="0"/></ContentsViewType>',
        '        <PartValue><Defn name="TEXT_PROBE"/></PartValue>',
        '        <Reference><Defn name="TP"/></Reference>',
    ]
    body += texts
    body += markers
    body += [
        "        <Rect>",
        '          <Defn fillStyle="1" hatchStyle="-1" lineStyle="0" lineWidth="0" '
        'x1="-40" x2="430" y1="-40" y2="230"/>',
        "        </Rect>",
        "      </NormalView>",
        "      <PhysicalPart>",
        "        <Defn/>",
        "      </PhysicalPart>",
        "    </LibPart>",
        "  </Package>",
    ]
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>',
            '<Lib xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:noNamespaceSchemaLocation="olb.xsd">',
            "",
            f"  <Defn name={quoteattr(lib_path)}/>",
            "",
            "  " + defaults.replace("\n", "\n  "),
            "",
            "\n".join(body),
            "",
            "</Lib>",
            "",
        ]
    )

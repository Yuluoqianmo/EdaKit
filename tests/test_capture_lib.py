"""Capture 真方言的生成器测试。

真方言来自用户机器上 Capture 17.2 的真实导出（samples/ref_capture172.xml）。
这里锁住几件关键事：
  * 输出是 <Lib>/<Package>/<LibPart>/<NormalView> 这套结构，不是我们早先猜的；
  * 坐标按 10 mil 换算，整数；
  * 引脚 start(本体端)/hotpt(连接端) 的方向不能反 —— 反了元件会「长反」；
  * DefaultValues 原样带上（Capture 认它）；
  * 生成的 XML 能被 XMATIC 解析器（ElementTree）读出来。
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from conftest import DATA

from edakit.easyeda.parse import parse_component
from edakit.easyeda.model import Symbol
from edakit.symbol.capture_lib import (
    CAPTURE_UNIT_MM,
    PIN_NAME_CHAR_MM,
    PIN_NAME_GAP_MM,
    default_values_block,
    extract_default_values,
    generate_lib_xml,
    generate_package_xml,
    is_capture_lib_dialect,
    layout_vertical_pins,
    normalize_capture_symbol,
    u,
)

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "samples" / "ref_capture172.xml"


def _comp(name="C25804"):
    payload = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    return parse_component(name, payload)


def test_unit_is_10_mil():
    # 2.54 mm = 100 mil = 10 单位
    assert u(2.54) == 10
    assert u(25.4) == 100
    assert CAPTURE_UNIT_MM == 0.254


def test_reference_is_the_real_dialect():
    ref = REF.read_text(encoding="utf-8")
    assert is_capture_lib_dialect(ref)
    assert extract_default_values(ref).startswith("<DefaultValues>")


def test_generated_xml_is_real_dialect_and_wellformed():
    xml = generate_lib_xml(_comp().symbol, package_name="R0603", footprint="R0603")
    assert is_capture_lib_dialect(xml)
    root = ET.fromstring(xml)
    assert root.tag == "Lib"
    pkg = root.find("Package")
    assert pkg is not None
    assert pkg.find("Defn").get("name") == "R0603"
    assert pkg.find("Defn").get("pcbFootprint") == "R0603"


def test_default_values_are_carried_over():
    xml = generate_lib_xml(_comp().symbol, package_name="R0603")
    root = ET.fromstring(xml)
    dv = root.find("DefaultValues")
    assert dv is not None
    # 24 个字体 + 页面设置 + 字段映射
    assert len(dv.findall("DefaultFont")) == 24
    assert dv.find("DefaultPageRec") is not None


def test_placement_properties_preserve_exact_names_values_and_hidden_display():
    symbol = Symbol(name="GENERIC_HEADER", description='描述 <5V & "quoted">\r\nnext\tline',
                    manufacturer="厂商 & Co.", mpn="2.54-1*40P直针")
    footprint = 'HDR_1x40_"A&B"'
    package = ET.fromstring(generate_package_xml(symbol, package_name="HEADER_P3", footprint=footprint))
    props = package.findall("LibPart/NormalView/SymbolUserProp/Defn")
    assert len(props) == 4
    assert {p.get("name"): p.get("val") for p in props} == {
        "Description": symbol.description,
        "PCBFootprint": footprint,
        "Manufacturer": symbol.manufacturer,
        "Manufacturer_PN": symbol.mpn,
    }
    assert package.find("Defn").get("pcbFootprint") == footprint
    assert package.find(".//PartValue/Defn").get("name") == symbol.name
    assert {p.get("name") for p in package.findall(".//SymbolDisplayProp/Defn")} == {"Part Reference", "Value"}
    # PackageUserProp survives library conversion but is not inherited on place.
    assert not package.findall("PackageUserProp")


def test_missing_metadata_keeps_four_empty_properties():
    package = ET.fromstring(generate_package_xml(Symbol(name="UNKNOWN"), package_name="UNKNOWN_P3"))
    assert {p.get("name"): p.get("val") for p in package.findall("LibPart/NormalView/SymbolUserProp/Defn")} == {
        "Description": "", "PCBFootprint": "", "Manufacturer": "", "Manufacturer_PN": "",
    }


def test_symbol_bbox_and_rect_are_integer_units():
    comp = _comp()  # 0603: 本体 5.08 x 2.032 mm
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="R0603"))
    bbox = root.find(".//SymbolBBox/Defn")
    rect = root.find(".//Rect/Defn")
    for k in ("x1", "x2", "y1", "y2"):
        assert bbox.get(k).lstrip("-").isdigit()
    # 本体宽 5.08mm = 20 单位
    assert int(rect.get("x2")) - int(rect.get("x1")) == 20
    # OrCAD 惯例：虚线框（SymbolBBox）= 本体实线矩形，见下面的专门测试
    for k in ("x1", "x2", "y1", "y2"):
        assert bbox.get(k) == rect.get(k)


def test_symbol_bbox_is_the_body_outline():
    """SymbolBBox（Capture 里画的虚线框）必须与本体实线矩形重合。

    回归背景（2026-10-19 v7 真机反馈）：BBox 取「引脚端点 + 本体」的总范围时，
    虚线框跑到引脚外面，顶部贴死编辑窗口、不好拖动查看；
    OrCAD 自家符号（用户参考件 samples/ref_capture172.xml）是
    Rect x1=0 x2=50 y1=0 y2=50、SymbolBBox 完全一样，
    引脚 hotptX=80 从框边 startX=50 向外伸 —— 即「引脚在虚线框外、贴着框」。
    """
    for cid, pkg in (("C2040", "RP2040"), ("C25804", "R0603")):
        comp = _comp(cid)
        root = ET.fromstring(generate_lib_xml(comp.symbol, package_name=pkg))
        bbox = root.find(".//SymbolBBox/Defn")
        rect = root.find(".//Rect/Defn")
        for k in ("x1", "x2", "y1", "y2"):
            assert bbox.get(k) == rect.get(k), (pkg, k)

        bx1, bx2 = int(bbox.get("x1")), int(bbox.get("x2"))
        by1, by2 = int(bbox.get("y1")), int(bbox.get("y2"))
        pins = [s.find("Defn") for s in root.findall(".//SymbolPinScalar")]
        assert pins
        for d in pins:
            hx, hy = int(d.get("hotptX")), int(d.get("hotptY"))
            # 连接点不能在虚线框内部（贴边或在外侧都行）
            assert not (bx1 < hx < bx2 and by1 < hy < by2), (pkg, d.get("name"))


def test_pin_geometry_start_is_body_end_hot_is_connection():
    comp = _comp()
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="R0603"))
    pins = root.findall(".//SymbolPinScalar")
    assert len(pins) == 2

    p0 = pins[0].find("Defn")
    start_x = int(p0.get("startX"))
    hot_x = int(p0.get("hotptX"))
    # 0603 的 2 号脚在右边：连接端必须比本体端更靠外
    assert abs(hot_x) > abs(start_x)
    assert (hot_x > 0) == (start_x > 0)
    # 引脚长 2.54mm = 10 单位
    assert abs(hot_x - start_x) == 10


def test_pin_numbers_mapping_is_complete():
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    scalars = root.findall(".//SymbolPinScalar")
    numbers = root.findall(".//PhysicalPart/PinNumber/Defn")
    assert len(scalars) == 57
    assert len(numbers) == 57
    # 每个 scalar 的 position 都能在 PinNumber 里找到；且号码集合一致
    positions = {s.find("Defn").get("position") for s in scalars}
    npos = {n.get("position") for n in numbers}
    assert positions == npos
    assert {n.get("number") for n in numbers} == {p.number for p in comp.symbol.pins}


def test_pin_type_codes_are_ints():
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    codes = {s.find("Defn").get("type") for s in root.findall(".//SymbolPinScalar")}
    assert codes <= {"0", "1", "2", "3", "4", "5", "6", "7"}
    # C2040 有 bidirectional / output / input / unspecified
    # 真实 OrCAD PortType：Input=0 Bidirectional=1 Output=2 Passive=4 Power=7
    assert "1" in codes      # bidirectional (GPIO)
    assert "2" in codes      # output (QSPI_SCLK)
    assert "0" in codes      # input (RUN/XIN)
    assert "4" in codes      # unspecified -> passive


def test_pin_type_mapping_matches_orcad_porttype():
    from edakit.symbol.capture_lib import PIN_TYPE_CODE
    assert PIN_TYPE_CODE["input"] == 0
    assert PIN_TYPE_CODE["bidirectional"] == 1
    assert PIN_TYPE_CODE["output"] == 2
    assert PIN_TYPE_CODE["open_collector"] == 3
    assert PIN_TYPE_CODE["passive"] == 4
    assert PIN_TYPE_CODE["tri_state"] == 5
    assert PIN_TYPE_CODE["open_emitter"] == 6
    assert PIN_TYPE_CODE["power"] == 7
    assert PIN_TYPE_CODE["unspecified"] == 4


def test_y_is_flipped_capture_y_points_down():
    """Capture 符号坐标 Y 向下，我们的模型 Y 向上 —— 生成时必须取反。

    回归背景（2026-10-19 用户截图）：不翻转时整个符号上下镜像，
    TESTEN/GND（本应在底部）跑到了顶上，顶部 12 个电源脚挤到底部。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    pins = {s.find("Defn").get("name"): s.find("Defn") for s in root.findall(".//SymbolPinScalar")}
    # EasyEDA 里 TESTEN/GND 在底边（y_mm 最小），Capture 里应落在 +Y（下方）
    assert int(pins["TESTEN"].get("hotptY")) > 0
    assert int(pins["GND"].get("hotptY")) > 0
    # 顶边的电源脚（y_mm 最大）应落在 -Y（上方）
    assert int(pins["ADC_AVDD"].get("hotptY")) < 0
    # 竖排引脚的 start（本体端）永远比 hotpt（连接端）更靠近本体
    assert abs(int(pins["ADC_AVDD"].get("hotptY"))) > abs(int(pins["ADC_AVDD"].get("startY")))
    # 矩形也要一起翻：Rect y1<y2，且本体中心在 0 附近
    rect = root.find(".//Rect/Defn")
    assert int(rect.get("y1")) < int(rect.get("y2"))


def test_long_pins_are_marked_long():
    """IsLong=0 时 Capture 只画一半引脚长度（OpenOrCadParser 已从二进制确认）。

    我们的引脚都是 100 mil = 10 单位，必须写 IsLong=1；否则名字/编号的
    默认摆放会跟着「短引脚」样式一起跑偏。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    longs = [s.find("IsLong/Defn").get("val") for s in root.findall(".//SymbolPinScalar")]
    assert longs and all(v == "1" for v in longs)


def test_refdes_prefix_strips_question_mark():
    comp = _comp()
    xml = generate_lib_xml(comp.symbol, package_name="R0603", refdes_prefix="R?")
    root = ET.fromstring(xml)
    assert root.find("Package/Defn").get("refdesPrefix") == "R"
    assert root.find(".//Reference/Defn").get("name") == "R"


def test_text_is_off_by_default():
    """原理图自带文字图元默认不导出；引脚名/编号（CommentText）全部自绘。"""
    comp = _comp("C2040")   # 这个元件带 2 个文字图元
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    assert root.findall(".//Text") == []
    # 57 个引脚名标签 + 57 个自绘编号标签（四边全画），
    # 不带元件自带的 2 段文字；顶部留白从 v10 起改用矩形探针，不再用空白文字
    assert len(root.findall(".//CommentText")) == 114
    # 0603 没有竖直引脚，名字=编号被隐藏；编号仍然自绘（两脚各一个）
    root2 = ET.fromstring(generate_lib_xml(_comp("C25804").symbol, package_name="R0603"))
    texts2 = root2.findall(".//CommentText")
    assert len(texts2) == 2
    assert all(_is_number_label(t) for t in texts2)


def _label_name(t):
    return t.find("Defn").get("name")


def _is_number_label(t):
    return _label_name(t).isdigit()


def test_pin_name_labels_are_rotated_per_side():
    """顶/底引脚名必须竖排（escapement=900），左右引脚名保持横排。

    回归背景（2026-10-19 真机）：IsPinNamesRotated=1 在 17.2 上不生效，
    顶边 12 个名字横排叠成一片。改为隐藏 Capture 名字、用 CommentText 自绘。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    texts = [t for t in root.findall(".//CommentText") if not _is_number_label(t)]

    def esc(t):
        return t.find("TextFont/Defn").get("escapement")

    rotated = [_label_name(t) for t in texts if esc(t) != "0"]
    # 顶边 12 + 底边 2 = 14 个竖排名（DVDD/IOVDD 有重名，不能按名字去重）
    assert len(rotated) == 14
    for name in ("ADC_AVDD", "IOVDD1", "TESTEN", "GND"):
        assert name in rotated
    flat = {_label_name(t) for t in texts if esc(t) == "0"}
    for name in ("GPIO7", "QSPI_SS", "USB_DP"):
        assert name in flat and name not in rotated


def test_pin_name_labels_sit_inside_body():
    """自绘名字必须在框内：左右名字不越出本体边线，上下名字落在外框之间。

    编号标签是画在框外的，这里按「纯数字」把它们排除。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    rect = root.find(".//Rect/Defn")
    bx1, bx2 = int(rect.get("x1")), int(rect.get("x2"))
    by1, by2 = int(rect.get("y1")), int(rect.get("y2"))
    for t in root.findall(".//CommentText"):
        if _is_number_label(t):
            continue
        d = t.find("Defn")
        x, y = int(d.get("locX")), int(d.get("locY"))
        assert bx1 < x < bx2, (d.get("name"), x)
        assert by1 < y < by2, (d.get("name"), y)


def test_vertical_pin_numbers_stay_within_pin_extent():
    """顶/底编号竖排自绘，且必须落在引脚长度范围内（不被取景裁掉）。

    回归背景：v5 截图顶边 12 个横排编号叠成一团 → 改自绘竖排；
    v11 截图发现画在引脚端点**之外**的编号被零件编辑器裁掉（初始取景 =
    虚线框 ∪ 引脚的包围盒、零内边距）。所以编号改为贴着端点内侧、沿引脚线。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))

    pins = {}
    for sp in root.findall(".//SymbolPinScalar"):
        d = sp.find("Defn")
        pins[(int(d.get("hotptX")), int(d.get("hotptY")))] = d

    nums = [t for t in root.findall(".//CommentText") if _is_number_label(t)]
    vertical = [t for t in nums if t.find("TextFont/Defn").get("escapement") == "900"]
    assert len(vertical) == 14  # 顶边 12 + 底边 2
    for t in vertical:
        d = t.find("Defn")
        x = int(d.get("locX"))
        px = x - 3                        # 编号锚点固定在引脚线右侧 3 单位
        y1, y2 = int(d.get("y1")), int(d.get("y2"))
        # 找到同一 x 列、端点离该编号最近的竖直引脚（顶边或底边）
        # —— 顶/底引脚可能共用同一 x 列，必须按端点距离消歧
        yloc = int(d.get("locY"))
        match = [p for (hx, hy), p in pins.items() if hx == px]
        assert match, ("找不到编号对应的引脚", _label_name(t), x)
        pin = min(match, key=lambda p: abs(int(p.get("hotptY")) - yloc))
        hotpt = int(pin.get("hotptY"))
        start = int(pin.get("startY"))
        lo, hi = sorted((hotpt, start))
        if hotpt < start:   # 顶边：编号不能越过端点（向上超出）
            assert y1 >= hotpt - 1, ("顶边编号超出引脚端点会被裁", _label_name(t), y1, hotpt)
            assert y2 <= hi + 3, ("编号不应深入本体过多", _label_name(t), y2, hi)
        else:               # 底边：编号不能越过端点（向下超出）
            assert y2 <= hotpt + 1, ("底边编号超出引脚端点会被裁", _label_name(t), y2, hotpt)
            assert y1 >= lo - 3, ("编号不应深入本体过多", _label_name(t), y1, lo)


def test_all_pin_numbers_self_drawn_outside_body():
    """四边编号全部自绘、画在框外；Capture 原生编号全局关闭。

    回归背景：
    * 2026-10-19 v6：右侧编号被 Capture 画在框内压住名字；
    * 2026-10-20：库经 OLB2XML→XML2OLB 规范化后，per-pin IsNumberVisible
      在二进制里丢失，放置时原生编号又冒出来 → 每个脚两个编号。
    修法：`IsPinNumbersVisible=0` 全局关闭，57 个编号全部来自 CommentText。
    """
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    rect = root.find(".//Rect/Defn")
    bx1, bx2 = int(rect.get("x1")), int(rect.get("x2"))

    nums = [t for t in root.findall(".//CommentText") if _is_number_label(t)]
    assert len(nums) == 57
    horizontal = [t for t in nums if t.find("TextFont/Defn").get("escapement") == "0"]
    assert len(horizontal) == 43           # 左 11 + 右 32
    for t in horizontal:
        d = t.find("Defn")
        x1, x2 = int(d.get("x1")), int(d.get("x2"))
        assert x2 <= bx1 or x1 >= bx2, ("水平编号必须落在框外", _label_name(t), x1, x2)

    # 每个引脚自己的编号开关全部关闭（二进制不保存它，只是不想再冒险）
    flags = [s.find("IsNumberVisible/Defn").get("val") for s in root.findall(".//SymbolPinScalar")]
    assert set(flags) == {"0"}
    # 全局开关也关闭 → 放置时不会再画出原生编号
    assert root.find(".//IsPinNumbersVisible/Defn").get("val") == "0"


def test_horizontal_only_parts_also_self_draw_numbers():
    """纯水平引脚（排针、阻容）的编号同样自绘，原生编号全局关闭。"""
    comp = _comp("C2337")  # 40P 排针，全部是左侧水平引脚
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="HEADER40"))
    texts = root.findall(".//CommentText")
    assert len(texts) == 40
    assert all(_is_number_label(t) for t in texts)
    assert root.find(".//IsPinNumbersVisible/Defn").get("val") == "0"
    flags = [s.find("IsNumberVisible/Defn").get("val") for s in root.findall(".//SymbolPinScalar")]
    assert flags and set(flags) == {"0"}


def test_rotated_font_is_registered_in_defaults():
    """CommentText 的竖排字体必须在 DefaultValues 字体表里有一席之地。"""
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    escs = {f.find("Defn").get("escapement") for f in root.findall("DefaultValues/DefaultFont")}
    assert "900" in escs
    # 0603 不用竖排，字体表保持原样（24 个）
    root2 = ET.fromstring(generate_lib_xml(_comp("C25804").symbol, package_name="R0603"))
    assert len(root2.findall("DefaultValues/DefaultFont")) == 24


def test_text_probe_generator_is_schema_shaped():
    from edakit.symbol.capture_lib import generate_text_probe_xml

    root = ET.fromstring(generate_text_probe_xml("D:/cadence/text_probe.olb"))
    assert root.find("Package/Defn").get("name") == "TEXT_PROBE"
    texts = root.findall(".//CommentText")
    assert len(texts) == 9
    names = {t.find("Defn").get("name") for t in texts}
    assert {"ESC0", "ESC900", "NOFONT", "J0", "J3"} <= names
    escs = {t.find("TextFont/Defn").get("escapement") for t in texts if t.find("TextFont") is not None}
    assert {"0", "900", "1800", "2700"} <= escs
    # 字体表补齐三种旋转角度
    dfl = {f.find("Defn").get("escapement") for f in root.findall("DefaultValues/DefaultFont")}
    assert {"900", "1800", "2700"} <= dfl


def test_text_can_be_enabled_as_comment_text():
    """17.2 的 olb.xsd 里没有 <Text>，文字图元是 CommentText（x1/x2/y1/y2 必填）。"""
    comp = _comp("C2040")
    root = ET.fromstring(
        generate_lib_xml(comp.symbol, package_name="RP2040", include_text=True)
    )
    texts = root.findall(".//CommentText")
    # 57 个引脚名标签 + 57 个自绘编号标签 + 2 个元件自带文字
    # （顶部留白自 v10 起是矩形探针，不再计入 CommentText）
    assert len(texts) == 116
    for t in texts:
        d = t.find("Defn")
        for k in ("locX", "locY", "name", "x1", "x2", "y1", "y2"):
            assert d.get(k) is not None
        if t.find("TextFont/Defn") is None:
            continue  # NOFONT 探针才允许无字体
        assert t.find("TextFont/Defn").get("height") == "-9"


def test_default_values_block_is_available_offline():
    blk = default_values_block()
    assert blk.startswith("<DefaultValues>")
    assert "<DefaultFont>" in blk


def test_package_xml_reusable_for_merge():
    comp = _comp()
    pkg = generate_package_xml(comp.symbol, package_name="R0603")
    assert pkg.strip().startswith("<Package>")
    assert pkg.strip().endswith("</Package>")


def test_lib_defn_carries_target_path():
    """参考件里 <Defn name> 写的是 .olb 自己的路径；生成器必须能带上它。

    怀疑点：不带名字时 XMATIC_XML2OLB 可能直接无视输入（真机上见过）。
    """
    comp = _comp()
    xml = generate_lib_xml(
        comp.symbol, lib_path="D:/cadence/lcsc_test.olb", package_name="R0603"
    )
    root = ET.fromstring(xml)
    first = root.find("Defn")
    assert first is not None
    assert first.get("name") == "D:/cadence/lcsc_test.olb"


def test_lib_defn_never_empty():
    """<Defn name> 绝不能空。

    真机实测（2026-10-19）：空的 <Defn/> 会让 XMATIC_XML2OLB 什么都不写，
    只回一个 DboState 句柄 —— 看起来成功、其实没生成文件。
    没给 lib_path 时必须兜底成 "<Package 名>.olb"。
    """
    comp = _comp()
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="R0603"))
    first = root.find("Defn")
    assert first is not None
    assert first.get("name") == "R0603.olb"


def test_pin_names_hidden_when_identical_to_numbers():
    """电阻/排针这类「名字==编号」的元件，不要重复画两遍。"""
    comp = _comp("C25804")          # 0603，两个脚名字都是 "1" "2"
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="R0603"))
    flag = root.find(".//IsPinNamesVisible/Defn")
    assert flag.get("val") == "0"


def test_pin_names_visible_when_meaningful():
    comp = _comp("C2040")           # RP2040，引脚名是 GPIO7 之类
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    flag = root.find(".//IsPinNamesVisible/Defn")
    # 有竖直引脚 → 隐藏 Capture 自己画的名字，改由 CommentText 自绘（竖排）
    assert flag.get("val") == "0"


def test_generator_aligns_hotpoints_without_expanding_body():
    """Capture 连接点对齐 100 mil；本体不因文字宽度被拉大。"""
    comp = _comp("C2040")
    root = ET.fromstring(generate_lib_xml(comp.symbol, package_name="RP2040"))
    got = sorted(
        (s.find("Defn").get("name"), int(s.find("Defn").get("hotptX")))
        for s in root.findall(".//SymbolPinScalar")
    )
    want = sorted(
        (p.name, round(p.x_mm / 0.254))
        for p in normalize_capture_symbol(comp.symbol).pins
    )
    assert got == want
    # 本体的宽度也不应被改大：Rect 与 EasyEDA 最大矩形一致
    rect = root.find(".//Rect/Defn")
    assert int(rect.get("x2")) - int(rect.get("x1")) <= 360  # 原 ~353 单位


def test_vertical_pin_layout_helper_still_available():
    """兜底方案：若 17.2 上竖排名仍不旋转，可按名字宽度疏排（不默认启用）。"""
    comp = _comp("C2040")
    pin_x, rect = layout_vertical_pins(comp.symbol)
    assert pin_x, "RP2040 顶边引脚应被疏排"
    assert rect, "本体应被加宽"
    top = [i for i, p in enumerate(comp.symbol.pins) if abs(p.orientation_deg - 270) < 1e-6]
    top.sort(key=lambda i: pin_x.get(i, comp.symbol.pins[i].x_mm))
    xs = [pin_x.get(i, comp.symbol.pins[i].x_mm) for i in top]
    assert len(xs) == 12
    for a, b, ia, ib in zip(xs, xs[1:], top, top[1:]):
        need = (
            (len(comp.symbol.pins[ia].name) + len(comp.symbol.pins[ib].name))
            / 2
            * PIN_NAME_CHAR_MM
            + PIN_NAME_GAP_MM
        )
        assert b - a >= need - 0.26


def test_side_pins_follow_widened_body():
    """本体加宽后，左右两侧水平引脚的本体端必须贴在新边线上，不能悬空。"""
    comp = _comp("C2040")
    pin_x, rect = layout_vertical_pins(comp.symbol)
    geom = next(iter(rect.values()))
    x1, x2 = sorted((geom["x_mm"], geom["x2_mm"]))
    checked = 0
    for i, p in enumerate(comp.symbol.pins):
        if i not in pin_x:
            continue
        ang = p.orientation_deg % 360.0
        if abs(ang) > 1e-6 and abs(ang - 180.0) > 1e-6:
            continue  # 只看水平引脚
        start_x = pin_x[i] + p.length_mm * (1 if abs(ang) < 1e-6 else -1)
        assert abs(start_x - x1) < 0.01 or abs(start_x - x2) < 0.01, p.name
        checked += 1
    assert checked >= 40  # 左右两侧的引脚都平移到了新边线


def test_layout_is_noop_when_names_hidden():
    """名字==编号（电阻/排针）时名字整体隐藏，不需要疏排。"""
    comp = _comp("C25804")
    assert layout_vertical_pins(comp.symbol, names_visible=False) == ({}, {})
    # 默认参数（可见）也不该动：0603 只有水平引脚
    assert layout_vertical_pins(comp.symbol) == ({}, {})


def test_generated_xml_validates_against_real_17_2_xsd():
    """用用户机器上 Capture 17.2 自带 olb.xsd 做真正的 schema 校验。

    回归背景：之前 include_text=True 会输出 `<Text>`，而 17.2 的 XSD 根本没有
    这个元素（只有 CommentText）；引脚/矩形尺寸也全都要求整数。XMATIC 容错
    不代表 schema 合法，这类错误只有 XSD 能提前抓住。
    """
    import pytest

    lxml = pytest.importorskip("lxml.etree")
    xsd_path = ROOT / "tests" / "data" / "olb.xsd"
    if not xsd_path.is_file():
        pytest.skip("olb.xsd 不在测试数据里")
    schema = lxml.XMLSchema(lxml.parse(str(xsd_path)))
    for cid, pkg in (("C25804", "R0603"), ("C2040", "RP2040")):
        comp = _comp(cid)
        for include_text in (False, True):
            xml = generate_lib_xml(
                comp.symbol, package_name=pkg, include_text=include_text
            )
            doc = lxml.fromstring(xml.encode("utf-8"))
            assert schema.validate(doc), (
                f"{pkg} include_text={include_text}: "
                + "\n".join(str(e) for e in schema.error_log)
            )

    # 文字探针库也要过同一份 17.2 XSD（CommentText≤5、字体条目、包结构）
    from edakit.symbol.capture_lib import generate_text_probe_xml

    probe = lxml.fromstring(generate_text_probe_xml().encode("utf-8"))
    assert schema.validate(probe), "\n".join(str(e) for e in schema.error_log)

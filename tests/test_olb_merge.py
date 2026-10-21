"""OLB XML 合并测试 —— 这是 Capture 侧累积工程库的关键。"""

from edakit.symbol.olb import (
    extract_part_names,
    extract_parts,
    merge_files,
    merge_olb_xml,
)

BASE = """<?xml version="1.0"?>
<CaptureLibrary>
  <Part Name="OLD"><Pins><Pin Number="1"/></Pins></Part>
</CaptureLibrary>
"""

NEW = """<?xml version="1.0"?>
<CaptureLibrary>
  <Part Name="RP2040"><Pins><Pin Number="1"/></Pins></Part>
</CaptureLibrary>
"""


def test_extract_parts():
    parts = extract_parts(BASE)
    assert len(parts) == 1
    assert extract_part_names(parts[0]) == ["OLD"]


def test_merge_into_empty_base_is_new_library():
    assert merge_olb_xml("", NEW) == NEW


def test_merge_appends_new_part_before_root_close():
    merged = merge_olb_xml(BASE, NEW)
    names = extract_part_names(merged)
    assert names == ["OLD", "RP2040"]
    # RP2040 必须在根结束标签之前 (即 XML 仍合法)
    assert merged.index("RP2040") < merged.rindex("</CaptureLibrary>")


def test_merge_same_name_replaces_not_duplicates():
    merged = merge_olb_xml(BASE, NEW)
    merged2 = merge_olb_xml(merged, NEW)   # 再放一次同名元件
    assert extract_part_names(merged2) == ["OLD", "RP2040"]   # 没有重复堆叠


def test_merge_replaces_old_version_of_same_part():
    updated = NEW.replace("RP2040", "RP2040").replace("<Pin Number=\"1\"/>", "<Pin Number=\"1\"/><Pin Number=\"2\"/>")
    merged = merge_olb_xml(merge_olb_xml(BASE, NEW), updated)
    assert extract_part_names(merged) == ["OLD", "RP2040"]
    assert merged.count('<Pin Number="2"/>') == 1


def test_merge_ignores_part_file_without_parts():
    junk = "<CaptureLibrary></CaptureLibrary>"
    assert merge_olb_xml(BASE, junk) == BASE   # 不破坏原有 XML


def test_merge_files_roundtrip(tmp_path):
    (tmp_path / "base.xml").write_text(BASE, encoding="utf-8")
    (tmp_path / "part.xml").write_text(NEW, encoding="utf-8")
    out = tmp_path / "out.xml"
    n = merge_files(str(tmp_path / "base.xml"), str(tmp_path / "part.xml"), str(out))
    assert n == 2
    assert extract_part_names(out.read_text(encoding="utf-8")) == ["OLD", "RP2040"]


def test_merge_files_without_base(tmp_path):
    (tmp_path / "part.xml").write_text(NEW, encoding="utf-8")
    out = tmp_path / "out.xml"
    n = merge_files("", str(tmp_path / "part.xml"), str(out))
    assert n == 1
    assert out.exists()


# ---------------------------------------------------------------------------
#  真方言：合并单位是 <Package>，不是 <Part>
#  （2026-10-19 从 Capture 17.2 实测到的结构）
# ---------------------------------------------------------------------------

LIB_A = """<?xml version="1.0" encoding="UTF-8"?>
<Lib xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Defn name="a.olb"/>
  <DefaultValues><Defn/></DefaultValues>
  <Package>
    <Defn name="R0603" isHomogeneous="1"/>
    <LibPart><Defn CellName="R0603"/></LibPart>
  </Package>
</Lib>
"""

LIB_B = """<?xml version="1.0" encoding="UTF-8"?>
<Lib xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <Defn name="b.olb"/>
  <DefaultValues><Defn/></DefaultValues>
  <Package>
    <Defn name="RP2040" isHomogeneous="1"/>
    <LibPart><Defn CellName="RP2040"/></LibPart>
  </Package>
</Lib>
"""


def test_extract_package_names():
    from edakit.symbol.olb import extract_package_names, extract_packages

    assert len(extract_packages(LIB_A)) == 1
    assert extract_package_names(LIB_A) == ["R0603"]


def test_merge_packages_appends():
    from edakit.symbol.olb import extract_package_names, merge_olb_xml

    merged = merge_olb_xml(LIB_A, LIB_B)
    assert extract_package_names(merged) == ["R0603", "RP2040"]
    assert merged.rindex("</Lib>") > merged.rindex("</Package>")


def test_merge_packages_replaces_same_name():
    from edakit.symbol.olb import extract_package_names, merge_olb_xml

    updated = LIB_B.replace("RP2040", "RP2040").replace(
        '<LibPart><Defn CellName="RP2040"/></LibPart>',
        '<LibPart><Defn CellName="RP2040"/><Rect/></LibPart>',
    )
    merged = merge_olb_xml(merge_olb_xml(LIB_A, LIB_B), updated)
    assert extract_package_names(merged) == ["R0603", "RP2040"]
    assert merged.count("<Rect/>") == 1


def test_merge_preserves_defaultvalues_and_root_attrs():
    from edakit.symbol.olb import merge_olb_xml

    merged = merge_olb_xml(LIB_A, LIB_B)
    assert merged.count("<DefaultValues>") == 1        # 不重复
    assert 'xmlns:xsd="http://www.w3.org/2001/XMLSchema"' in merged
    assert '<Defn name="a.olb"/>' in merged            # base 的路径声明保留


def test_merge_package_into_empty_is_new_lib():
    from edakit.symbol.olb import merge_olb_xml

    assert merge_olb_xml("", LIB_B) == LIB_B

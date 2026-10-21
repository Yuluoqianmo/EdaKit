"""Capture 库 XML 结构分析测试。

learn-schema 是本项目风险最高的一步（OLB XML schema 未公开），所以它产出的
结构清单必须忠实反映参考文件 —— 这份清单是后续改生成器的唯一依据。
"""

import xml.etree.ElementTree as ET

import pytest

from edakit.symbol.olb_xml import (
    analyze_olb_xml,
    build_profile_from_olb_xml,
    render_schema_report,
)

# 一份「假想的真实 schema」：标签名故意跟 DEFAULT_PROFILE 不一样，
# 用来确认清单能如实报出差异（而不是抄我们自己的猜测）。
REF = """<?xml version="1.0" encoding="UTF-8"?>
<CaptureLibrary Version="2.0" xmlns:ns0="http://example/ns">
  <Part Name="REF" RefDesPrefix="U?">
    <PinList>
      <Pin Number="1" Name="VCC" X="0.0" Y="2.54" Length="2.54"/>
      <Pin Number="2" Name="GND" X="0.0" Y="-2.54" Length="2.54"/>
    </PinList>
    <Shapes>
      <BodyRect LL="-2.54,-2.54" UR="2.54,2.54"/>
      <Label X="0.0" Y="3.81">REF</Label>
    </Shapes>
    <Props>
      <Prop Name="PCB Footprint">SOIC-8</Prop>
    </Props>
  </Part>
</CaptureLibrary>
"""


def test_analyze_reports_real_tag_names_not_guesses():
    a = analyze_olb_xml(REF)
    paths = {e["path"] for e in a["elements"]}
    assert "CaptureLibrary" in paths
    assert "CaptureLibrary/Part" in paths
    assert "CaptureLibrary/Part/PinList" in paths
    assert "CaptureLibrary/Part/PinList/Pin" in paths
    # 这些是参考文件里真有的标签 —— 清单必须报出来（哪怕 DEFAULT_PROFILE 里没有）
    assert "CaptureLibrary/Part/Shapes/BodyRect" in paths
    assert "CaptureLibrary/Part/Props/Prop" in paths


def test_analyze_counts_and_attr_samples():
    a = analyze_olb_xml(REF)
    by_path = {e["path"]: e for e in a["elements"]}
    pin = by_path["CaptureLibrary/Part/PinList/Pin"]
    assert pin["count"] == 2
    assert set(pin["attrs"]) == {"Number", "Name", "X", "Y", "Length"}
    assert pin["attrs"]["Number"] == ["1", "2"]
    assert by_path["CaptureLibrary/Part"]["count"] == 1


def test_analyze_root_attrs_and_total_count():
    a = analyze_olb_xml(REF)
    assert a["root"] == "CaptureLibrary"
    assert a["rootAttrs"]["Version"] == "2.0"
    # 1 根 + 1 Part + 1 PinList + 2 Pin + 1 Shapes + 1 BodyRect + 1 Label + 1 Props + 1 Prop = 10
    assert a["elementCount"] == 10


def test_analyze_strips_namespace_prefixes():
    xml = '<ns0:Root xmlns:ns0="http://x"><ns0:Child Id="1"/></ns0:Root>'
    a = analyze_olb_xml(xml)
    assert a["root"] == "Root"
    assert [e["path"] for e in a["elements"]] == ["Root", "Root/Child"]


def test_analyze_reports_text_content():
    a = analyze_olb_xml(REF)
    by_path = {e["path"]: e for e in a["elements"]}
    assert by_path["CaptureLibrary/Part/Props/Prop"]["text"] == ["SOIC-8"]
    assert by_path["CaptureLibrary/Part/Shapes/Label"]["text"] == ["REF"]


def test_analyze_rejects_malformed_xml():
    with pytest.raises(ET.ParseError):
        analyze_olb_xml("<CaptureLibrary><Part></CaptureLibrary>")


def test_report_is_readable_and_mentions_real_tags():
    r = render_schema_report(analyze_olb_xml(REF), source="ref.xml")
    assert "CaptureLibrary" in r
    assert "PinList" in r
    assert "BodyRect" in r
    assert "ref.xml" in r
    assert "×2" in r                       # 出现次数
    assert "XMATIC_XML2OLB" in r           # 说明下一步怎么用


def test_profile_extraction_sees_this_dialect():
    """profile 至少应该认出 PinList / Props，而不是我们猜的 Pins / Properties。"""
    prof = build_profile_from_olb_xml(REF)
    assert prof["root"] == "CaptureLibrary"
    assert prof["pins"] == "PinList"
    assert prof["part"] == "Part"
    assert prof["properties"] == "Props"


def test_profile_keeps_defaults_when_tags_absent():
    """关键回归: 找不到的标签必须保留默认值，不能被写成 None。

    之前用「捕获命名空间前缀的那个组」取值，没前缀时该组为 None，
    会把 prof['part'] 覆盖成 None → 生成器吐出 <None ...>。
    """
    prof = build_profile_from_olb_xml('<Library><Thing/></Library>')
    assert prof["part"] == "Part"
    assert prof["pin"] == "Pin"
    assert prof["properties"] == "Properties"
    assert prof["root"] == "Library"          # 认得出别名根元素
    for k, v in prof.items():
        assert v is not None, f"prof[{k!r}] 被写成了 None"



def test_analyze_tolerates_single_part_no_pins():
    a = analyze_olb_xml('<Root><Part Name="X"/></Root>')
    by_path = {e["path"]: e for e in a["elements"]}
    assert by_path["Root/Part"]["attrs"]["Name"] == ["X"]
    assert by_path["Root/Part"]["count"] == 1


# ---------------------------------------------------------------------------
#  文件不存在 / 空文件时必须给人话，而不是甩 traceback
#  （用户真机上确实踩到过：XMATIC_OLB2XML 回了 DboState 但没写出文件）
# ---------------------------------------------------------------------------

def test_missing_roundtrip_file_gives_actionable_error(tmp_path, capsys):
    from edakit import cli

    missing = tmp_path / "nope" / "ref.xml"
    code = cli.main(["learn-schema", "--roundtrip-xml", str(missing), "--out", str(tmp_path / "s")])
    out = capsys.readouterr()
    assert code == 2
    text = out.err + out.out
    assert "找不到这个文件" in text
    assert "diag_olb2xml.tcl" in text          # 指向诊断脚本
    assert "Traceback" not in text


def test_missing_file_reports_nearby_xml(tmp_path, capsys):
    from edakit import cli

    (tmp_path / "real.xml").write_text("<Root/>", encoding="utf-8")
    missing = tmp_path / "ref.xml"
    code = cli.main(["learn-schema", "--roundtrip-xml", str(missing), "--out", str(tmp_path / "s")])
    out = capsys.readouterr()
    assert code == 2
    assert "real.xml" in (out.out + out.err)


def test_empty_roundtrip_file_is_rejected(tmp_path, capsys):
    from edakit import cli

    empty = tmp_path / "ref.xml"
    empty.write_bytes(b"")
    code = cli.main(["learn-schema", "--roundtrip-xml", str(empty), "--out", str(tmp_path / "s")])
    out = capsys.readouterr()
    assert code == 2
    assert "空" in (out.out + out.err)


def test_utf16_xml_is_read_correctly(tmp_path, capsys):
    """XMATIC 吐 UTF-16 时也要能读 —— 否则结构清单全是乱码。"""
    from edakit import cli

    xml = '<?xml version="1.0"?><CaptureLibrary><Part Name="REF"/></CaptureLibrary>'
    f = tmp_path / "ref16.xml"
    f.write_bytes(xml.encode("utf-16"))

    code = cli.main(["learn-schema", "--roundtrip-xml", str(f), "--out", str(tmp_path / "s")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "CaptureLibrary" in out
    assert (tmp_path / "s" / "schema-report.txt").exists()

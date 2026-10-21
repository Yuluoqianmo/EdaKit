"""落盘流水线测试 (离线: 用本地样例数据，STEP 下载被打桩)。"""

import json

import pytest
from conftest import DATA

from edakit.bridge.queue import Config
from edakit.easyeda.parse import parse_component
from edakit.pipeline import stage_component


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # STEP 下载改成写一份假文件，避免测试联网
    import edakit.pipeline as pl

    class _FakeStep:
        def download_step(self, uuid, out_path):
            from pathlib import Path

            p = Path(out_path)
            p.write_bytes(b"ISO-10303-21;\nHEADER;\nENDSEC;\n")
            return p

    monkeypatch.setattr(pl, "StepFetcher", _FakeStep)


def _comp(name="C2040"):
    payload = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
    return parse_component(name, payload)


def _cfg(tmp_path):
    cfg = Config()
    cfg.footprint_lib = str(tmp_path / "footprint_lib")
    cfg.project_olb = str(tmp_path / "project.olb")
    return cfg


def test_stage_writes_all_artifacts(tmp_path):
    cfg = _cfg(tmp_path)
    st = stage_component(_comp(), cfg)

    assert st.symbol_xml and st.symbol_xml.exists()
    assert st.footprint_skill and st.footprint_skill.exists()
    assert st.step and st.step.exists()
    assert st.map_xml and st.map_xml.exists()

    # 符号 XML 落在 staging，封装类文件落在封装库
    assert st.symbol_xml.parent.name == "C2040"
    assert st.footprint_skill.parent == (tmp_path / "footprint_lib")
    assert st.footprint_name == "LQFN-56_L7.0-W7.0-P0.4-EP"
    assert st.warnings == []

    # 3D 映射额外出一份 3D Canvas 用的
    assert (tmp_path / "footprint_lib" / (st.footprint_name + ".3dmap.xml")).exists()
    # 人读小抄
    assert (st.workdir / "README.txt").exists()


def test_stage_skill_uses_real_allegro_calls(tmp_path):
    cfg = _cfg(tmp_path)
    st = stage_component(_comp(), cfg)
    il = st.footprint_skill.read_text(encoding="utf-8")
    assert "axlDBCreatePadStack" in il       # 注意大写 S
    assert "axlPadstackCreate" not in il     # 幻觉函数名
    assert "axlSaveDesign" in il


def test_stage_without_step_download(tmp_path):
    cfg = _cfg(tmp_path)
    st = stage_component(_comp(), cfg, download_step=False)
    assert st.step is None
    assert st.map_xml is None                # 没 STEP 就不出映射
    assert st.symbol_xml.exists()            # 其余照常


def test_capture_prepare_preserves_symbol_without_pcb_work(tmp_path, monkeypatch):
    import edakit.pipeline as pl

    cfg = _cfg(tmp_path)
    component = _comp()
    full = stage_component(component, cfg)
    expected = full.symbol_xml.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("Capture placement must not generate PCB or download STEP")

    monkeypatch.setattr(pl, "generate_skill", forbidden)
    monkeypatch.setattr(pl, "StepFetcher", forbidden)
    capture = stage_component(component, cfg, capture_only=True)
    # Generation timestamps may cross a second between the two operations.
    # Compare all actual library content, without relying on wall-clock timing.
    from xml.etree import ElementTree as ET
    def without_timestamps(data):
        root = ET.fromstring(data)
        for element in root.iter():
            element.attrib.pop("timestamp", None)
        return ET.tostring(root)
    assert without_timestamps(capture.symbol_xml.read_bytes()) == without_timestamps(expected)
    assert capture.footprint_name == full.footprint_name
    assert capture.footprint_skill is capture.step is capture.map_xml is None
    assert full.step.exists()  # Existing full export artifacts are retained.


def test_long_model_preserved_as_value_but_package_uses_alias(tmp_path):
    from xml.etree import ElementTree as ET
    component = _comp()
    component.cid = "C5123614"
    component.symbol.name = "HOARG0603-1/10W-5.1KR-0.1%-TCR25"
    staged = stage_component(component, _cfg(tmp_path), capture_only=True)
    xml = ET.parse(staged.symbol_xml).getroot()
    assert xml.find("./Package/Defn").get("name") == staged.part_name
    assert xml.find("./Package/LibPart/Defn").get("CellName") == staged.part_name
    assert xml.find(".//PartValue/Defn").get("name") == component.symbol.name
    assert len(staged.part_name) <= 31


def test_stage_reports_missing_pieces(tmp_path):
    comp = _comp()
    comp.footprint = None
    comp.model3d = None
    st = stage_component(comp, _cfg(tmp_path))
    assert any("PCB 封装" in w for w in st.warnings)
    assert any("3D" in w for w in st.warnings)
    assert st.symbol_xml.exists()


def test_staged_to_dict_is_json_safe(tmp_path):
    st = stage_component(_comp(), _cfg(tmp_path))
    json.dumps(st.to_dict())   # 不抛异常即无 Path 泄漏


def test_symbol_xml_is_capture_lib_dialect(tmp_path):
    """落盘的符号 XML 必须是 Capture 真方言（<Lib>/<Package>），不是早先猜的 <CaptureLibrary>。"""
    cfg = _cfg(tmp_path)
    st = stage_component(_comp(), cfg, download_step=False)
    txt = st.symbol_xml.read_text(encoding="utf-8")

    assert txt.startswith("<?xml"), txt[:80]
    assert "<Lib " in txt and "</Lib>" in txt
    assert "<Package>" in txt
    assert "<SymbolPinScalar>" in txt
    assert "<DefaultValues>" in txt
    # 早先猜的那套不能再出现
    assert "<CaptureLibrary" not in txt
    assert "<Pins>" not in txt

    # Package 名包含版本后缀（必须与 PlacePart 传的名字一致）；
    # 封装名落在 pcbFootprint 属性上
    assert f'name="{st.part_name}"' in txt
    assert st.part_name == "RP2040_P6"
    assert 'pcbFootprint="LQFN-56_L7.0-W7.0-P0.4-EP"' in txt
    assert 'pcbFootprint="LQFN-56_L7.0-W7.0-P0.4-EP"' in txt
    # 57 个引脚
    assert txt.count("<SymbolPinScalar>") == 57


@pytest.mark.parametrize("capture_only", [False, True])
@pytest.mark.parametrize("cid", ["C2040", "C25804", "C2337", "C19110"])
def test_staging_and_library_merge_keep_component_properties(tmp_path, capture_only, cid):
    from xml.etree import ElementTree as ET
    from edakit.symbol.olb import merge_olb_xml
    from edakit.symbol.naming import capture_part_name

    component = _comp(cid)
    staged = stage_component(component, _cfg(tmp_path), capture_only=capture_only, download_step=False)
    assert staged.part_name.endswith("_P6")
    assert staged.part_name != capture_part_name(component.symbol.name, cid, revision="P3")
    assert staged.part_name != capture_part_name(component.symbol.name, cid)
    assert staged.part_name != capture_part_name(component.symbol.name, cid, revision="G2")
    assert len(staged.part_name.encode("utf-8")) <= 31
    generated = staged.symbol_xml.read_text(encoding="utf-8")
    old = stage_component(_comp("C170151"), _cfg(tmp_path), capture_only=capture_only, download_step=False)
    merged = merge_olb_xml(old.symbol_xml.read_text(encoding="utf-8"), generated)
    # A second merge replaces the same package and retains the exact metadata.
    merged = merge_olb_xml(merged, generated)
    packages = [p for p in ET.fromstring(merged).findall("Package") if p.find("Defn").get("name") == staged.part_name]
    assert len(packages) == 1
    assert {p.get("name"): p.get("val") for p in packages[0].findall("LibPart/NormalView/SymbolUserProp/Defn")} == {
        "Description": component.symbol.description,
        "PCBFootprint": component.footprint.name,
        "Manufacturer": component.symbol.manufacturer,
        "Manufacturer_PN": component.symbol.mpn,
    }

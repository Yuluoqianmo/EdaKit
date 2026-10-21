"""物理引脚配对门槛：真实样本、错误编号、名称及流水线输出边界。"""
import json
from copy import deepcopy

import pytest
from conftest import DATA

from edakit.config import Config
from edakit.easyeda.model import Footprint, Pad, Pin, Primitive, Symbol
from edakit.easyeda.parse import parse_component
from edakit.errors import PinMappingError
from edakit.footprint.padstack import merge_padstacks
from edakit.footprint.validation import validate_pin_mapping
from edakit.pipeline import stage_component


def pair():
    sym = Symbol(name="test", pins=[Pin(number="1", name="GND"), Pin(number="A2", name="GPIO")])
    fp = Footprint(name="test", pads=[Pad(number="1", layers=["TOP"]), Pad(number="A2", layers=["TOP"])])
    fp.padstacks = merge_padstacks(fp.pads)
    return sym, fp


@pytest.mark.parametrize("cid", ["C2040", "C2337", "C25804", "C23630", "C170151", "C19110"])
def test_real_components_match(cid):
    comp = parse_component(cid, json.loads((DATA / f"{cid}.json").read_text(encoding="utf-8")))
    report = validate_pin_mapping(comp.symbol, comp.footprint)
    assert report["pin_count"] == len(comp.symbol.pins)
    assert report["pin_numbers_matched"]
    assert not report["independent_pad_names_checked"]
    assert report["pins"][0]["symbol_name"] == comp.symbol.pins[0].name


@pytest.mark.parametrize("number", ["a2", "02", "3", "", " A2", "A 2"])
def test_wrong_missing_or_case_changed_pad_number(number):
    sym, fp = pair()
    fp.pads[1].number = number
    fp.padstacks = merge_padstacks(fp.pads)
    with pytest.raises(PinMappingError):
        validate_pin_mapping(sym, fp)


def test_extra_pin_and_duplicate_symbol():
    sym, fp = pair()
    sym.pins.append(Pin(number="3"))
    with pytest.raises(PinMappingError, match="PCB 缺少.*3"):
        validate_pin_mapping(sym, fp)
    sym.pins[-1].number = "1"
    with pytest.raises(PinMappingError, match="原理图存在重复"):
        validate_pin_mapping(sym, fp)


def test_extra_pad():
    sym, fp = pair()
    fp.pads.append(Pad(number="EP", layers=["TOP"]))
    fp.padstacks = merge_padstacks(fp.pads)
    with pytest.raises(PinMappingError, match="PCB 多出.*EP"):
        validate_pin_mapping(sym, fp)


def test_same_layer_duplicate_rejected_but_cross_layer_merged():
    sym, fp = pair()
    extra = deepcopy(fp.pads[0])
    fp.pads.append(extra)
    fp.padstacks = merge_padstacks(fp.pads)
    with pytest.raises(PinMappingError, match="同层重复"):
        validate_pin_mapping(sym, fp)
    extra.layers = ["BOTTOM"]
    fp.padstacks = merge_padstacks(fp.pads)
    assert validate_pin_mapping(sym, fp)["pin_count"] == 2


def test_independent_names_checked_when_available():
    sym, fp = pair()
    for pin, pad in zip(sym.pins, fp.pads):
        pad.name = pin.name
    assert validate_pin_mapping(sym, fp)["independent_pad_names_checked"]
    fp.pads[0].name = "gnd"
    with pytest.raises(PinMappingError, match="名称不一致"):
        validate_pin_mapping(sym, fp)


def test_mechanical_hole_not_an_electrical_pin_and_blank_pad_not_guessed():
    sym, fp = pair()
    fp.primitives.append(Primitive(kind="HOLE"))
    assert validate_pin_mapping(sym, fp)["pin_count"] == 2
    fp.pads.append(Pad(number="", layers=["TOP"], hole_mm=1))
    fp.padstacks = merge_padstacks(fp.pads)
    with pytest.raises(PinMappingError, match="PCB 焊盘"):
        validate_pin_mapping(sym, fp)


def test_stale_padstacks_rejected():
    sym, fp = pair()
    fp.padstacks[0].name = "wrong"
    with pytest.raises(PinMappingError, match="Padstack 不一致"):
        validate_pin_mapping(sym, fp)


@pytest.mark.parametrize("capture_only", [True, False])
def test_pipeline_rejects_before_writing_pair(tmp_path, monkeypatch, capture_only):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "app"))
    comp = parse_component("C2040", json.loads((DATA / "C2040.json").read_text(encoding="utf-8")))
    cfg = Config()
    cfg.footprint_lib = str(tmp_path / "lib")
    cfg.project_olb = str(tmp_path / "test.olb")
    # 模拟已经有可复用的成功准备结果，错误数据不得绕过校验。
    good = stage_component(comp, cfg, capture_only=True, output_dir=tmp_path / "export")
    original = good.symbol_xml.read_bytes()
    report = json.loads(good.pin_map.read_text(encoding="utf-8"))
    assert report["pin_count"] == 57
    comp.symbol.pins[0].number = "missing"
    with pytest.raises(PinMappingError):
        stage_component(comp, cfg, capture_only=capture_only, output_dir=tmp_path / "export")
    assert good.symbol_xml.read_bytes() == original
    assert not list(tmp_path.rglob("*.il"))

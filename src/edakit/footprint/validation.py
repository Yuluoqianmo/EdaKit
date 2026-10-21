"""Capture pin number ↔ Allegro package pin number 的生成前门槛。"""

from collections import Counter

from ..easyeda.model import Footprint, Symbol
from ..errors import PinMappingError
from .padstack import merge_padstacks


def _number(value: str, source: str) -> str:
    if not value or value != value.strip() or any(c.isspace() or ord(c) < 32 for c in value):
        raise PinMappingError(f"{source}存在空白或无效引脚编号: {value!r}")
    return value


def validate_pin_mapping(symbol: Symbol, footprint: Footprint) -> dict:
    """保留精确编号及功能名，不做大小写转换、自动补号或去零。"""
    pins = [_number(pin.number, "原理图") for pin in symbol.pins]
    if not pins:
        raise PinMappingError("原理图没有可匹配的引脚。")
    duplicates = sorted(n for n, count in Counter(pins).items() if count > 1)
    if duplicates:
        raise PinMappingError(f"原理图存在重复引脚编号: {duplicates}")

    # 跨层铜形可合并；同层重复编号不能借合并静默消失。
    records = []
    for pad in footprint.pads:
        number = _number(pad.number, "PCB 焊盘")
        for layer in pad.layers or ["TOP"]:
            records.append((number, layer))
    duplicate_pads = sorted(str(key) for key, count in Counter(records).items() if count > 1)
    if duplicate_pads:
        raise PinMappingError(f"PCB 存在同层重复焊盘编号: {duplicate_pads}")
    # 重新计算，避免调用者修改 pads 后使用过期的 padstacks 输出错误编号。
    merged = merge_padstacks(footprint.pads)
    expected = {ps.name for ps in merged}
    actual = [ps.name for ps in footprint.padstacks]
    if len(actual) != len(set(actual)) or set(actual) != expected or merged != footprint.padstacks:
        raise PinMappingError("PCB 原始焊盘与合并后的 Padstack 不一致，请重新解析。")
    missing, extra = sorted(set(pins) - expected), sorted(expected - set(pins))
    if missing or extra:
        raise PinMappingError(f"引脚编号不一致（区分大小写）: PCB 缺少 {missing}; PCB 多出 {extra}")

    names = {pin.number: pin.name for pin in symbol.pins}
    for pad in footprint.pads:
        if pad.name and pad.name != names[pad.number]:
            raise PinMappingError(
                f"引脚 {pad.number} 名称不一致: 原理图 {names[pad.number]!r}, PCB {pad.name!r}"
            )
    independent_names = bool(footprint.pads) and all(pad.name for pad in footprint.pads)
    return {
        "schema_version": 1,
        "symbol": symbol.name,
        "footprint": footprint.name,
        "pin_count": len(pins),
        "pin_numbers_matched": True,
        "independent_pad_names_checked": independent_names,
        "name_status": "matched" if independent_names else "symbol_name_mapping_only",
        "pins": [
            {"number": pin.number, "symbol_name": pin.name, "mapped_pad_name": pin.name}
            for pin in symbol.pins
        ],
    }

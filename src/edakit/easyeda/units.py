"""单位换算。

EasyEDA 有两套画布:
  * 符号 (schematic symbol): 画布虚拟单位。转 mm 用 (ee - bbox) * 10 * 0.0254，Y 取反。
  * 封装 (footprint): 1 单位 = 10 mil = 0.254 mm。

全部内部统一到 mm。mil 与 inch 仅作为便利函数保留。
"""

from __future__ import annotations

MIL_TO_MM = 0.0254
FOOTPRINT_UNIT_TO_MM = 10 * MIL_TO_MM  # = 0.254 mm，即 10 mil

# 符号画布单位 → mm 的系数 (经验值，来自 easyeda2kicad / KiCad 导入格式文档)。
SYMBOL_UNIT_TO_MM = 10 * MIL_TO_MM  # = 0.254 mm


def mil_to_mm(mil: float) -> float:
    return mil * MIL_TO_MM


def mm_to_mil(mm: float) -> float:
    return mm / MIL_TO_MM


def footprint_units_to_mm(units: float) -> float:
    """封装画布单位 → mm。"""
    return units * FOOTPRINT_UNIT_TO_MM


def mm_to_footprint_units(mm: float) -> float:
    """mm → 封装画布单位。"""
    return mm / FOOTPRINT_UNIT_TO_MM


def symbol_units_to_mm(units: float, *, flip_y: bool = False) -> float:
    """符号画布单位 → mm。flip_y 用于把 EasyEDA 的 Y 轴翻到 EDA 常规方向。"""
    mm = units * SYMBOL_UNIT_TO_MM
    return -mm if flip_y else mm


def snap_mm(value: float, grid_mil: float = 10.0) -> float:
    """把 mm 吸附到给定 mil 网格。

    Capture 符号受 10 mil 网格限制；生成时用它避免落到网格外的坐标。
    """
    step = mil_to_mm(grid_mil)
    if step <= 0:
        return value
    return round(value / step) * step

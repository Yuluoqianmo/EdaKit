from edakit.easyeda import units


def test_footprint_unit():
    # 1 封装单位 = 10 mil = 0.254 mm
    assert abs(units.footprint_units_to_mm(1) - 0.254) < 1e-9
    assert abs(units.footprint_units_to_mm(100) - 25.4) < 1e-9


def test_roundtrip():
    for v in (0.0, 1.27, 15.7, 100.0):
        assert abs(units.mm_to_footprint_units(units.footprint_units_to_mm(v)) - v) < 1e-9


def test_symbol_flip_y():
    assert units.symbol_units_to_mm(10, flip_y=True) == -units.symbol_units_to_mm(10)


def test_snap_grid():
    # 吸附到 10 mil (0.254 mm) 网格
    assert units.snap_mm(0.30, 10) == units.mil_to_mm(10) * round(0.30 / units.mil_to_mm(10))

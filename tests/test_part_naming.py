import pytest
from edakit.symbol.naming import capture_part_name


@pytest.mark.parametrize("name", ["RP2040", "RC0603FR-074K7L", "MF1/2W-4.7KΩ±1% T52", "A" * 31])
def test_working_names_unchanged(name):
    assert capture_part_name(name, "C2040") == name


def test_32_character_model_gets_unique_bounded_identifier():
    name = "HOARG0603-1/10W-5.1KR-0.1%-TCR25"
    assert len(name) == 32
    alias = capture_part_name(name, "C5123614")
    assert alias.isascii() and len(alias) <= 31
    assert alias.endswith("_C5123614")
    assert "/" not in alias and "%" not in alias
    assert alias == capture_part_name(name, "C5123614")
    assert alias != capture_part_name(name, "C5123615")


def test_long_unicode_and_unusual_ids_are_bounded():
    alias = capture_part_name("电阻" * 40, "nonstandard" * 20)
    assert alias.isascii() and len(alias) <= 31

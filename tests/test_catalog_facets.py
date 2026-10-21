"""Attribute filters must affect upstream queries, including pages and value parsing."""
import pytest

from edakit.catalog.api import MallClient
from edakit.catalog.facets import clean_params, normalize_facets


def test_facets_keep_raw_keys_brand_ids_and_all_options():
    raw = {"Package": [{"name": "0603"}, {"name": "0402"}, {"name": "0603"}, {"name": "-"}],
           "Manufacturer": [{"id": "99", "name": "UNI-ROYAL"}],
           "paramNameValueMap": {"Resistance": {"paramDetailList": [{"name": "4.7kΩ"}]},
                                 "Tolerance": {"paramDetailList": [{"name": "±1%"}]},
                                 "Future Field": {"paramDetailList": [{"name": "raw-value"}]}}}
    by_key = {f["key"]: f for f in normalize_facets(raw)}
    assert by_key["Resistance"]["label"] == "阻值"
    assert by_key["Resistance"]["values"] == [{"value": "4.7kΩ", "label": "4.7kΩ"}]
    assert by_key["Manufacturer"]["values"][0]["value"] == "99"
    assert [v["value"] for v in by_key["Package"]["values"]] == ["0402", "0603"]
    assert by_key["Future Field"]["label"] == "Future Field"
    assert by_key["Future Field"]["translated"] is False


def test_facet_universe_preserves_value_parser_and_does_not_self_filter(monkeypatch):
    def post(self, path, body):
        assert path.endswith("/param/group")
        assert body["keyword"] == ""
        assert body["paramNameValueMap"] == {"Resistance": ["4.7kΩ"]}
        assert body["encapValueList"] == []
        return {"totalCount": 465, "Package": [{"name": "0603"}, {"name": "0805"}]}
    monkeypatch.setattr(MallClient, "_post", post)
    result = MallClient().facet_options([1199], "4K7")
    assert result["total"] == 465 and result["scope"] == "category-keyword"
    assert len(result["facets"][0]["values"]) == 2


def test_filters_are_combined_and_preserved_on_second_page(monkeypatch):
    def post(self, path, body):
        assert body["keyword"] == ""
        assert body["currentPage"] == 2
        assert body["catalogIdList"] == [1199]
        assert body["paramNameValueMap"] == {"Resistance": ["4.7kΩ"], "Tolerance": ["±1%", "±5%"]}
        assert body["encapValueList"] == ["0603", "0805"]
        assert body["brandIdList"] == [99, 396]
        return {}
    monkeypatch.setattr(MallClient, "_post", post)
    MallClient().search_keyword("4.7K", catalog_ids=[1199], page=2,
                               params={"Tolerance": ["±1%", "±5%"]},
                               packages=["0603", "0805"], brand_ids=["99", "396"])


def test_value_conflict_is_explicit_instead_of_silently_overriding():
    with pytest.raises(ValueError, match="冲突"):
        MallClient().search_keyword("4.7K", catalog_ids=[1199], params={"Resistance": ["10kΩ"]})


def test_zero_keyword_accepts_explicit_equivalent_label(monkeypatch):
    def post(self, path, body):
        assert body["keyword"] == ""
        assert body["paramNameValueMap"] == {"Resistance": ["0mΩ"]}
        return {}
    monkeypatch.setattr(MallClient, "_post", post)
    MallClient().search_keyword("0R", catalog_ids=[1199], params={"Resistance": ["0mΩ"]})


def test_browse_forwards_attributes_without_literal_keyword(monkeypatch):
    def post(self, path, body):
        assert body["keyword"] == ""
        assert body["paramNameValueMap"] == {"Capacitance": ["100nF"], "Voltage Rating": ["50V"]}
        assert body["encapValueList"] == ["0603"]
        return {}
    monkeypatch.setattr(MallClient, "_post", post)
    MallClient().browse_category(1142, packages=["0603"],
                                params={"Capacitance": ["100nF"], "Voltage Rating": ["50V"]})


@pytest.mark.parametrize("params", [{"x": "not-a-list"}, {"x": [1]}, {"x": [""]},
                                    {"x": ["a"] * 51}, {"x" * 121: ["a"]}])
def test_invalid_filter_shape_rejected(params):
    with pytest.raises(ValueError):
        clean_params(params)


def test_no_filter_and_duplicate_filter_values():
    assert clean_params(None) == {}
    assert clean_params({"Tolerance": ["±1%", "±1%"]}) == {"Tolerance": ["±1%"]}

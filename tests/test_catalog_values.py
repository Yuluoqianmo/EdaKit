"""Regression: passive values must filter attributes, not model substrings."""
import pytest

from edakit.catalog.api import MallClient
from edakit.catalog.values import passive_value


@pytest.mark.parametrize('keyword,ids,expected', [
    ('4.7K', [1199], ('Resistance', '4.7kΩ')),
    ('4.7K', [1198, 1199, 1200, 1201, 1202, 1203, 1336], ('Resistance', '4.7kΩ')),
    ('4k7', [1199], ('Resistance', '4.7kΩ')),
    ('4700Ω', [1199], ('Resistance', '4.7kΩ')),
    ('4.7 kohm', [1199], ('Resistance', '4.7kΩ')),
    ('4.7K欧姆', [1199], ('Resistance', '4.7kΩ')),
    ('2R2', [1199, 1203], ('Resistance', '2.2Ω')),
    ('0R', [1199], ('Resistance', '0Ω')),
    ('1M', [1199], ('Resistance', '1MΩ')),
    ('1mΩ', [1199], ('Resistance', '1mΩ')),
    ('0.1Ω', [1199], ('Resistance', '100mΩ')),
    ('100nF', [1142], ('Capacitance', '100nF')),
    ('0.1uF', [1142], ('Capacitance', '100nF')),
    ('.1 μF', [1142], ('Capacitance', '100nF')),
    ('100000pF', [1142], ('Capacitance', '100nF')),
    ('4u7', [1142], ('Capacitance', '4.7uF')),
    ('4.7UH', [1181], ('Inductance', '4.7uH')),
    ('4700nH', [1181], ('Inductance', '4.7uH')),
    ('0.0047mH', [1181], ('Inductance', '4.7uH')),
    ('4.7kΩ', [], ('Resistance', '4.7kΩ')),
    ('0.1uF', [], ('Capacitance', '100nF')),
])
def test_value_aliases(keyword, ids, expected):
    assert passive_value(keyword, ids) == expected


@pytest.mark.parametrize('keyword,ids', [
    ('RP2040', [941]), ('C25804', [1199]), ('0603', [1199]),
    ('4700', [1199]), ('104', [1142]), ('4.7K 1%', [1199]),
    ('RC0603FR-074K7L', [1199]), ('4.7K', []), ('4K7', [941]),
    ('4.7kΩ', [941]), ('100nF', [1199]), ('4.7K', [1199, 941]),
    ('1MHz', [1199]), ('-4.7K', [1199]), ('NaNΩ', [1199]),
    ('1e6Ω', [1199]), ('', [1199]), ('9'*100+'K', [1199]),
])
def test_ambiguous_or_mixed_text_stays_literal(keyword, ids):
    assert passive_value(keyword, ids) is None


@pytest.mark.parametrize('keyword,ids,param,label', [
    ('4.7K', [1199], 'Resistance', '4.7kΩ'),
    ('4K7', [1199], 'Resistance', '4.7kΩ'),
    ('4700Ω', [1199], 'Resistance', '4.7kΩ'),
    ('0.1uF', [1142], 'Capacitance', '100nF'),
    ('4700nH', [1181], 'Inductance', '4.7uH'),
])
def test_product_and_facet_use_the_same_exact_value(monkeypatch, keyword, ids, param, label):
    calls = []
    def post(self, path, body):
        calls.append((path, body))
        if path.endswith('/param/group'):
            return {'Package': [{'name': '0603'}], 'totalCount': 465}
        return {'dataList': [], 'totalRow': 465}
    monkeypatch.setattr(MallClient, '_post', post)
    client = MallClient()
    assert '0603' in client.package_options(ids, keyword)['packages']
    client.search_keyword(keyword, catalog_ids=ids, package='0603', page=2)
    for _, body in calls:
        assert body['keyword'] == ''
        assert body['paramNameValueMap'] == {param: [label]}
        assert body['catalogIdList'] == ids
    assert calls[1][1]['encapValueList'] == ['0603']
    assert calls[1][1]['currentPage'] == 2


def test_normal_model_query_does_not_gain_a_value_filter(monkeypatch):
    def post(self, path, body):
        assert body['keyword'] == 'RC0603FR-074K7L'
        assert 'paramNameValueMap' not in body
        return {}
    monkeypatch.setattr(MallClient, '_post', post)
    MallClient().search_keyword('RC0603FR-074K7L', catalog_id=1199)


@pytest.mark.parametrize('keyword,param,label,leaf', [
    ('4.7kΩ', 'Resistance', '4.7kΩ', 1199),
    ('0.1uF', 'Capacitance', '100nF', 1142),
    ('4700nH', 'Inductance', '4.7uH', 1181),
])
def test_explicit_unit_without_category_supplies_leaf_ids(monkeypatch, keyword, param, label, leaf):
    calls = []
    def post(self, path, body):
        assert not path.endswith('/global')
        assert leaf in body['catalogIdList']
        assert not {501, 495, 498}.intersection(body['catalogIdList'])
        assert body['keyword'] == ''
        assert body['paramNameValueMap'] == {param: [label]}
        calls.append(body)
        return {}
    monkeypatch.setattr(MallClient, '_post', post)
    client = MallClient()
    client.package_options([], keyword)
    client.search_keyword(keyword)
    assert calls[0]['catalogIdList'] == calls[1]['catalogIdList']


def test_zero_resistor_includes_equivalent_upstream_labels(monkeypatch):
    def post(self, path, body):
        assert body['paramNameValueMap'] == {'Resistance': ['0Ω', '0mΩ']}
        return {}
    monkeypatch.setattr(MallClient, '_post', post)
    MallClient().package_options([1199], '0R')
    MallClient().search_keyword('0Ω', catalog_id=1199)

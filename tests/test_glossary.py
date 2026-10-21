"""Localization must preserve filter identity and distinguish circuit semantics."""
from copy import deepcopy

from edakit.catalog.api import MallClient
from edakit.catalog.facets import normalize_facets
from edakit.catalog.glossary import display_params, parameter_display, value_label
from edakit.catalog.models import CategoryNode, Part
from edakit.server.app import _part_dict


def test_translated_choices_still_submit_original_keys_and_values(monkeypatch):
    raw = {'paramNameValueMap': {
        'Output Type': {'paramDetailList': [{'name': 'Adjustable'}, {'name': 'Fixed'}]},
        'Driven Configuration': {'paramDetailList': [{'name': 'High Side'}]}}}
    before = deepcopy(raw)
    fields = {f['key']: f for f in normalize_facets(raw, [1007])}
    assert raw == before
    assert fields['Output Type']['label'] == '输出电压类型'
    assert fields['Output Type']['values'][0] == {'value': 'Adjustable', 'label': '可调'}
    chosen = {key: [f['values'][0]['value']] for key, f in fields.items()}

    def post(self, path, body):
        assert body['catalogIdList'] == [1007]
        assert body['paramNameValueMap'] == {
            'Output Type': ['Adjustable'], 'Driven Configuration': ['High Side']}
        return {}

    monkeypatch.setattr(MallClient, '_post', post)
    MallClient().browse_category(1007, params=chosen)


def test_output_type_uses_observed_semantics_and_mixed_scope_falls_back():
    assert parameter_display('Output Type', ['Fixed'])['label'] == '输出电压类型'
    assert parameter_display('Output Type', ['Open-drain', 'CMOS', 'Tri-State'])['label'] == '输出形式'
    assert parameter_display('Output Type', ['Fixed', 'Open-drain'])['label'] == '输出类型'


def test_passive_tolerance_context_does_not_cross_categories():
    assert parameter_display('Tolerance', ['±1%'], [1199])['label'] == '阻值精度'
    assert parameter_display('Tolerance', ['±10%'], [1142])['label'] == '容量偏差'
    assert parameter_display('Tolerance', ['±20%'], [1181])['label'] == '感量偏差'
    assert parameter_display('Tolerance', ['±1%'], [1199, 1142])['label'] == '精度'


def test_dielectric_codes_and_resistor_tcr_have_different_names():
    assert parameter_display('Temperature Coefficient', ['X7R', 'C0G'], [1142])['label'] == '介质/温度特性'
    assert parameter_display('Temperature Coefficient', ['±100ppm/℃'], [1199])['label'] == '温度系数（TCR）'


def test_logic_channel_direction_is_not_mosfet_polarity():
    assert parameter_display('Channel Type', ['Bidirectional'])['label'] == '通道方向'
    assert parameter_display('Channel Type', ['N-Channel'])['label'] == '通道类型'
    assert value_label('Channel Type', 'Bidirectional') == '双向'
    assert value_label('FET Type', 'N-Channel') == 'N 沟道'


def test_upstream_unit_mismatch_is_visible_and_is_not_rewritten():
    row = display_params({'Resolution (Bits)': '32kHz~192kHz'}, 255)[0]
    assert row['needsReview'] and '单位与字段不符' in row['note']
    assert row['value'] == row['displayValue'] == '32kHz~192kHz'
    assert not parameter_display('Resolution (Bits)', ['12', '16'])['needsReview']


def test_uncertain_definitions_keep_symbols_and_review_notes():
    for key in ('Con', 'Drain Current (Idss)', 'Photoperceptivity'):
        row = parameter_display(key, ['1'])
        assert row['needsReview'] and row['note']
    assert 'Idss' in parameter_display('Drain Current (Idss)')['label']


def test_enum_translation_is_field_scoped_and_whole_value_only():
    assert value_label('Driven Configuration', 'High Side') == '高侧'
    assert value_label('Package', 'High Side') == 'High Side'
    assert value_label('Manufacturer', 'Fixed') == 'Fixed'
    assert value_label('Function', 'Buck-Boost') == '升降压'
    assert value_label('Function', 'Buck model X') == 'Buck model X'
    assert value_label('Dimming', 'PWM') == 'PWM 调光'


def test_aliases_share_labels_without_collapsing_wire_identity():
    params = {'Output Current': '1A', 'Output current': '2A',
              'High-side\u00a0Bias\u00a0Voltage(Vbs)': '80V', 'Future Field': 'new-value'}
    rows = display_params(params)
    assert [r['key'] for r in rows] == list(params)
    assert rows[0]['label'] == rows[1]['label'] == '输出电流'
    assert rows[2]['label'] == '高侧偏置电压（Vbs）'
    assert rows[3]['label'] == 'Future Field' and not rows[3]['translated']


def test_product_display_keeps_raw_parameters_model_and_package():
    params = {'Dimming': 'PWM', 'Output Type': 'Fixed'}
    part = Part(cid='C13755', model='LM5116', package='HTSSOP-20-EP', catalog_id=1007, params=params)
    result = _part_dict(part)
    assert result['params'] == params
    assert result['model'] == 'LM5116' and result['package'] == 'HTSSOP-20-EP'
    assert result['paramDisplay'][0]['displayValue'] == 'PWM 调光'
    assert result['paramDisplay'][1]['label'] == '输出电压类型'


def test_category_translation_preserves_id_and_hierarchy():
    node = CategoryNode(261, 'Logic', children=[CategoryNode(999, 'Gates and Inverters')])
    result = node.to_dict()
    assert result['id'] == 261 and result['children'][0]['id'] == 999
    assert result['children'][0]['name'] == '逻辑门与反相器'
    assert result['children'][0]['originalName'] == 'Gates and Inverters'
    assert CategoryNode(1383, 'AC DC Converters (Off-Board)').to_dict()['name'] == '非板载 AC-DC 电源'


def test_timing_and_current_directions_remain_distinct():
    assert '高到低' in parameter_display('Propagation Delay tpHL')['label']
    assert '低到高' in parameter_display('Propagation Delay tpLH')['label']
    assert parameter_display('Peak Output Current(Source)')['label'] == '峰值拉电流'
    assert parameter_display('Peak Output Current(Sink)')['label'] == '峰值灌电流'
    assert value_label('Current - Output High(IOH)', '-6mA') == '-6mA'

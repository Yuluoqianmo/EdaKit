from edakit.ibom import manufacturing as m


def field(label, value='', spec=None):
    return dict(sheet='PCB说明', label=label, value=value, spec=spec or {})


def test_order_choices_follow_verified_layer_conditions():
    assert '3.2 mm' in dict(m.schema('厚度', 2))['成品板厚']
    assert '3.2 mm' not in dict(m.schema('厚度', 6))['成品板厚']
    assert '1.5 oz' in dict(m.schema('铜箔厚度', 6))['外层']
    assert '内层' not in dict(m.schema('铜箔厚度', 2))
    assert '有铅喷锡' not in dict(m.schema('表面处理', 6))['工艺']
    assert dict(m.schema('厚度', 10))['成品板厚'] == ()
    assert '3.0 mm' in dict(m.schema('厚度', 4))['成品板厚']
    assert '过孔盖油' not in dict(m.schema('阻焊要求', 4))['过孔']
    assert dict(m.schema('厚度', 2, 'FPC软板'))['成品板厚'] == ()
    assert '有铅喷锡' not in dict(m.schema('表面处理', 2, thickness='0.4 mm'))['工艺']


def test_switching_layers_exposes_incompatible_choices_without_replacing_them():
    fields = [field('PCB层数', '6'), field('表面处理', '有铅喷锡'),
              field('铜箔厚度', spec={'外层': '6 oz'}), field('厚度', spec={'成品板厚': '3.2 mm'})]
    assert len(m.validate(fields)) == 3
    assert fields[1]['value'] == '有铅喷锡'
    assert m.validate([field('PCB层数', '2'), field('铜箔厚度', spec={'内层': '1 oz'})])


def test_compound_order_fields_roundtrip_and_preserve_legacy_text():
    parts = {'外层': '1 oz', '内层': '0.5 oz', '补充要求': '特殊公差'}
    value = m.compose('铜箔厚度', parts)
    assert m.restore('铜箔厚度', value, parts) == parts
    assert m.restore('铜箔厚度', 'TOP: 30.48 μm') == {'补充要求': 'TOP: 30.48 μm'}
    assert m.restore('铜箔厚度', '手工新要求', parts) == {'补充要求': '手工新要求'}
    assert m.compose('厚度', {'成品板厚': '1.6 mm'}) == '1.6 mm'


def test_thin_board_and_impedance_conflicts():
    assert m.validate([field('表面处理', '无铅喷锡'), field('厚度', spec={'成品板厚': '0.4 mm'})])
    assert m.validate([field('阻抗控制', spec={'管控': '无要求', '公差': '±20%'})])
    assert not m.validate([field('PCB层数', '6'), field('表面处理', '沉金'), field('厚度', spec={'成品板厚': '1.6 mm'})])

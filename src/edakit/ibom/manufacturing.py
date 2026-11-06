"""Order choices, separate from PCB facts. Sources: docs/嘉立创下单参数分析-20261104.md."""
import re
from .stencil import CATALOGUE

REFERENCE_ONLY = {'厚度', '铜箔厚度', '板材'}
MASK = ('绿色', '红色', '黄色', '蓝色', '白色', '哑黑色', '嘉立创紫')
FINISH = ('无铅OSP', '有铅喷锡', '无铅喷锡', '沉金')
VIA = ('按Gerber文件', '过孔盖油', '过孔开窗', '过孔塞油', '过孔塞树脂+电镀盖帽', '过孔塞铜浆+电镀盖帽')
DELETED = {'设计人员电话', '其他'}
REMOVED = {'丝印要求', '金手指', '阻抗控制'} | DELETED
STENCIL_SIZES = tuple(spec.value for spec in CATALOGUE)

MATERIALS = ('FR-4', 'FPC软板', '铝基板', '铜基板', '高频板', '其他板材')
MATERIAL_FIELDS = {
    'FR-4': (('TG要求', 'TG 值要求（手工填写）'),),
    'FPC软板': (('基材/型号', '基材 / 型号'), ('基材结构要求', '基材结构要求')),
    '铝基板': (('导热系数要求', '导热系数要求（W/m·K）'), ('型号/绝缘要求', '板材型号 / 其他要求')),
    '铜基板': (('结构/型号要求', '结构 / 型号要求'), ('热设计要求', '其他热设计要求')),
    '高频板': (('品牌/型号', '品牌 / 板材型号'), ('介电要求', '介电 / 其他要求')),
    '其他板材': (('板材名称/型号', '板材名称 / 型号'), ('规格要求', '规格要求')),
}
MATERIAL_NOTES = {
    'FR-4': '如需指定品牌、型号，可填写补充要求。',
    'FPC软板': '按柔性板基材与结构描述要求，不沿用 FR-4 的 TG 输入。',
    '铝基板': '导热要求对应导热绝缘层；具体可生产规格需由板厂确认。',
    '铜基板': '按实际结构描述热设计或绝缘要求。',
    '高频板': '优先指定准确型号；PTFE 等材质要求可写入补充说明。',
    '其他板材': '以明确的材料名称和规格说明交付要求。',
}

# Initial order selections explicitly requested in the user's screenshots.
# PCB facts and unspecified requirements (including TG) are not defaults.
DEFAULT_PARTS = {
    '板材': {'类别': 'FR-4'},
    '厚度': {'成品板厚': '1.6 mm'},
    '铜箔厚度': {'外层': '1 oz'},
    '表面处理': {'工艺': '沉金'},
    '阻焊要求': {'颜色': '绿色', '过孔': '过孔盖油'},
}
STENCIL_DEFAULTS = {
    '数量': '1', '钢网用途': '锡膏网', 'MARK点': '不需要',
    '抛光工艺': '打磨抛光', '工程处理要求': '按《钢网制作规范及协议》进行制作',
    '打印钢网型号（字符）到钢片上': '需要',
}


def default_value(sheet, label):
    if sheet == 'PCB说明' and label in DEFAULT_PARTS:
        return compose(label, DEFAULT_PARTS[label])
    return STENCIL_DEFAULTS.get(label, '') if sheet == '钢网' else ''


def material_models(layers):
    common = ('不指定（真A级）随机品牌 TG135', 'KB6164（有水印）TG135', 'KB-6165F TG155', '南亚 NP-140F（有水印）TG140')
    if layers == 2:
        return common
    return ('不指定 TG135', '不指定 TG155', 'KB-6165F（无水印）TG155', '南亚 NP-140F（无水印）TG140', '南亚 NP-155F TG155') + (('生益 S1000-2M TG170',) if layers and layers >= 6 else ())


def layer_count(value):
    match = re.fullmatch(r'\s*(\d+)\s*(?:层)?\s*', str(value))
    return int(match[1]) if match else None


def schema(label, layers=None, board_type='', thickness=''):
    """Empty choice lists denote free text; unknown combinations stay custom."""
    fr4 = not board_type or board_type == 'FR-4'
    if label == '厚度':
        sizes = {2: ('0.4', '0.6', '0.8', '1.0', '1.2', '1.6', '2.0', '2.5', '3.2'),
                 4: ('0.6', '0.8', '1.0', '1.2', '1.6', '2.0', '2.5', '3.0'),
                 6: ('0.6', '0.8', '1.0', '1.2', '1.6', '1.8', '2.0', '2.5', '3.0')}.get(layers, ()) if fr4 else ()
        return [('成品板厚', tuple(x+' mm' for x in sizes))]
    if label == '铜箔厚度':
        outer = {2: ('1', '2', '2.5', '3.5', '4.5', '5', '6'), 6: ('1', '1.5', '2')}.get(layers, ('1', '2') if layers and layers >= 4 else ()) if fr4 else ()
        result = [('外层', tuple(x+' oz' for x in outer))]
        if layers is None or layers > 2:
            result.append(('内层', ('0.5 oz', '1 oz', '2 oz') if fr4 else ()))
        return result
    try:
        thin = float(thickness.removesuffix(' mm')) <= .4
    except ValueError:
        thin = False
    via = {2: ('按Gerber文件', '过孔盖油', '过孔开窗', '过孔塞油', '过孔塞树脂+电镀盖帽'),
           4: ('按Gerber文件', '过孔开窗', '过孔塞油', '过孔塞树脂+电镀盖帽', '过孔塞铜浆+电镀盖帽'),
           6: ('按Gerber文件', '过孔塞树脂+电镀盖帽', '过孔塞铜浆+电镀盖帽', '过孔塞树脂+过孔开窗')}.get(layers, ('按Gerber文件',)) if fr4 else ('按Gerber文件',)
    return {
        '板材': [('类别', MATERIALS)] + [(key, ()) for key, _ in MATERIAL_FIELDS.get(board_type or 'FR-4', MATERIAL_FIELDS['其他板材'])],
        '表面处理': [('工艺', (('无铅OSP', '沉金') if thin or layers is not None and layers >= 6 else FINISH) if fr4 else ())],
        '阻焊要求': [('颜色', MASK if fr4 else ()), ('过孔', via)],
        '丝印要求': [('颜色', ('白色', '深空蓝', '晚霞橙', '暮光紫', '曜日红')), ('面', ('顶面', '底面', '双面', '不印丝印')), ('工艺', ('字符打印或网版印刷', '高精字符'))],
        '阻抗控制': [('管控', ('无要求', '需要')), ('公差', ('±20%', '±10%（小于50Ω±5Ω）')), ('叠构/目标/网络', ())],
        '金手指': [('金手指', ('无', '有')), ('斜边', ('不需要', '需要'))],
        '是否加急': [('交期', ('不加急', '需要加急（交期另确认）'))],
    }.get(label)


def compose(label, parts):
    values = [(key, value.strip()) for key, value in parts.items() if value.strip()]
    if label in ('厚度', '表面处理', '是否加急'):
        return '；'.join(value for _, value in values)
    return '；'.join(value if key == '补充要求' else key+'：'+value for key, value in values)


def restore(label, value, saved=None):
    if saved and compose(label, saved) == value:
        parts = dict(saved)
        if label == '板材' and '品牌/型号/TG' in parts:
            parts['TG要求'] = parts.pop('品牌/型号/TG')
        return parts
    if not value:
        return {}
    if label == '板材' and value.startswith('类别：'):
        # Older settings may contain the exported string without structured parts.
        # Only parse our known keys; arbitrary free text stays verbatim below.
        keys = {'类别', 'TG要求', '品牌/型号/TG', '补充要求'} | {key for definitions in MATERIAL_FIELDS.values() for key, _ in definitions}
        pieces = [piece.partition('：') for piece in value.split('；')]
        if all(separator and key in keys for key, separator, _ in pieces):
            parts = {key: text for key, _, text in pieces}
            if '品牌/型号/TG' in parts:
                parts['TG要求'] = parts.pop('品牌/型号/TG')
            return parts
    if label in ('厚度', '表面处理', '是否加急'):
        key = {'厚度': '成品板厚', '表面处理': '工艺', '是否加急': '交期'}[label]
        return {key: value}
    # Previous free-text requirements are kept verbatim, never silently discarded.
    return {'补充要求': value}


def validate(fields):
    by_label = {f['label']: f for f in fields if f['sheet'] == 'PCB说明'}
    get = lambda key: by_label.get(key, {}).get('value', '')
    layers = layer_count(get('PCB层数'))
    board_type = by_label.get('板材', {}).get('spec', {}).get('类别', '')
    fr4 = not board_type or board_type in ('FR-4', 'HDI盲埋孔板')
    errors = []
    finish = get('表面处理')
    if fr4 and layers is not None and layers >= 6 and ('有铅喷锡' in finish or '无铅喷锡' in finish):
        errors.append('6层及以上的FR-4/HDI不能选择喷锡，请核对表面处理。')
    thickness = by_label.get('厚度', {}).get('spec', {}).get('成品板厚', '')
    if finish and '喷锡' in finish and thickness:
        try:
            if float(thickness.removesuffix(' mm')) <= .4:
                errors.append('成品板厚≤0.4 mm不能选择喷锡。')
        except ValueError:
            pass
    for label in ('厚度', '铜箔厚度'):
        field = by_label.get(label, {})
        for key, choices in schema(label, layers, board_type):
            value = field.get('spec', {}).get(key, '')
            if choices and value and value not in choices:
                errors.append(f'{label}的{key}“{value}”不在当前{layers}层参考规格中；请改选或移入补充要求，按定制规格确认。')
    copper = by_label.get('铜箔厚度', {}).get('spec', {})
    if layers is not None and layers <= 2 and copper.get('内层'):
        errors.append('单双层板不能保留内层铜厚，请清除该项。')
    via = by_label.get('阻焊要求', {}).get('spec', {}).get('过孔', '')
    if (not board_type or board_type == 'FR-4') and layers in (2, 4, 6) and via and via not in dict(schema('阻焊要求', layers))['过孔']:
        errors.append('过孔处理不在当前层数的参考选项中，请核对Gerber和厂家工艺后修改。')
    impedance = by_label.get('阻抗控制', {}).get('spec', {})
    if impedance.get('管控') == '无要求' and (impedance.get('公差') or impedance.get('叠构/目标/网络')):
        errors.append('阻抗选择“无要求”时不能同时填写阻抗公差或目标。')
    return errors

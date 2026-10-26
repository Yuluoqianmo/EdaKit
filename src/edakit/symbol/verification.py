"""Compare stable Capture symbol content, ignoring timestamps and generated defaults."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from defusedxml import ElementTree as ET


def fields(node, keys, numeric=()):
    values = []
    for key in keys:
        value = node.get(key, '')
        if key in numeric and value != '':
            try:
                value = Decimal(value)
                if not value.is_finite():
                    raise ValueError('OLB 包含非有限数值：' + key)
            except InvalidOperation as exc:
                raise ValueError('OLB 数值字段无效：' + key) from exc
        values.append(value)
    return tuple(values)


def signatures(path):
    root = ET.parse(path, forbid_dtd=True).getroot()
    result = {}
    for package in root.findall('Package'):
        definition = package.find('Defn')
        if definition is None:
            continue
        name = definition.get('name', '')
        if name in result:
            raise ValueError('OLB 回读存在重复器件：' + name)
        parts = []
        for part in package.findall('LibPart'):
            pins = Counter()
            for pin in part.findall('.//SymbolPinScalar/Defn'):
                pins[fields(pin, ('position', 'name', 'hotptX', 'hotptY', 'startX', 'startY', 'type', 'visible'), ('position', 'hotptX', 'hotptY', 'startX', 'startY', 'type', 'visible'))] += 1
            numbers = Counter(fields(p, ('number', 'position'), ('position',)) for p in part.findall('.//PinNumber/Defn'))
            boxes = Counter(fields(p, ('x1', 'y1', 'x2', 'y2'), ('x1', 'y1', 'x2', 'y2')) for p in part.findall('.//SymbolBBox/Defn'))
            props = Counter(fields(p, ('name', 'val', 'value')) for p in part.findall('.//SymbolUserProp/Defn'))
            values = Counter(fields(p, ('name',)) for p in part.findall('.//PartValue/Defn'))
            parts.append((pins, numbers, boxes, props, values))
        result[name] = (fields(definition, ('pcbFootprint', 'pcbLib', 'refdesPrefix', 'isHomogeneous', 'alphabeticNumbering'), ('isHomogeneous', 'alphabeticNumbering')), parts)
    return result


def verify(expected, actual):
    incoming, written = signatures(expected), signatures(actual)
    if not incoming:
        raise ValueError('待校验 XML 中没有器件')
    for name, content in incoming.items():
        if written.get(name) != content:
            raise ValueError('OLB 成品内容与本次输入不一致：' + name + '；请关闭 Capture 中已打开的库后重试，原库备份保留。')
    return len(incoming)

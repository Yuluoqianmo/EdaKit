"""Compare Capture's final OLB readback against the generated pin contract."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def contract(path):
    root = ET.parse(path).getroot()
    view = root.find('.//NormalView')
    if view is None:
        raise ValueError('NormalView missing')
    for flag in ('IsPinNumbersVisible', 'IsPinNamesVisible', 'IsPinNamesRotated'):
        if view.find(f'{flag}/Defn').get('val') != '1':
            raise ValueError(f'{flag} disabled')
    if view.findall('CommentText'):
        raise ValueError('Unexpected text labels in native-label acceptance part')
    numbers = {d.get('position'): d.get('number')
               for d in root.findall('.//PhysicalPart/PinNumber/Defn')}
    result = {}
    for pin in view.findall('SymbolPinScalar'):
        d = pin.find('Defn')
        number = numbers[d.get('position')]
        if number in result:
            raise ValueError(f'Duplicate physical pin {number}')
        coords = tuple(int(d.get(k)) for k in ('hotptX', 'hotptY', 'startX', 'startY'))
        if coords[0] % 10 or coords[1] % 10:
            raise ValueError(f'Off-grid pin {number}: {coords}')
        if pin.find('IsLong/Defn').get('val') != '1':
            raise ValueError(f'Pin {number} is not Line')
        if (coords[0] != coords[2] and coords[1] != coords[3]
                or abs(coords[0]-coords[2]) + abs(coords[1]-coords[3]) != 30):
            raise ValueError(f'Invalid lead geometry {number}: {coords}')
        result[number] = (d.get('name'), d.get('type'), coords)
    if set(result) != {str(i) for i in range(1, 58)}:
        raise ValueError('Expected physical pins 1 through 57')
    if len({p[2][:2] for p in result.values()}) != 57:
        raise ValueError('Colliding connection points')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    folder = parser.parse_args().folder
    expected = contract(folder/'input.olb.xml')
    actual = contract(folder/'final.roundtrip.xml')
    if actual != expected:
        changed = [n for n in expected if expected[n] != actual[n]]
        raise ValueError(f'Capture changed pin contract: {changed}')
    print('PASS: 57 physical pins; 300 mil leads, grid, Line, native visibility and readback match')


if __name__ == '__main__':
    main()

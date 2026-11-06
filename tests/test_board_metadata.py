from pathlib import Path
from types import SimpleNamespace

import pytest

from edakit.ibom import board_metadata as m


def test_geometry_uses_actual_line_and_arc_widths_and_existing_outline_layers():
    text = ('A!CLASS!SUBCLASS!GRAPHIC_DATA_NAME!GRAPHIC_DATA_5!GRAPHIC_DATA_8!GRAPHIC_DATA_10!\n'
            'J!board!date!0!0!0!0!.001!mils!\n'
            'S!ETCH!TOP!LINE!10!!CONNECT!\n'
            'S!ETCH!BOTTOM!ARC!100!8!CONNECT!\n'
            'S!ETCH!TOP!LINE!0.5!!NOTCONNECT!\n'
            'S!BOARD GEOMETRY!OUTLINE!LINE!1!!NOTCONNECT!\n'
            'S!BOARD GEOMETRY!CUTOUT!ARC!1!1!NOTCONNECT!\n'
            'S!BOARD GEOMETRY!SILKSCREEN_TOP!LINE!1!!NOTCONNECT!\n')
    result = m.parse_geometry(text)
    assert result['width'] == 8
    assert result['outline_layers'] == ['BOARD GEOMETRY/OUTLINE', 'BOARD GEOMETRY/CUTOUT']
    assert m.parse_geometry(text.replace('mils', 'millimeters'))['width'] == pytest.approx(8/.0254)
    with pytest.raises(ValueError, match='单位'):
        m.parse_geometry(text.replace('mils', 'unknown'))


def ipc(unit='MILLIMETER'):
    return f'''<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Ecad>
      <CadHeader units="{unit}"><Spec name="dielectric"><General type="MATERIAL"><Property text="FR-4"/></General></Spec></CadHeader>
      <CadData><Layer name="TOP" layerFunction="CONDUCTOR"/><Layer name="CORE" layerFunction="DIELCORE"/>
      <Layer name="BOTTOM" layerFunction="CONDUCTOR"/><Layer name="DRILL_1-2" layerFunction="DRILL"/>
      <Stackup name="PRIMARY" overallThickness="1.6"><StackupGroup>
        <StackupLayer layerOrGroupRef="TOP" thickness="0.035" sequence="1"/>
        <StackupLayer layerOrGroupRef="CORE" thickness="1.53" sequence="2"><SpecRef id="dielectric"/></StackupLayer>
        <StackupLayer layerOrGroupRef="BOTTOM" thickness="0.035" sequence="3"/>
      </StackupGroup></Stackup>
      <Step name="board"><PadStackDef><PadstackHoleDef diameter="0.001"/></PadStackDef>
        <Profile><Polygon><PolyBegin x="-10" y="-5"/><PolyStepSegment x="10" y="-5"/>
        <PolyStepSegment x="10" y="5"/><PolyStepSegment x="-10" y="5"/><PolyStepSegment x="-10" y="-5"/></Polygon></Profile>
        <LayerFeature layerRef="DRILL_1-2"><Set><Hole diameter="0.3"/><Hole diameter="1.0"/></Set></LayerFeature>
      </Step></CadData></Ecad></IPC-2581>'''


def test_native_parameters_use_stack_order_material_and_actual_holes(tmp_path):
    path = tmp_path/'board.xml'; path.write_text(ipc())
    result = m.parse(path)
    values = result['values']
    assert values['PCB层数'] == '2'
    assert values['层序'] == 'TOP / BOTTOM'
    assert values['板材'] == 'FR-4'
    assert values['厚度'] == '1.6 mm'
    assert values['铜箔厚度'] == 'TOP: 35 μm / BOTTOM: 35 μm'
    assert values['PCB尺寸'] == '20.000 × 10.000 mm'
    assert values['最小孔径(mm)'] == '0.3'
    assert '表面处理' not in values and '最小线宽/线距(mil)' not in values
    assert '需确认' in result['sources']['厚度']


def test_native_parameters_convert_units_and_reject_unknown_units(tmp_path):
    path = tmp_path/'board.xml'; path.write_text(ipc('INCH'))
    values = m.parse(path)['values']
    assert values['厚度'] == '40.64 mm'
    assert values['最小孔径(mm)'] == '7.62'
    assert values['PCB尺寸'] == '508.000 × 254.000 mm'
    path.write_text(ipc('UNKNOWN'))
    with pytest.raises(ValueError, match='单位'):
        m.parse(path)


def test_multiple_stackups_are_not_flattened_into_one_fabrication_specification(tmp_path):
    path = tmp_path/'board.xml'
    path.write_text(ipc().replace('</CadData>', '<Stackup name="FLEX" overallThickness="0.1"/></CadData>'))
    result = m.parse(path)
    assert '厚度' not in result['values'] and 'PCB层数' not in result['values']
    assert result['warnings']


def test_read_requests_stackup_and_drill_layers_without_modifying_board(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'app_dir', lambda: tmp_path/'private')
    board = tmp_path/'snapshot.brd'; board.write_bytes(b'original')
    def runner(cmd, **kwargs):
        if Path(cmd[0]).name == 'extracta.exe':
            return SimpleNamespace(returncode=1)
        assert '-l' in cmd and '-R' in cmd and '-k' in cmd and '-S' in cmd
        Path(cmd[cmd.index('-o')+1]).write_text(ipc())
        return SimpleNamespace(returncode=0)
    assert m.read(board, tmp_path/'cadence', runner=runner)['values']['PCB层数'] == '2'
    assert board.read_bytes() == b'original'


def test_actual_holes_are_classified_and_unused_paste_does_not_select_stencil_face(tmp_path):
    path = tmp_path/'board.xml'
    path.write_text(ipc().replace('<Hole diameter="0.3"/>', '<Hole diameter="0.3" platingStatus="VIA"/>').replace('<Hole diameter="1.0"/>', '<Hole diameter="1.0" platingStatus="NONPLATED"/>'))
    result = m.parse(path)
    assert any('过孔：1个，最小0.3 mm' in s for s in result['details'])
    assert any('NPTH孔：1个，最小1 mm' in s for s in result['details'])
    assert any('未推断钢网面' in s for s in result['warnings'])
    assert '制作要求' not in result['values']

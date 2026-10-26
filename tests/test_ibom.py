import os
import json
import shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
from edakit.ibom import exporter
from edakit.install import ibom


def test_settings_launcher_returns_without_opening_modal_ui(setup, monkeypatch):
    calls = []
    monkeypatch.setattr(exporter.subprocess, 'Popen', lambda command, **kwargs: calls.append((command, kwargs)))
    monkeypatch.setattr(exporter, 'settings', lambda *a: pytest.fail('launcher must not open settings UI'))
    args = SimpleNamespace(cmd='ibom-settings', source='E:/board with spaces.brd', detach=True,
                           pick_folder=True, choose_bom=False, clear_bom=False, notify=True)
    assert exporter.command(args) == 0
    command, kwargs = calls[0]
    assert '--detach' not in command
    assert '--pick-folder' in command and '--notify' in command
    assert command[command.index('--source') + 1] == args.source
    assert kwargs['close_fds']
    assert kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'


def test_folder_picker_has_no_waiting_editor_owner(setup, monkeypatch):
    from edakit.services import directory_picker
    calls = []
    monkeypatch.setattr(directory_picker, '_pick_directory', lambda initial, owner: calls.append((initial, owner)) or 'E:/chosen')
    args = SimpleNamespace(cmd='ibom-settings', source='E:/board.brd', detach=False,
                           pick_folder=True, choose_bom=False, clear_bom=False, notify=False)
    assert exporter.command(args) == 0
    assert calls == [('', None)]
    assert exporter.settings()['outputFolder'] == 'E:/chosen'


def test_window_launcher_owns_copy_of_temporary_board(setup, monkeypatch):
    from edakit.ibom import window
    folder, board, _, _, _ = setup
    calls = []
    monkeypatch.setattr(window.subprocess, 'Popen', lambda command, **kw: (calls.append((command, kw)) or SimpleNamespace(pid=os.getpid())))
    labels = folder / 'labels.tsv'
    labels.write_text('native text data', encoding='utf-8')
    Path(str(labels)+'.models.tsv').write_text('native STEP mappings',encoding='utf-8')
    args = SimpleNamespace(board=str(board), source=str(folder / 'actual.brd'), cadence_root='D:/Cadence', labels=str(labels))
    assert window.launch(args) == 0
    command, options = calls[0]
    owned = Path(command[command.index('--board') + 1])
    assert owned != board and owned.read_bytes() == board.read_bytes()
    assert '--dialog-worker' in command
    assert options['env']['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    assert Path(command[command.index('--labels') + 1]).read_text(encoding='utf-8') == 'native text data'
    assert Path(command[command.index('--labels') + 1]+'.models.tsv').read_text(encoding='utf-8') == 'native STEP mappings'


def test_native_labels_keep_board_position_rotation_and_size(setup):
    folder, board, root, _, runner = setup
    labels=folder/'labels.tsv'
    labels.write_text('refdes\tside\tminX\tminY\tmaxX\tmaxY\trotation\tmirrored\nR1\ttop\t9\t4\t10\t6\t90\t1\n',encoding='utf-8')
    parsed=exporter.load_labels(labels)[('R1','top')]
    assert parsed['rotation']==90 and parsed['mirrored']
    result=exporter.generate(board,cadence_root=root,output=folder/'out',runner=runner,labels=labels)
    import re
    payload=json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>',Path(result['html']).read_text(encoding='utf-8'),re.S).group(1))
    assert payload['components'][0]['refdesLabel']==parsed


def test_invalid_native_label_bounds_are_rejected(setup):
    folder,*_=setup
    labels=folder/'bad.tsv'
    labels.write_text('refdes\tside\tminX\tminY\tmaxX\tmaxY\trotation\tmirrored\nR1\ttop\t0\t0\tnan\t1\t0\t0\n',encoding='utf-8')
    with pytest.raises(ValueError,match='范围无效'):
        exporter.load_labels(labels)


def test_footprint_parser_retains_original_project_geometry(setup):
    _, _, _, xml, _ = setup
    polygon = '<Polygon><PolyBegin x="0" y="0"/><PolyStepSegment x="1" y="0"/><PolyStepSegment x="1" y="1"/></Polygon>'
    xml.write_text(IPC.replace('<PickupPoint', '<AssemblyDrawing>'+polygon+'</AssemblyDrawing><SilkScreen>'+polygon+'</SilkScreen><PickupPoint'))
    geometry = exporter.reference.parse_ipc_packages(xml)['R0805']
    assert {shape['source'] for shape in geometry.drawing_shapes} == {'outline', 'assemblydrawing', 'silkscreen'}


def test_export_reports_actual_stages_and_can_force_board_information(setup):
    folder, board, root, _, runner = setup
    exporter.settings({'outputFolder': '', 'bomByBoard': {exporter.board_key(board): 'E:/missing.xlsx'}})
    stages = []
    result = exporter.generate(board, cadence_root=root, output=folder/'out', runner=runner, use_board=True, progress=stages.append)
    assert result['overlay'] == ''
    assert len(stages) == 7 and stages[-1].startswith('导出完成')

IPC = '''<IPC-2581 xmlns="http://webstds.ipc.org/2581"><Content><FunctionMode mode="USERDEF" level="3"/><StepRef name="BOARD"/></Content><Bom name="bom"><BomItem OEMDesignNumberRef="internal"><RefDes name="R1" populate="true"/><RefDes name="R2" populate="false"/><Characteristics><Textual textualCharacteristicName="COMP_VALUE" textualCharacteristicValue="10K"/></Characteristics></BomItem></Bom><Ecad><CadData units="MILLIMETER"><Step name="BOARD"><Profile><Polygon><PolyBegin x="0" y="0"/><PolyStepSegment x="30" y="0"/><PolyStepSegment x="30" y="20"/><PolyStepSegment x="0" y="20"/></Polygon></Profile><Package name="R0805"><Outline><Polygon><PolyBegin x="-1" y="-0.5"/><PolyStepSegment x="1" y="-0.5"/><PolyStepSegment x="1" y="0.5"/><PolyStepSegment x="-1" y="0.5"/></Polygon></Outline><PickupPoint x="0" y="0"/></Package><Component refDes="R1" packageRef="R0805" layerRef="TOP"><Xform rotation="90"/><Location x="10" y="5"/><NonstandardAttribute name="Manufacturer_PN" value="PN-001"/><NonstandardAttribute name="Manufacturer" value="Maker"/></Component><Component refDes="R2" packageRef="R0805" layerRef="BOTTOM"><Xform rotation="180"/><Location x="20" y="5"/></Component></Step></CadData></Ecad></IPC-2581>'''


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'app'))
    board = tmp_path / 'test board.brd'
    board.write_bytes(b'original-design')
    root = tmp_path / 'Cadence'
    (root / 'tools/bin').mkdir(parents=True)
    (root / 'tools/bin/ipc2581_out.exe').write_bytes(b'fake')
    xml = tmp_path / 'input.xml'
    xml.write_text(IPC)
    def runner(command, **kwargs):
        assert command[0].endswith('ipc2581_out.exe')
        assert command[command.index('-u') + 1] == 'MILLIMETER'
        assert kwargs['timeout'] == 300
        assert 'Component/MANUFACTURER_PN' in Path(command[command.index('-g')+1]).read_text(encoding='ascii')
        shutil.copy2(xml, command[command.index('-o') + 1])
        return SimpleNamespace(returncode=0)
    return tmp_path, board, root, xml, runner


def test_native_bom_instance_properties_and_dnp(setup):
    _, _, _, xml, _ = setup
    rows, ignored = exporter.native_bom(xml)
    assert ignored == {'R2'}
    assert len(rows) == 1
    assert rows[0]['manufacturer_pn'] == 'PN-001'
    assert rows[0]['value'] == '10K'
    assert rows[0]['quantity'] == 1


def test_generate_reuses_engine_offline_and_never_overwrites_board(setup):
    folder, board, root, _, runner = setup
    result = exporter.generate(board, cadence_root=root, output=folder / 'output', runner=runner)
    assert board.read_bytes() == b'original-design'
    assert result['components'] == 1
    page = Path(result['html']).read_text(encoding='utf-8')
    assert 'PN-001' in page and '10K' in page
    assert '<svg' in page
    assert Path(result['report']).is_file()
    import re
    payload=json.loads(re.search(r'<script id="payload" type="application/json">(.*?)</script>',page,re.S).group(1))
    assert all(c['refdes'] != 'R2' for c in payload['components'])


def test_final_bom_override_keeps_native_dnp_exclusion(setup):
    folder, board, root, _, runner = setup
    bom = folder / 'final.csv'
    bom.write_text('位号,厂家型号,物料编码,数量,描述\nR1,MODEL,000009,1,Final resistor\nR2,OTHER,000010,1,DNP\n', encoding='utf-8-sig')
    result = exporter.generate(board, cadence_root=root, output=folder / 'out', bom=bom, runner=runner)
    assert result['components'] == 1
    page = Path(result['html']).read_text(encoding='utf-8')
    assert 'MODEL' in page and '000009' in page and 'Final resistor' in page
    assert '000010' not in page


def test_final_bom_cannot_reintroduce_bom_ignore_component(setup):
    folder, board, root, xml, runner = setup
    xml.write_text(IPC.replace('populate="false"', 'populate="true"').replace('<Component refDes="R2" packageRef="R0805" layerRef="BOTTOM">', '<Component refDes="R2" packageRef="R0805" layerRef="BOTTOM"><NonstandardAttribute name="BOM_IGNORE" value="TRUE"/>'))
    bom = folder / 'final.csv'
    bom.write_text('位号,厂家型号,数量\nR1,MODEL,1\nR2,IGNORE-ME,1\n', encoding='utf-8-sig')
    result = exporter.generate(board, cadence_root=root, output=folder / 'out', bom=bom, runner=runner)
    assert result['components'] == 1
    assert 'IGNORE-ME' not in Path(result['html']).read_text(encoding='utf-8')


def test_export_failure_preserves_inputs_and_does_not_publish_html(setup):
    folder, board, root, _, _ = setup
    with pytest.raises(ValueError, match='IPC-2581'):
        exporter.generate(board, cadence_root=root, output=folder / 'bad', runner=lambda *a, **kw: SimpleNamespace(returncode=2))
    assert not list((folder / 'bad').glob('*.html'))
    assert board.read_bytes() == b'original-design'


def test_startup_preserves_user_bytes_and_is_idempotent(setup):
    folder, _, root, _, _ = setup
    home = folder / 'pcbenv'
    home.mkdir()
    original = b'; user settings \xd6\xd0\xce\xc4\nfoo=1\n'
    (home / 'allegro.ilinit').write_bytes(original)
    executable = folder / 'edakit.exe'
    executable.write_bytes(b'exe')
    result = ibom.deploy(root, executable=executable, pcbenv=home)
    first = (home / 'allegro.ilinit').read_bytes()
    ibom.deploy(root, executable=executable, pcbenv=home)
    assert (home / 'allegro.ilinit').read_bytes() == first
    assert first.startswith(original)
    assert first.count(ibom.BEGIN) == 1
    assert (home / 'allegro.ilinit.edakit-ibom.bak').read_bytes() == original
    assert Path(result['skill']).read_bytes().isascii()


def test_startup_broken_marker_is_not_overwritten(setup):
    folder, _, root, _, _ = setup
    home = folder / 'home'
    home.mkdir()
    original = ibom.BEGIN + b'\nuser code'
    (home / 'allegro.ilinit').write_bytes(original)
    executable = folder / 'edakit.exe'; executable.write_bytes(b'exe')
    with pytest.raises(ValueError):
        ibom.deploy(root, executable=executable, pcbenv=home)
    assert (home / 'allegro.ilinit').read_bytes() == original


def test_uninstall_removes_only_managed_startup_and_script(setup):
    folder, _, root, _, _ = setup
    home = folder / 'home'
    home.mkdir()
    (home / 'allegro.ilinit').write_bytes(b'; custom code\n')
    executable = folder / 'edakit.exe'; executable.write_bytes(b'exe')
    result = ibom.deploy(root, executable=executable, pcbenv=home)
    (home / 'allegro.ilinit').write_bytes((home / 'allegro.ilinit').read_bytes() + b'; later user edit\n')
    ibom.undeploy(pcbenv=home)
    assert not Path(result['skill']).exists()
    contents = (home / 'allegro.ilinit').read_bytes()
    assert b'custom code' in contents and b'later user edit' in contents
    assert ibom.BEGIN not in contents

@pytest.mark.parametrize('rotation,expected', [(0,(12,20)), (90,(10,22)), (180,(8,20)), (270,(10,18))])
def test_component_uses_footprint_origin_not_pickup_centroid(rotation, expected):
    r = exporter.reference
    package = r.PackageGeometry(name='HEADER', pickup_x=7, pickup_y=3,
        bbox={'minX':0,'minY':0,'maxX':2,'maxY':1},
        outline_polygons=[[{'x':2,'y':0}]],
        drawing_shapes=[{'type':'polygon','points':[{'x':2,'y':0}],'source':'assemblydrawing','width':0}],
        pad_shapes=[{'type':'rect','x':2,'y':0,'width':1,'height':1,'rotation':0}])
    package.pad_shapes[0]['primitive']='rect'
    row={'id':'r','references':['J1'],'footprint':'HEADER','description':'','value':''}
    comps,_ = r.build_components([row], {'J1':{'x':10,'y':20,'rotation':rotation,'side':'top','package':'HEADER'}}, None, {'HEADER':package})
    c=comps[0]
    for point in [c['padShapes'][0],c['drawingShapes'][0]['points'][0],c['outlinePolygons'][0][0]]:
        assert (point['x'],point['y']) == pytest.approx(expected)


@pytest.mark.parametrize('clockwise,start,end,mid', [
    ('true',(0,-5),(-5,0),(-3.5355339,-3.5355339)),
    ('false',(5,0),(0,5),(3.5355339,3.5355339))])
def test_ipc_arc_keeps_center_radius_and_direction(clockwise,start,end,mid):
    from xml.etree import ElementTree as ET
    node=ET.fromstring(f'<Polygon><PolyBegin x="{start[0]}" y="{start[1]}"/><PolyStepCurve x="{end[0]}" y="{end[1]}" centerX="0" centerY="0" clockwise="{clockwise}"/></Polygon>')
    points=exporter.reference.parse_ipc_polygon(node)
    assert len(points)>40
    assert (points[0]['x'],points[0]['y'])==start
    assert (points[-1]['x'],points[-1]['y'])==end
    assert all((p['x']**2+p['y']**2)**.5 == pytest.approx(5) for p in points)
    closest=min(points,key=lambda p:(p['x']-mid[0])**2+(p['y']-mid[1])**2)
    assert abs(closest['x']-mid[0])<.07 and abs(closest['y']-mid[1])<.07



def test_3d_models_deduplicate_and_keep_native_mapping(setup):
    from edakit.ibom import preview3d
    folder,board,root,xml,_=setup
    model=folder/'actual.stp'
    model.write_bytes(b'ISO-10303-21;\nDATA;\nENDSEC;\nEND-ISO-10303-21;')
    labels=folder/'labels.tsv'; sidecar=Path(str(labels)+'.models.tsv')
    sidecar.write_text('refdes\tfile\trx\try\trz\tox\toy\toz\tsearch\nR1\t'+str(model)+'\t0\t90\t180\t1\t2\t3\t\nR2\t'+str(model)+'\t0\t0\t0\t0\t0\t0\t\n',encoding='utf-8')
    payload={'components':[{'refdes':'R1','footprint':'R0805'},{'refdes':'R2','footprint':'R0805'}]}
    preview3d.prepare(payload,xml,board,labels)
    assert len(payload['preview3d']['models'])==1
    assert payload['components'][0]['model3d']['rotation']==[0,90,180]
    assert payload['components'][0]['model3d']['offset']==[1,2,3]
    assert payload['components'][0]['model3d']['key']==payload['components'][1]['model3d']['key']


def test_3d_missing_step_is_explicit_fallback(setup):
    from edakit.ibom import preview3d
    folder,board,_,xml,_=setup
    labels=folder/'labels.tsv'
    Path(str(labels)+'.models.tsv').write_text('refdes\tfile\trx\try\trz\tox\toy\toz\tsearch\nR1\tmissing.stp\t0\t0\t0\t0\t0\t0\t\n',encoding='utf-8')
    payload={'components':[{'refdes':'R1','footprint':'R0805'}]}
    preview3d.prepare(payload,xml,board,labels)
    assert payload['components'][0]['model3d'] is None
    assert len(payload['preview3d']['warnings'])==1
    assert payload['preview3d']['boardThicknessSource']=='默认示意'


def test_3d_native_resolved_file_wins_over_other_libraries(setup):
    from edakit.ibom import preview3d
    import base64
    folder,board,_,xml,_=setup
    (folder/'same.stp').write_bytes(b'ISO-10303-21;wrong library')
    native=folder/'native library';native.mkdir()
    model=native/'same.step';raw=b'ISO-10303-21;native resolved model';model.write_bytes(raw)
    labels=folder/'labels.tsv'
    Path(str(labels)+'.models.tsv').write_text('refdes\tfile\trx\try\trz\tox\toy\toz\tsearch\tresolved\nR1\tsame.stp\t0\t0\t0\t0\t0\t0\t\t'+str(model)+'\n',encoding='utf-8')
    payload={'components':[{'refdes':'R1','footprint':'R0805','height3d':100}]}
    preview3d.prepare(payload,xml,board,labels)
    assert base64.b64decode(next(iter(payload['preview3d']['models'].values()))['data'])==raw
    assert 'height3d' not in payload['components'][0]


def test_3d_extensionless_mapping_finds_step_alternative(setup):
    from edakit.ibom import preview3d
    folder,board,_,xml,_=setup
    (folder/'extensionless.step').write_bytes(b'ISO-10303-21;actual model')
    labels=folder/'labels.tsv'
    Path(str(labels)+'.models.tsv').write_text('refdes\tfile\trx\try\trz\tox\toy\toz\tsearch\nR1\textensionless\t0\t0\t0\t0\t0\t0\t\n',encoding='utf-8')
    payload={'components':[{'refdes':'R1','footprint':'R0805'}]}
    preview3d.prepare(payload,xml,board,labels)
    assert payload['components'][0]['model3d'] is not None

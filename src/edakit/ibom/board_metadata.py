"""Read manufacturing facts from a private Allegro IPC export, never defaults."""
import math
import os
from pathlib import Path
import subprocess
import uuid

from ..config import app_dir
from ..services.bom import xml
from . import reference

NS = {'i': 'http://webstds.ipc.org/2581'}


def parse(path):
    root = xml(Path(path).read_bytes())
    header = root.find('.//i:CadHeader', NS)
    unit = header.get('units', '').upper() if header is not None else ''
    scale = {'MILLIMETER': 1, 'INCH': 25.4, 'MICRON': .001}.get(unit)
    if scale is None:
        raise ValueError('无法确认 PCB 参数单位')
    values, sources, warnings, details, copper_layers = {}, {}, [], [], []
    def put(label, value, source):
        values[label] = value
        sources[label] = source
    def number(value):
        try:
            n = float(value)
            return n if math.isfinite(n) and n > 0 else None
        except (ValueError, TypeError):
            return None
    def fmt(value):
        return f'{value:.6f}'.rstrip('0').rstrip('.')
    cad = root.find('.//i:CadData', NS)
    if cad is None:
        raise ValueError('PCB 导出缺少 CadData')
    stacks = cad.findall('i:Stackup', NS)
    if len(stacks) == 1:
        stack = stacks[0]
        layers = {x.get('name'): x.get('layerFunction', '').upper() for x in cad.findall('i:Layer', NS)}
        ordered = sorted(stack.findall('.//i:StackupLayer', NS), key=lambda x: int(x.get('sequence', '0')))
        copper = [x for x in ordered if layers.get(x.get('layerOrGroupRef')) in ('CONDUCTOR', 'POWERGROUND', 'MIXED', 'PLANE')]
        names = [x.get('layerOrGroupRef') for x in copper]
        if names and len(names) == len(set(names)):
            copper_layers = [{'name': name, 'kind': layers[name]} for name in names]
            put('PCB层数', str(len(names)), 'PCB 导电叠层')
            put('层序', ' / '.join(names), 'PCB 叠层顺序')
        thickness = number(stack.get('overallThickness'))
        if thickness:
            put('厚度', fmt(thickness*scale)+' mm', 'PCB 叠层值，需确认制板厚度')
        materials = {s.get('name'): [p.get('text', '') for p in s.findall('i:General[@type="MATERIAL"]/i:Property', NS)] for s in header.findall('i:Spec', NS)}
        dielectric = []
        for layer in ordered:
            if layers.get(layer.get('layerOrGroupRef'), '').startswith('DIEL'):
                for spec in layer.findall('i:SpecRef', NS):
                    dielectric += materials.get(spec.get('id'), [])
        dielectric = list(dict.fromkeys(s for s in dielectric if s and s.upper() not in ('UNKNOWN', 'UNSPECIFIED')))
        if dielectric:
            put('板材', ' / '.join(dielectric), 'PCB 介质材料')
        if copper and all(number(x.get('thickness')) for x in copper):
            put('铜箔厚度', ' / '.join(x.get('layerOrGroupRef')+': '+fmt(float(x.get('thickness'))*scale*1000)+' μm' for x in copper), 'PCB 各铜层厚度，需确认工艺')
    else:
        warnings.append('多叠层或缺少叠层，未自动填写层数、板厚和材料')
    steps = cad.findall('i:Step', NS)
    if len(steps) == 1:
        step = steps[0]
        profile = step.find('i:Profile/i:Polygon', NS)
        if profile is not None:
            points = reference.parse_ipc_polygon(profile)
            if len(points) >= 4 and all(math.isfinite(p[k]) for p in points for k in ('x', 'y')):
                width = (max(p['x'] for p in points)-min(p['x'] for p in points))*scale
                height = (max(p['y'] for p in points)-min(p['y'] for p in points))*scale
                if width > 0 and height > 0:
                    put('PCB尺寸', f'{width:.3f} × {height:.3f} mm', 'PCB 板框包络尺寸')
        # Actual drilled holes only; unused padstack definitions are not evidence.
        drills = {x.get('name') for x in cad.findall('i:Layer', NS) if x.get('layerFunction') == 'DRILL'}
        diameters = [number(h.get('diameter')) for layer in step.findall('i:LayerFeature', NS) if layer.get('layerRef') in drills for h in layer.findall('.//i:Hole', NS)]
        diameters = [v*scale for v in diameters if v]
        if diameters:
            put('最小孔径(mm)', fmt(min(diameters)), 'PCB 实际圆孔最小直径')
        groups = {}
        for layer in step.findall('i:LayerFeature', NS):
            if layer.get('layerRef') not in drills:
                continue
            for set_ in layer.findall('i:Set', NS):
                for hole in set_.findall('.//i:Hole', NS):
                    diameter = number(hole.get('diameter'))
                    if not diameter:
                        continue
                    status = hole.get('platingStatus', '').upper()
                    kind = '过孔' if status == 'VIA' or set_.get('geometry', '').upper() == 'VIA' else 'PTH孔' if status == 'PLATED' else 'NPTH孔' if status in ('NONPLATED', 'NON_PLATED', 'NON-PLATED') else '未分类圆孔'
                    groups.setdefault(kind, []).append(diameter*scale)
        for kind, diameters_ in groups.items():
            details.append(f'PCB {kind}：{len(diameters_)}个，最小{fmt(min(diameters_))} mm。')
        # Only actual placed features prove an active paste face, not library definitions.
        paste_layers = {x.get('name'): x.get('side') for x in cad.findall('i:Layer', NS) if x.get('layerFunction', '').upper() == 'SOLDERPASTE'}
        sides = set()
        for layer in step.findall('i:LayerFeature', NS):
            side = paste_layers.get(layer.get('layerRef'))
            if side in ('TOP', 'BOTTOM') and any(x.tag.rsplit('}', 1)[-1] in ('Pad', 'Features') for x in layer.iter()):
                sides.add(side)
        if sides:
            details.append('PCB 有效锡膏图形：'+'、'.join('顶面' if s == 'TOP' else '底面' for s in sorted(sides))+'；钢网制作方式请确认。')
        else:
            warnings.append('当前导出未提供有效锡膏/阻焊图形，未推断钢网面或过孔开窗；按Gerber文件核对。')
    else:
        warnings.append('多个 PCB Step，未猜测板框和最小孔径')
    put('制图软件', 'Cadence Allegro', '当前 PCB 导出工具')
    return dict(values=values, sources=sources, warnings=warnings, details=details, copper_layers=copper_layers)


def read(board, cadence_root, runner=subprocess.run):
    folder = app_dir()/'delivery'/'metadata'/uuid.uuid4().hex
    folder.mkdir(parents=True)
    path = folder/'board.xml'
    root = Path(cadence_root)
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    env = dict(os.environ, CDSROOT=str(root), ALLEGRO_ROOT=str(root))
    with (folder/'export.log').open('wb') as log:
        result = runner([str(root/'tools/bin/ipc2581_out.exe'), '-l', '-R', '-k', '-O', '-I', '-S',
                         '-u', 'MILLIMETER', '-o', str(path), str(Path(board).resolve())],
                        cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120, **options)
    if result.returncode not in (0, 1) or not path.is_file():
        raise ValueError('PCB 参数读取失败，日志：'+str(folder/'export.log'))
    metadata = parse(path)
    try:
        command = folder/'geometry.txt'
        names = ['CLASS', 'SUBCLASS', 'GRAPHIC_DATA_NAME', 'NET_NAME'] + ['GRAPHIC_DATA_'+str(i) for i in range(1, 11)]
        command.write_text('GEOMETRY\n'+'\n'.join(names)+'\nEND\n', encoding='ascii')
        geometry = folder/'geometry.out'
        with (folder/'geometry.log').open('wb') as log:
            result = runner([str(root/'tools/bin/extracta.exe'), str(Path(board).resolve()), str(command), str(geometry)], cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120, **options)
        if result.returncode != 0 or not geometry.is_file():
            raise ValueError('Extracta 未生成几何数据')
        facts = parse_geometry(geometry.read_text(encoding='utf-8', errors='replace'))
        metadata['geometry_layers'] = facts['layers']
        metadata['choices'] = {'板框层': facts['outline_layers']}
        if len(facts['outline_layers']) == 1:
            metadata['values']['板框层'] = facts['outline_layers'][0]
            metadata['sources']['板框层'] = 'PCB 中实际存在的板框图形层'
        if facts['width'] is not None:
            metadata['values']['最小线宽/线距(mil)'] = f"{facts['width']:.4f}".rstrip('0').rstrip('.')+' / 待确认'
            metadata['sources']['最小线宽/线距(mil)'] = '实际走线最小宽度 / 线距待确认'
            metadata['details'].append('已读取实际最小走线宽度；完整铜间距含焊盘、铺铜，尚未自动测量，请确认斜杠后的线距。')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        metadata['warnings'].append('几何参数未能读取：'+str(error))
    return metadata


def parse_geometry(text):
    """Extracta geometry fields are defined in Cadence algrodescmp/appa.html.

    Width is DATA_5 for LINE and DATA_8 for ARC. Never treat a net's
    minimum-width constraint as a measurement of placed copper.
    """
    lines = text.splitlines()
    header = next(line.split('!')[1:-1] for line in lines if line.startswith('A!'))
    info = next(line.split('!') for line in lines if line.startswith('J!'))
    scale = {'mils': 1, 'millimeters': 1/.0254, 'inches': 1000}.get(info[8].lower())
    if scale is None:
        raise ValueError('无法确认几何参数单位')
    outlines, widths, layers = set(), [], set()
    for line in lines:
        if not line.startswith('S!'):
            continue
        row = dict(zip(header, line.split('!')[1:-1]))
        if row.get('CLASS') and row.get('SUBCLASS'):
            layers.add(row['CLASS']+'/'+row['SUBCLASS'])
        kind = row.get('GRAPHIC_DATA_NAME')
        if kind not in ('LINE', 'ARC'):
            continue
        class_, layer = row.get('CLASS', ''), row.get('SUBCLASS', '')
        if class_ in ('BOARD GEOMETRY', 'MANUFACTURING') and any(token in layer.upper() for token in ('OUTLINE', 'DESIGN_OUTLINE', 'ROUTE', 'BOARD', 'PROFILE', 'CUT', '边', '框')):
            outlines.add(class_+'/'+layer)
        if class_ == 'ETCH' and row.get('GRAPHIC_DATA_10') == 'CONNECT':
            value = float(row['GRAPHIC_DATA_5' if kind == 'LINE' else 'GRAPHIC_DATA_8'])*scale
            if math.isfinite(value) and value > 0:
                widths.append(value)
    return {'outline_layers': sorted(outlines, key=lambda s: ('OUTLINE' not in s, s)), 'width': min(widths) if widths else None, 'layers': sorted(layers)}

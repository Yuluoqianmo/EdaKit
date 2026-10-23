"""Offline STEP-backed preview using native library resolution, never invented bodies."""
import base64
import csv
import hashlib
import html
import io
import json
import math
import os
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from ..config import Config
from . import facets


def board_holes(ipc):
    """Resolve actual package drills, including mounting parts outside the BOM."""
    if not ipc:
        return []
    ns = {'i': 'http://webstds.ipc.org/2581'}
    root = ET.parse(ipc).getroot()
    drills = {}
    for stack in root.findall('.//i:PadStackDef', ns):
        hole = stack.find('i:PadstackHoleDef', ns)
        if hole is not None:
            values = [float(hole.get(k, '0')) for k in ('x', 'y', 'diameter')]
            if all(math.isfinite(v) for v in values) and values[2] > 0:
                drills[stack.get('name')] = values
    packages = {p.get('name'): p for p in root.findall('.//i:Package', ns)}
    holes = {}
    def rotate(x, y, angle):
        a = math.radians(angle)
        return x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a)
    for comp in root.findall('.//i:Step/i:Component', ns):
        package = packages.get(comp.get('packageRef'))
        location = comp.find('i:Location', ns)
        if package is None or location is None:
            continue
        xform = comp.find('i:Xform', ns)
        angle = float(xform.get('rotation', '0')) if xform is not None else 0
        for pad in package.findall('i:LandPattern/i:Pad', ns):
            drill = drills.get(pad.get('padstackDefRef'))
            pos = pad.find('i:Location', ns)
            if drill is None or pos is None:
                continue
            pf = pad.find('i:Xform', ns)
            dx, dy = rotate(*drill[:2], float(pf.get('rotation', '0')) if pf is not None else 0)
            x, y = rotate(float(pos.get('x', '0'))+dx, float(pos.get('y', '0'))+dy, angle)
            x += float(location.get('x', '0')); y += float(location.get('y', '0'))
            if all(math.isfinite(v) for v in (x, y)):
                holes[(round(x, 6), round(y, 6), drill[2])] = {'x': x, 'y': y, 'diameter': drill[2]}
    return list(holes.values())


def prepare(payload, ipc, source, labels=None):
    mappings={}
    sidecar=Path(str(labels)+'.models.tsv') if labels else None
    if sidecar and sidecar.is_file():
        try:
            text=sidecar.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:
            text=sidecar.read_text(encoding='mbcs' if os.name=='nt' else 'utf-8')
        mappings={row['refdes'].upper():row for row in csv.DictReader(io.StringIO(text),delimiter='\t')}
    models={}; total=0; warnings=[]; loaded={}; diagnostics=[]
    library=Path(Config.load().effective_step_lib)
    for comp in payload['components']:
        comp.pop('height3d',None)
        row=mappings.get(comp['refdes'])
        comp['model3d']=None
        if not row:
            diagnostics.append({'refdes':comp['refdes'],'status':'无 STEP 绑定'})
            continue
        try:
            pose=[float(row[k]) for k in ('rx','ry','rz','ox','oy','oz')]
            if not all(math.isfinite(v) for v in pose): raise ValueError('invalid transform')
            name=Path(row['file'])
            roots=[Path(source).parent,library]
            if row.get('package_resolved'):
                roots.insert(0,Path(row['package_resolved']).parent)
            for token in re.findall(r'"[^"]+"|\S+',row.get('search','')):
                p=Path(os.path.expandvars(token.strip('"'))).expanduser()
                roots.append(p if p.is_absolute() else Path(source).parent/p)
            candidates=[name] if name.is_absolute() else [p/name for p in roots]
            if row.get('resolved'):
                candidates.insert(0,Path(row['resolved']))
            candidates += [p.with_suffix(ext) for p in list(candidates) if p.suffix.lower() in ('','.stp','.step') for ext in ('.stp','.step')]
            cache_name=name.stem+'.xml' if name.suffix.lower() in ('.stp','.step') else name.name+'.xml'
            cache_candidates=[Path(row['facet_resolved'])] if row.get('facet_resolved') else []
            cache_candidates += [p/'stepFacetFiles4Map'/cache_name for p in roots]
            cache_candidates += [p/cache_name for p in roots]
            errors=[]; key=None; path=None; kind=None
            for candidate,format_name in [(p,'step') for p in candidates]+[(p,'allegro-facets') for p in cache_candidates]:
                if not candidate.is_file(): continue
                identity=(str(candidate.resolve()),format_name)
                try:
                    if identity in loaded:
                        key=loaded[identity];path=candidate;kind=format_name;break
                    if candidate.stat().st_size>25_000_000: raise ValueError('模型文件超出预览大小限制')
                    raw=candidate.read_bytes()
                    digest=hashlib.sha256(raw).hexdigest()
                    model_key=format_name+':'+digest
                    if model_key not in models:
                        entry={'name':candidate.name,'format':format_name}
                        if format_name=='step':
                            if not raw.lstrip().startswith(b'ISO-10303-21;'): raise ValueError('STEP 文件格式无效')
                            entry['data']=base64.b64encode(raw).decode('ascii')
                        else:
                            entry['meshes']=facets.parse(raw)
                        size=len(json.dumps(entry,separators=(',',':')))
                        if total+size>80_000_000: raise ValueError('真实模型总大小超出预览限制')
                        models[model_key]=entry;total+=size
                    loaded[identity]=model_key;key=model_key;path=candidate;kind=format_name;break
                except (OSError,ValueError) as error:
                    errors.append(candidate.name+': '+str(error))
            if key is None: raise ValueError('; '.join(errors) if errors else 'STEP 与 Allegro 模型缓存均未找到')
            comp['model3d']={'key':key,'rotation':pose[:3],'offset':pose[3:]}
            diagnostics.append({'refdes':comp['refdes'],'status':'已加载','format':kind,'file':str(path)})
        except (OSError,ValueError,KeyError) as error:
            warnings.append(comp['refdes']+': '+str(error))
            diagnostics.append({'refdes':comp['refdes'],'status':str(error),'mapping':row.get('file','')})
    payload['preview3d']={'models':models,'boardThickness':1.6,'boardThicknessSource':'默认示意', 'warnings':warnings,'diagnostics':diagnostics,'boardHoles':board_holes(ipc)}


def embed(page,payload):
    folder=Path(__file__).parent
    library=(folder/'vendor/three.min.js').read_text(encoding='utf-8')
    extra=''
    uses_step=any(entry.get('format','step')=='step' for entry in payload.get('preview3d',{}).get('models',{}).values())
    if uses_step:
        wasm=base64.b64encode((folder/'vendor/occt-import-js.wasm').read_bytes()).decode('ascii')
        extra='<script>'+ (folder/'vendor/occt-import-js.js').read_text(encoding='utf-8').replace('</script','<\\/script')+'</script>'
        extra+='<script>window.__ibomWasm="'+wasm+'";</script>'
    scripts='<script>'+library.replace('</script','<\\/script')+'</script>'+extra
    scripts+='<script>'+(folder/'view3d.js').read_text(encoding='utf-8').replace('</script','<\\/script')+'</script>'
    notices='three.js 0.158.0 — https://github.com/mrdoob/three.js/tree/r158\n'+(folder/'vendor/three.LICENSE').read_text(encoding='utf-8')
    if uses_step:
        notices+='\nocct-import-js 0.0.23 — https://github.com/kovacsv/occt-import-js\n'+(folder/'vendor/occt.LICENSE').read_text(encoding='utf-8')
    scripts+='<script type="text/plain" id="preview3d-licenses">'+html.escape(notices)+'</script>'
    return page.replace('</body>',scripts+'</body>')

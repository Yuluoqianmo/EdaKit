"""Allegro 17.2 标准焊盘封装候选脚本，原生结果须上机验收。"""
from __future__ import annotations
import hashlib
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from ..easyeda.model import Footprint
from ..errors import UnsupportedGeometryError

LAYERS = {'TOP':'TOP', 'BOTTOM':'BOTTOM', 'DEFAULT_INTERNAL':'DEFAULT_INTERNAL',
          'TOP_SOLDERMASK':'SOLDERMASK_TOP', 'BOTTOM_SOLDERMASK':'SOLDERMASK_BOTTOM',
          'TOP_PASTE':'PASTEMASK_TOP', 'BOTTOM_PASTE':'PASTEMASK_BOTTOM'}
DRAW = {'TOP_SILK':'PACKAGE GEOMETRY/SILKSCREEN_TOP',
        'BOTTOM_SILK':'PACKAGE GEOMETRY/SILKSCREEN_BOTTOM',
        'TOP_ASSEMBLY':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'BOTTOM_ASSEMBLY':'PACKAGE GEOMETRY/ASSEMBLY_BOTTOM',
        'DOCUMENT':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'BOARD_OUTLINE':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'ComponentPolarityLayer':'PACKAGE GEOMETRY/SILKSCREEN_TOP'}
SOLID_DRAW = {'ComponentShapeLayer': 'PACKAGE GEOMETRY/ASSEMBLY_TOP',
              'LeadShapeLayer': 'PACKAGE GEOMETRY/ASSEMBLY_TOP',
              'TOP_PASTE': 'PACKAGE GEOMETRY/PASTEMASK_TOP',
              'ComponentPolarityLayer': 'PACKAGE GEOMETRY/SILKSCREEN_TOP'}

def _s(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')

def _pt(x, y):
    return f'{x:.4f}:{y:.4f}'

def _check(call, label):
    return f'    (unless {call} (error "EdaKit: {_s(label)} failed"))'

def generate_skill(fp: Footprint, *, drill_plated: bool = True, output_dir: Path | None = None,
                   refdes_prefix: str = "", manual: bool = False) -> str:
    """按本机 algroskill 手册生成脚本；在独立符号编辑器加载，拒绝覆盖输出。"""
    prefix = (refdes_prefix or "U").strip().rstrip("?*")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", prefix):
        raise UnsupportedGeometryError(f'无效的器件位号前缀: {refdes_prefix!r}')
    if not fp.name or any(c in fp.name for c in '<>:"/\\|?*\r\n') or fp.name.endswith(('.', ' ')):
        raise UnsupportedGeometryError('封装名称不是有效的单个库文件名。')
    if not fp.padstacks:
        raise UnsupportedGeometryError('封装没有可生成的焊盘。')
    numbers = [ps.name for ps in fp.padstacks]
    if (len(numbers) != len(set(numbers)) or
            any(not n or n.startswith('@') or any(c.isspace() or ord(c) < 32 for c in n) for n in numbers)):
        raise UnsupportedGeometryError('封装引脚编号为空、重复或无效；机械孔需独立建模。')
    if any(p.kind in {'HOLE', 'RECT', 'RECTANGLE'} for p in fp.primitives):
        raise UnsupportedGeometryError('当前阶段尚不支持圆弧、独立孔或矩形图元，拒绝丢弃几何。')
    for region in fp.solid_regions:
        layer = region.geom.get('layer')
        pts = region.geom.get('points_mm') or []
        if (layer not in SOLID_DRAW or not region.geom.get('path_supported', True)
                or len(pts) < 6 or len(pts) % 2
                or not all(math.isfinite(v) for v in pts)):
            raise UnsupportedGeometryError(f'不支持的填充区域: {layer!r}，或区域路径无效。')
    for ps in fp.padstacks:
        if not all(math.isfinite(v) for v in (ps.x_mm, ps.y_mm, ps.rotation_deg, ps.drill_mm)) or ps.drill_mm < 0 or not ps.layers:
            raise UnsupportedGeometryError(f'焊盘 {ps.name} 的坐标、钻孔或层无效。')
        for lay in ps.layers:
            if lay.layer not in LAYERS or lay.shape not in {'RECT', 'CIRCLE', 'OBLONG'}:
                raise UnsupportedGeometryError(f'焊盘 {ps.name}: 暂不支持 {lay.layer}/{lay.shape}，拒绝近似铜形。')
            if not all(math.isfinite(v) and v > 0 for v in (lay.w_mm, lay.h_mm)):
                raise UnsupportedGeometryError(f'焊盘 {ps.name} 尺寸无效。')
            if lay.shape == 'CIRCLE' and abs(lay.w_mm - lay.h_mm) > 1e-4:
                raise UnsupportedGeometryError(f'焊盘 {ps.name} 圆形宽高不相等。')
    if any(l not in DRAW for l, _ in fp.lines) or any(l not in DRAW for l, *_ in fp.circles):
        raise UnsupportedGeometryError('存在尚未支持的图形层。')
    root = Path(output_dir).resolve().as_posix() if output_dir is not None else '.'
    base = f'{root}/{fp.name}'
    out = ['/* EdaKit M4 candidate. Load in a separate Allegro symbol editor. */',
           '(defun lcsc_build_footprint ()', '  (let ()']
    for ext in ('.dra', '.psm'):
        if manual and ext == '.dra':
            continue
        out.append(f'    (when (isFile "{_s(base + ext)}") (error "EdaKit: output already exists"))')
    if manual:
        out.append('    (unless (axlIsSymbolEditor) (error "EdaKit: create a Package Symbol first"))')
        out.append('    (unless (equal (lowerCase (axlDesignType t)) "package") (error "EdaKit: expected package symbol"))')
        out.append(f'    (unless (equal (lowerCase (simplifyFilename (axlGetDrawingName))) (lowerCase (simplifyFilename "{_s(base)}.dra"))) (error "EdaKit: wrong drawing path"))')
    else:
        out.append(_check(f'(axlOpenDesign ?design "{_s(base)}.dra" ?mode "w" ?noMru t)', 'open design'))
    out.append(_check('(axlSetSymbolType "package")', 'symbol type'))
    out.append(_check('(axlDBChangeDesignUnits "millimeters" 4)', 'units'))
    extents_index = len(out)
    created = set()
    points = []
    for ps in fp.padstacks:
        plated = ps.hole_plated and drill_plated
        data = {'layers':[asdict(l) for l in ps.layers], 'drill':ps.drill_mm, 'plated':plated}
        name = 'EK_' + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:20]
        if name not in created:
            created.add(name)
            drill = 'nil'
            if ps.drill_mm:
                plating = 'PLATED' if plated else 'NON_PLATED'
                drill = f"(make_axlPadStackDrill ?holeType 'CIRCLE_DRILL ?drillDiameter {ps.drill_mm:.4f} ?plating '{plating})"
            pads = []
            for lay in ps.layers:
                figure = {'RECT': 'RECTANGLE', 'CIRCLE': 'CIRCLE', 'OBLONG': 'OVAL'}[lay.shape]
                # Allegro distinguishes a square from a non-square rectangle.
                # Compare dimensions at the same precision emitted to SKILL.
                if lay.shape == 'RECT' and f'{lay.w_mm:.4f}' == f'{lay.h_mm:.4f}':
                    figure = 'SQUARE'
                pads.append(f'(make_axlPadStackPad ?layer "{LAYERS[lay.layer]}" ' +
                            f"?type 'REGULAR ?figure '{figure} ?figureSize {_pt(lay.w_mm, lay.h_mm)})")
            out.append(_check(f'(axlDBCreatePadStack "{name}" {drill} (list {" ".join(pads)}))', 'create padstack'))
            path = _s(f'{root}/{name}.pad')
            out.append(f'    (unless (isFile "{path}")')
            out.append(_check(f'(axlPadstackToDisk "{name}" "{path}")', 'save padstack'))
            out.append('    )')
        pin = 'nil' if ps.name.startswith('@') else (
            f'(make_axlPinText ?number "{_s(ps.name)}" ?offset 0:0 ' +
            '?text (make_axlTextOrientation ?textBlock 1 ?rotation 0.0 ?justify "center"))')
        out.append(_check(f'(axlDBCreatePin "{name}" {_pt(ps.x_mm, ps.y_mm)} {pin} {ps.rotation_deg:.4f})', 'create pin'))
        a = math.radians(ps.rotation_deg)
        for lay in ps.layers:
            if lay.layer not in {'TOP', 'BOTTOM', 'DEFAULT_INTERNAL'}:
                continue
            for x in (-lay.w_mm/2, lay.w_mm/2):
                for y in (-lay.h_mm/2, lay.h_mm/2):
                    points.append((ps.x_mm+x*math.cos(a)-y*math.sin(a), ps.y_mm+x*math.sin(a)+y*math.cos(a)))
    tracks = [p for p in fp.primitives if p.kind == 'TRACK' and p.geom.get('points_mm')]
    circles = [p for p in fp.primitives if p.kind == 'CIRCLE' and 'r_mm' in p.geom]
    for i, (layer, pts) in enumerate(fp.lines):
        width = tracks[i].geom['width_mm'] if i < len(tracks) else 0.12
        coords = ' '.join(_pt(x,y) for x,y in pts)
        out.append(_check(f'(axlDBCreateLine (list {coords}) {width:.4f} "{DRAW[layer]}")', 'line'))
        points.extend(pts)
    for i, (layer, x,y,r) in enumerate(fp.circles):
        width = circles[i].geom['stroke_mm'] if i < len(circles) else 0.12
        out.append(_check(f'(axlDBCreateCircle (list {_pt(x,y)} {r:.4f}) {width:.4f} "{DRAW[layer]}")', 'circle'))
        points.extend(((x-r,y-r),(x+r,y+r)))
    for prim in (p for p in fp.primitives if p.kind == 'ARC'):
        # ARC path semantics are not yet calibrated; preserve the source in validation errors.
        raise UnsupportedGeometryError(f"暂不支持 ARC 圆弧图元: {prim.raw[:160]}")
    for region in fp.solid_regions:
        flat = region.geom['points_mm']
        # Allegro requires an explicitly closed boundary. Normalize at the
        # emitted precision so rounding cannot introduce zero-length edges.
        vertices = []
        for i in range(0, len(flat), 2):
            vertex = tuple(float(f'{v:.4f}') for v in flat[i:i + 2])
            if not vertices or vertex != vertices[-1]:
                vertices.append(vertex)
        if len(vertices) > 1 and vertices[-1] == vertices[0]:
            vertices.pop()
        area2 = sum(a[0]*b[1] - b[0]*a[1]
                    for a, b in zip(vertices, vertices[1:] + vertices[:1]))
        if len(set(vertices)) < 3 or abs(area2) < 1e-12:
            raise UnsupportedGeometryError('填充区域在输出精度下退化，无法生成闭合边界。')
        vertices.append(vertices[0])
        coords = ' '.join(_pt(x, y) for x, y in vertices)
        out.append(_check(
            f'(axlDBCreateShape (axlPathStart (list {coords})) t "{SOLID_DRAW[region.geom["layer"]]}")',
            'solid region'))
        points.extend((flat[i], flat[i + 1]) for i in range(0, len(flat), 2))
    x1, x2 = min(x for x,y in points)-0.2, max(x for x,y in points)+0.2
    y1, y2 = min(y for x,y in points)-0.2, max(y for x,y in points)+0.2
    # New package drawings can have positive-only default extents. Establish
    # geometry bounds in mm before creating any pin, including negative XY.
    ex1, ey1 = min(-10.0, x1-10.0), min(-10.0, y1-10.0)
    ex2, ey2 = max(10.0, x2+10.0), max(10.0, y2+10.0)
    out.insert(extents_index, _check(
        f'(axlDBChangeDesignExtents (list {_pt(ex1,ey1)} {_pt(ex2,ey2)}))',
        'drawing extents'))
    out.append(_check(f'(axlDBCreateRectangle (list {_pt(x1,y1)} {_pt(x2,y2)}) t "PACKAGE GEOMETRY/PLACE_BOUND_TOP")', 'place bound'))
    # Package symbols require a reference designator on the dedicated class;
    # package-geometry text is not a substitute. Keep the Capture prefix.
    for subclass in ('SILKSCREEN_TOP', 'ASSEMBLY_TOP'):
        out.append(_check(
            f'(axlDBCreateText "{_s(prefix)}*" {_pt((x1+x2)/2,y2+1.0)} '
            '(make_axlTextOrientation ?textBlock "1" ?rotation 0.0 ?justify "center") '
            f'"REF DES/{subclass}" nil)', 'reference designator'))
    out.append(_check('(axlSaveDesign ?noMru t)', 'save design'))
    out.append(_check(f'(axlCompileSymbol ?symbol "{_s(base)}")', 'compile package'))
    out.extend(['    t', '  )', ')', '', '(lcsc_build_footprint)', ''])
    return '\n'.join(out)

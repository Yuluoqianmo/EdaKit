"""Allegro 17.2 标准焊盘封装候选脚本，原生结果须上机验收。"""
from __future__ import annotations
import math
import re
from pathlib import Path
from ..easyeda.model import Footprint
from ..errors import UnsupportedGeometryError
from .identity import native_precision, pad_name

LAYERS = {'TOP':'TOP', 'BOTTOM':'BOTTOM', 'DEFAULT_INTERNAL':'DEFAULT_INTERNAL',
          'TOP_SOLDERMASK':'SOLDERMASK_TOP', 'BOTTOM_SOLDERMASK':'SOLDERMASK_BOTTOM',
          'TOP_PASTE':'PASTEMASK_TOP', 'BOTTOM_PASTE':'PASTEMASK_BOTTOM'}
DRAW = {'TOP_SILK':'PACKAGE GEOMETRY/SILKSCREEN_TOP',
        'BOTTOM_SILK':'PACKAGE GEOMETRY/SILKSCREEN_BOTTOM',
        'TOP_ASSEMBLY':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'BOTTOM_ASSEMBLY':'PACKAGE GEOMETRY/ASSEMBLY_BOTTOM',
        'DOCUMENT':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'BOARD_OUTLINE':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'ComponentShapeLayer':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'LeadShapeLayer':'PACKAGE GEOMETRY/ASSEMBLY_TOP',
        'ComponentPolarityLayer':'PACKAGE GEOMETRY/SILKSCREEN_TOP'}
# Outlines and filled graphics must use the same semantic layer mapping.
# Mask artwork is non-copper package geometry; never map copper to assembly.
SOLID_DRAW = {**DRAW,
              'TOP_PASTE': 'PACKAGE GEOMETRY/PASTEMASK_TOP',
              'BOTTOM_PASTE': 'PACKAGE GEOMETRY/PASTEMASK_BOTTOM',
              'TOP_SOLDERMASK': 'PACKAGE GEOMETRY/SOLDERMASK_TOP',
              'BOTTOM_SOLDERMASK': 'PACKAGE GEOMETRY/SOLDERMASK_BOTTOM'}

def _s(s):
    return s.replace('\\', '\\\\').replace('"', '\\"')

def _pt(x, y):
    return f'{x:.4f}:{y:.4f}'

def _check(call, label):
    return f'    (unless {call} (error "EdaKit: {_s(label)} failed"))'

def generate_skill(fp: Footprint, *, drill_plated: bool = True, output_dir: Path | None = None,
                   refdes_prefix: str = "", manual: bool = False) -> str:
    """按本机 algroskill 手册生成脚本；在独立符号编辑器加载，拒绝覆盖输出。"""
    from .coordinates import native_cartesian
    fp = native_precision(native_cartesian(fp))
    prefix = (refdes_prefix or "U").strip().rstrip("?*")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", prefix):
        raise UnsupportedGeometryError(f'无效的器件位号前缀: {refdes_prefix!r}')
    if not fp.name or any(c in fp.name for c in '<>:"/\\|?*\r\n') or fp.name.endswith(('.', ' ')):
        raise UnsupportedGeometryError('封装名称不是有效的单个库文件名。')
    if not fp.padstacks:
        raise UnsupportedGeometryError('封装没有可生成的焊盘。')
    for prim in fp.primitives:
        if prim.kind in {'VIA','COPPERAREA','KEEPOUT'}:
            raise UnsupportedGeometryError(f'暂不支持封装中的 {prim.kind} 电气或禁布区域，不能静默丢弃。')
    numbers = [ps.name for ps in fp.padstacks if not ps.mechanical]
    if (len(numbers) != len(set(numbers)) or
            any(not n or n.startswith('@') or any(c.isspace() or ord(c) < 32 for c in n) for n in numbers)):
        raise UnsupportedGeometryError('封装引脚编号为空、重复或无效；机械孔需独立建模。')
    for region in fp.solid_regions:
        layer = region.geom.get('layer')
        pts = region.geom.get('points_mm') or []
        if region.geom.get('region_type', 'solid') not in {'solid', 'cutout'}:
            raise UnsupportedGeometryError(
                f'不支持的填充区域类型: {region.geom.get("region_type")!r}，层 {layer!r}；不能按实心区域转换。')
        if layer not in SOLID_DRAW:
            raise UnsupportedGeometryError(f'不支持的填充区域层: {layer!r}；不能转换或丢弃该层。')
        if (not region.geom.get('path_supported', True)
                or len(pts) < 6 or len(pts) % 2
                or not all(math.isfinite(v) for v in pts)):
            raise UnsupportedGeometryError(f'填充区域路径无效或暂不支持: {layer!r}。')
    for ps in fp.padstacks:
        if not all(math.isfinite(v) for v in (ps.x_mm, ps.y_mm, ps.rotation_deg, ps.drill_mm,
                ps.slot_width_mm, ps.slot_height_mm, ps.drill_offset_x_mm, ps.drill_offset_y_mm)) or ps.drill_mm < 0 or (not ps.layers and not ps.mechanical):
            raise UnsupportedGeometryError(f'焊盘 {ps.name} 的坐标、钻孔或层无效。')
        if ps.mechanical and (ps.hole_plated or ps.drill_mm <= 0):
            raise UnsupportedGeometryError('无编号机械孔必须是非镀孔且孔径大于零。')
        for lay in ps.layers:
            if lay.layer not in LAYERS or lay.shape not in {'RECT', 'CIRCLE', 'OBLONG', 'ROUNDED_RECT', 'SHAPE'}:
                raise UnsupportedGeometryError(f'焊盘 {ps.name}: 暂不支持 {lay.layer}/{lay.shape}，拒绝近似铜形。')
            if not all(math.isfinite(v) and v > 0 for v in (lay.w_mm, lay.h_mm)):
                raise UnsupportedGeometryError(f'焊盘 {ps.name} 尺寸无效。')
            if lay.shape == 'CIRCLE' and abs(lay.w_mm - lay.h_mm) > 1e-4:
                raise UnsupportedGeometryError(f'焊盘 {ps.name} 圆形宽高不相等。')
            if lay.shape == 'ROUNDED_RECT' and not 0 < lay.radius_mm <= min(lay.w_mm, lay.h_mm)/2:
                raise UnsupportedGeometryError(f'焊盘 {ps.name} 圆角半径缺失或超出范围。')
            if lay.shape == 'SHAPE':
                from .geometry import polygon
                polygon(lay.polygon_mm)
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
        name = pad_name(ps, drill_plated)
        if name not in created:
            created.add(name)
            drill = 'nil'
            if ps.drill_mm:
                plating = 'PLATED' if plated else 'NON_PLATED'
                hole = (f"?holeType 'OVAL_SLOT ?slotSize {_pt(ps.slot_width_mm, ps.slot_height_mm)} ?usage \"SLOT\""
                        if ps.slot_width_mm and ps.slot_height_mm else
                        f"?holeType 'CIRCLE_DRILL ?drillDiameter {ps.drill_mm:.4f}")
                drill = (f"(make_axlPadStackDrill {hole} ?plating '{plating} "
                         f'?offset {_pt(ps.drill_offset_x_mm, ps.drill_offset_y_mm)})')
            pads = []
            for lay in sorted(ps.layers, key=lambda l: l.layer):
                figure = {'RECT': 'RECTANGLE', 'CIRCLE': 'CIRCLE',
                          'OBLONG': 'OBLONG_X' if lay.w_mm > lay.h_mm else 'OBLONG_Y',
                          'ROUNDED_RECT': 'ROUNDED_RECTANGLE', 'SHAPE': ''}[lay.shape]
                if lay.shape == 'OBLONG' and f'{lay.w_mm:.4f}' == f'{lay.h_mm:.4f}':
                    figure = 'CIRCLE'
                # Allegro distinguishes a square from a non-square rectangle.
                # Compare dimensions at the same precision emitted to SKILL.
                if lay.shape == 'RECT' and f'{lay.w_mm:.4f}' == f'{lay.h_mm:.4f}':
                    figure = 'SQUARE'
                extra = ''
                if lay.shape == 'ROUNDED_RECT':
                    extra = f' ?radius {lay.radius_mm:.4f} ?corners "UR-UL-LR-LL"'
                if lay.shape == 'SHAPE':
                    from .shapes import shape_name
                    figure_arg = f'"{shape_name(lay)}"'
                else:
                    figure_arg = "'" + figure
                pads.append(f'(make_axlPadStackPad ?layer "{LAYERS[lay.layer]}" ' +
                            f"?type 'REGULAR ?figure {figure_arg} ?figureSize {_pt(lay.w_mm, lay.h_mm)}{extra})")
            out.append(_check(f'(axlDBCreatePadStack "{name}" {drill} (list {" ".join(pads)}))', 'create padstack'))
            path = _s(f'{root}/{name}.pad')
            out.append(f'    (unless (isFile "{path}")')
            out.append(_check(f'(axlPadstackToDisk "{name}" "{path}")', 'save padstack'))
            out.append('    )')
        pin = 'nil' if ps.mechanical else (
            f'(make_axlPinText ?number "{_s(ps.name)}" ?offset 0:0 ' +
            '?text (make_axlTextOrientation ?textBlock 1 ?rotation 0.0 ?justify "center"))')
        out.append(_check(f'(axlDBCreatePin "{name}" {_pt(ps.x_mm, ps.y_mm)} {pin} {ps.rotation_deg:.4f})', 'create pin'))
        a = math.radians(ps.rotation_deg)
        if ps.drill_mm:
            radius = max(ps.drill_mm, ps.slot_width_mm, ps.slot_height_mm)/2
            points.extend(((ps.x_mm-radius-abs(ps.drill_offset_x_mm), ps.y_mm-radius-abs(ps.drill_offset_y_mm)),
                           (ps.x_mm+radius+abs(ps.drill_offset_x_mm), ps.y_mm+radius+abs(ps.drill_offset_y_mm))))
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
    for prim in (p for p in fp.primitives if p.kind in {'RECT', 'RECTANGLE'}):
        g = prim.geom
        if not all(k in g for k in ('x_mm', 'y_mm', 'x2_mm', 'y2_mm', 'width_mm', 'filled')):
            raise UnsupportedGeometryError('矩形图元字段不完整。')
        x, y, xx, yy, width = (g[k] for k in ('x_mm', 'y_mm', 'x2_mm', 'y2_mm', 'width_mm'))
        if (g.get('layer') not in DRAW or not all(math.isfinite(v) for v in (x, y, xx, yy, width))
                or x == xx or y == yy or width < 0 or (not g['filled'] and width == 0)):
            raise UnsupportedGeometryError('矩形图元层、尺寸或线宽无效。')
        vertices = [(x, y), (xx, y), (xx, yy), (x, yy), (x, y)]
        if g['filled']:
            call = f'(axlDBCreateRectangle (list {_pt(min(x,xx),min(y,yy))} {_pt(max(x,xx),max(y,yy))}) t "{DRAW[g["layer"]]}")'
            out.append(_check(call, 'rectangle fill'))
        if width > 0:
            # A closed line preserves the source stroke width; rectangle API has no width argument.
            coords = ' '.join(_pt(a, b) for a, b in vertices)
            call = f'(axlDBCreateLine (list {coords}) {width:.4f} "{DRAW[g["layer"]]}")'
            out.append(_check(call, 'rectangle outline'))
        for a, b in vertices:
            points.extend(((a-width/2, b-width/2), (a+width/2, b+width/2)))
    for prim in (p for p in fp.primitives if p.kind == 'ARC'):
        g = prim.geom
        if not g.get('arcs') or g.get('layer') not in DRAW:
            raise UnsupportedGeometryError(f"ARC 圆弧无效: {g.get('arc_error', prim.raw[:160])}")
        width = g.get('width_mm', 0.12)
        if not math.isfinite(width) or width <= 0:
            raise UnsupportedGeometryError('ARC 线宽必须大于零')
        for arc in g['arcs']:
            sx, sy = arc['start']
            ex, ey = arc['end']
            if math.hypot(ex-sx, ey-sy) < 1e-8:
                raise UnsupportedGeometryError('ARC 起终点在输出精度下重合，无法确定圆弧')
            radius = max(arc['radius'], math.hypot(ex-sx, ey-sy)/2)
            # Cadence algroskill 03dbcre8: endpoint, clockwise, bigarc, radius.
            out.append('    (let ((path (axlPathStart (list ' + _pt(sx, sy) + '))))')
            out.append(_check(f'(axlPathArcRadius path {width:.4f} {_pt(ex, ey)} '
                              f'{"t" if arc["clockwise"] else "nil"} '
                              f'{"t" if arc["large"] else "nil"} {radius:.8f})', 'arc segment'))
            out.append(_check(f'(axlDBCreatePath path "{DRAW[g["layer"]]}")', 'arc'))
            out.append('    )')
            from ..easyeda.arcs import arc_bounds
            for x, y in arc_bounds(arc):
                points.extend(((x-width/2, y-width/2), (x+width/2, y+width/2)))
    from .geometry import graphic_regions, pieces
    for region_index, (layer, geometry) in enumerate(graphic_regions(fp)):
        from shapely import constrained_delaunay_triangles
        polygons = []
        for poly in pieces(geometry):
            # Graphic layers can forbid void DB objects. Triangulation keeps
            # exact holes without depending on that layer-specific permission.
            polygons.extend(list(constrained_delaunay_triangles(poly).geoms) if poly.interiors else [poly])
        for poly in polygons:
            vertices = list(poly.exterior.coords)
            coords = ' '.join(_pt(x,y) for x,y in vertices)
            out.append(_check(
                f'(axlDBCreateShape (axlPathStart (list {coords})) t "{SOLID_DRAW[layer]}")',
                'solid region').replace('solid region failed', f'solid region failed [{region_index}:{layer}]'))
            points.extend(vertices)
    x1, x2 = min(x for x,y in points)-0.2, max(x for x,y in points)+0.2
    y1, y2 = min(y for x,y in points)-0.2, max(y for x,y in points)+0.2
    # New package drawings can have positive-only default extents. Establish
    # geometry bounds in mm before creating any pin, including negative XY.
    # Whole-mm outward limits avoid 17.2 rejecting extents after its internal
    # mil-to-mm rounding (e.g. 15.1999 mm is not representable at design accuracy).
    ex1, ey1 = math.floor(min(-10.0, x1-10.0)), math.floor(min(-10.0, y1-10.0))
    ex2, ey2 = math.ceil(max(10.0, x2+10.0)), math.ceil(max(10.0, y2+10.0))
    out.insert(extents_index,
        '    (let ((bounds (axlGetParam "paramDesign")->bBox))\n'
        f'      (unless (and (xCoord (car bounds)) <= {x1:.4f} (yCoord (car bounds)) <= {y1:.4f} '
        f'(xCoord (cadr bounds)) >= {x2:.4f} (yCoord (cadr bounds)) >= {y2+2.0:.4f})\n'
        + _check(f'(axlDBChangeDesignExtents (list '
                 f'(list (min (xCoord (car bounds)) {ex1:.4f}) (min (yCoord (car bounds)) {ey1:.4f})) '
                 f'(list (max (xCoord (cadr bounds)) {ex2:.4f}) (max (yCoord (cadr bounds)) {ey2:.4f}))))',
                 'drawing extents') + '\n      )\n    )')
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

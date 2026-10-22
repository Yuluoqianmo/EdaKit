"""Validated polygons in millimeters, with explicit curve tolerance."""
import math
import re

from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
from svgelements import Path, Move, Close, Line

from ..errors import UnsupportedGeometryError

CURVE_TOLERANCE_MM = 0.001


def polygon(points):
    if len(points) < 3 or not all(math.isfinite(v) for p in points for v in p):
        raise UnsupportedGeometryError('多边形坐标无效。')
    clean = []
    for x,y in points:
        point = (round(x,4),round(y,4))
        if not clean or point != clean[-1]:
            clean.append(point)
    if len(set(clean)) < 3:
        raise UnsupportedGeometryError('多边形在输出精度下退化。')
    result = Polygon(clean)
    if not result.is_valid or result.area < 1e-8:
        raise UnsupportedGeometryError('多边形自交或面积退化，无法生成。')
    return result


def path_polygons(path, transform):
    """Flatten SVG curves adaptively; every point is measured in output mm."""
    if not path.strip():
        raise ValueError('空路径')
    # svgelements tolerates unknown trailing input. Validate the entire token
    # stream and command arities before allowing its path interpreter to run.
    number = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    token = re.compile(r'[MmLlHhVvCcSsQqTtAaZz]|'+number)
    tokens = []
    end = 0
    for match in token.finditer(path):
        if path[end:match.start()].strip(' \t\r\n,'):
            raise ValueError('路径含未知字符')
        tokens.append(match.group())
        end = match.end()
    if path[end:].strip(' \t\r\n,') or not tokens or tokens[0] not in ('M','m'):
        raise ValueError('路径起点或末尾无效')
    arities = {'M':2,'L':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'T':2,'A':7,'Z':0}
    index = 0
    while index < len(tokens):
        command = tokens[index]
        if command.upper() not in arities:
            raise ValueError('路径缺少命令')
        index += 1
        values = []
        while index < len(tokens) and tokens[index].upper() not in arities:
            values.append(float(tokens[index])); index += 1
        size = arities[command.upper()]
        if (size and (not values or len(values)%size)) or (not size and values) or not all(map(math.isfinite,values)):
            raise ValueError('路径命令参数数量无效')
        if command.upper() == 'A' and any(values[i] not in (0,1) for j in range(0,len(values),7) for i in (j+3,j+4)):
            raise ValueError('圆弧标志无效')
    result = []
    for subpath in Path(path).as_subpaths():
        points = []
        for segment in subpath:
            if isinstance(segment, Move):
                points.append(transform.pt((segment.end.x, segment.end.y)))
                continue
            if segment.start is None:
                raise ValueError('路径缺少起点')
            def at(t):
                p = segment.point(t)
                return transform.pt((p.x, p.y))
            def subdivide(t0, a, t1, b, depth=0):
                samples = [at(t0 + (t1-t0)*fraction) for fraction in (.25, .5, .75)]
                dx, dy = b[0]-a[0], b[1]-a[1]
                length = math.hypot(dx, dy)
                errors = [abs(dx*(a[1]-p[1])-(a[0]-p[0])*dy)/length
                          if length else math.dist(a, p) for p in samples]
                if max(errors) <= CURVE_TOLERANCE_MM and length <= .5:
                    points.append(b)
                elif depth < 20:
                    middle = (t0+t1)/2
                    subdivide(t0, a, middle, samples[1], depth+1)
                    subdivide(middle, samples[1], t1, b, depth+1)
                else:
                    raise ValueError('曲线超出离散精度或复杂度限制')
            if isinstance(segment, (Line, Close)):
                points.append(at(1))
            else:
                subdivide(0, at(0), 1, at(1))
        clean = []
        for point in points:
            if not clean or math.dist(clean[-1], point) > 1e-9:
                clean.append(point)
        if len(clean) > 1 and math.dist(clean[0], clean[-1]) < 1e-9:
            clean.pop()
        if len(clean) < 3:
            raise ValueError('轮廓至少需要三个顶点')
        result.append(clean)
        if sum(len(p) for p in result) > 20000:
            raise ValueError('区域顶点过多')
    if not result:
        raise ValueError('无有效轮廓')
    return result


def rings_geometry(rings):
    # SVG's default nonzero fill rule. Preserve winding when nested contours
    # encode a void; same-winding inner contours remain solid.
    from shapely.ops import polygonize
    signed = []
    for ring in rings:
        p = polygon(ring)
        signed.append((p, 1 if p.exterior.is_ccw else -1))
    if len(signed) == 1:
        return signed[0][0]
    cells = polygonize(unary_union([p.boundary for p,_ in signed]))
    result = unary_union([cell for cell in cells if sum(direction for p,direction in signed
                        if p.covers(cell.representative_point())) != 0])
    if not result.is_valid or result.is_empty:
        raise UnsupportedGeometryError('填充区域的复合轮廓无效。')
    return result


def pieces(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    raise UnsupportedGeometryError('几何运算结果不是封闭多边形。')


def graphic_regions(footprint):
    regions, cutouts = [], {}
    for region in footprint.solid_regions:
        g = region.geom
        flat = g.get('points_mm', [])
        rings = g.get('rings_mm', [])
        if len(rings) <= 1:
            rings = [[(flat[i],flat[i+1]) for i in range(0,len(flat),2)]]
        geom = rings_geometry(rings)
        if g.get('region_type', 'solid') == 'cutout':
            cutouts.setdefault(g['layer'], []).append(geom)
        else:
            regions.append((g['layer'],geom))
    for layer, holes in cutouts.items():
        if not any(l == layer for l,_ in regions):
            raise UnsupportedGeometryError(f'区域挖空层 {layer} 没有对应的实体区域，无法确认用途。')
    result = [(layer, geom.difference(unary_union(cutouts[layer])) if layer in cutouts else geom)
              for layer,geom in regions]
    from .padstack import is_aperture
    from shapely.geometry import box, Point, LineString
    from shapely.affinity import rotate, translate
    for pad in footprint.pads:
        if not is_aperture(pad):
            continue
        shape = pad.shape.upper()
        if shape in {'POLYGON','REGULAR_POLYGON'}:
            geom = polygon(pad.polygon_mm)
        else:
            w,h = pad.w_mm,pad.h_mm
            if min(w,h) <= 0:
                raise UnsupportedGeometryError('开窗焊盘尺寸无效。')
            if shape == 'RECT':
                geom = box(-w/2,-h/2,w/2,h/2)
            elif shape == 'ROUNDRECT':
                geom = rounded_polygon(w,h,pad.corner_radius_mm)
            elif shape in {'ELLIPSE','OVAL','CIRCLE'}:
                geom = rounded_polygon(w,h,min(w,h)/2)
            else:
                raise UnsupportedGeometryError('不支持的独立开窗形状：'+shape)
            geom = translate(rotate(geom,pad.rotation_deg,origin=(0,0)),pad.x_mm,pad.y_mm)
        result.extend((layer,geom) for layer in pad.layers)
    return result


def rounded_polygon(w, h, radius):
    from shapely.geometry import box, LineString, Point
    if not 0 < radius <= min(w, h)/2:
        raise UnsupportedGeometryError('圆角半径必须大于零且不超过短边一半。')
    # Tangential rounded corners; buffer resolution chosen for <= 1um sagitta.
    steps = max(8, math.ceil(math.pi / (4*math.acos(max(-1, 1-CURVE_TOLERANCE_MM/radius)))))
    x,y = w/2-radius,h/2-radius
    inner = Point(0,0) if x == y == 0 else LineString([(-x,-y),(x,y)]) if x == 0 or y == 0 else box(-x,-y,x,y)
    return inner.buffer(radius, quad_segs=steps)

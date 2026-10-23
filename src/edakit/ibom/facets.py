"""Read Allegro's STEP facet cache without inventing replacement geometry.

The cache stores STEP-local vertices, per-face colors and assembly child
matrices. Units and child placements are baked into millimeter mesh arrays;
the board's STEP installation transform is applied by the viewer afterwards.
"""
import math
from xml.etree import ElementTree as ET


def _numbers(text, count):
    values = [float(v) for v in text.split()]
    if len(values) != count or not all(math.isfinite(v) for v in values):
        raise ValueError('模型缓存坐标无效')
    return values


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _multiply(a, b):
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4))
            for c in range(4) for r in range(4)]


def _color(value):
    if len(value) != 6:
        raise ValueError('模型缓存颜色无效')
    try:
        return [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError as exc:
        raise ValueError('模型缓存颜色无效') from exc


def _normal(vector, transform):
    # Inverse transpose of the assembly's linear matrix, including nonuniform
    # scales. Translation must never affect a surface normal.
    a, b, c = [transform[i:i + 3] for i in (0, 4, 8)]
    def cross(u, v):
        return [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
    cols = [cross(b, c), cross(c, a), cross(a, b)]
    det = sum(a[i]*cols[0][i] for i in range(3))
    if abs(det) < 1e-15:
        raise ValueError('模型缓存法线变换无效')
    out = [sum(cols[k][r]*vector[k] for k in range(3))/det for r in range(3)]
    length = math.hypot(*out)
    if not math.isfinite(length) or length < 1e-15:
        raise ValueError('模型缓存法线无效')
    return [v/length for v in out]


def parse(raw):
    if len(raw) > 25_000_000 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('模型缓存过大或格式不支持')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError('模型缓存 XML 无效') from exc
    if root.tag != 'step-assembly':
        raise ValueError('不是 Allegro STEP 模型缓存')
    nodes = {n.get('id'): n for n in root if n.get('id')}
    meshes = []
    triangle_count = 0

    def visit(shape_id, transform, ancestors):
        nonlocal triangle_count
        if shape_id in ancestors or len(ancestors) > 64:
            raise ValueError('模型缓存装配关系无效')
        node = nodes.get(shape_id)
        if node is None:
            raise ValueError('模型缓存装配引用缺失')
        if node.tag == 'product':
            visit(node.get('shape'), transform, ancestors + [shape_id])
            return
        if node.tag != 'shape':
            raise ValueError('模型缓存装配类型无效')
        # The numeric value in unit is meters per model unit, including
        # inch/custom STEP units; positions in the viewer are millimeters.
        unit = node.get('unit', '').split()
        if len(unit) != 2:
            raise ValueError('模型缓存单位缺失')
        scale = _numbers(unit[1], 1)[0] * 1000
        if scale <= 0:
            raise ValueError('模型缓存单位无效')
        for shell_id in node.get('shell', '').split():
            shell = nodes.get(shell_id)
            if shell is None or shell.tag != 'shell':
                raise ValueError('模型缓存曲面引用缺失')
            vertices = [_numbers(v.get('p', ''), 3) for v in shell.findall('verts/v')]
            positions = []
            for vertex in vertices:
                xyz = [x * scale for x in vertex]
                positions.extend(sum(transform[k * 4 + r] * xyz[k] for k in range(3))
                                 + transform[12 + r] for r in range(3))
            if not all(math.isfinite(v) for v in positions):
                raise ValueError('模型缓存变换无效')
            groups = {}
            normal_groups = {}
            for facets in shell.findall('facets'):
                color = facets.get('color', shell.get('color', '777f86'))
                indices = groups.setdefault(color, [])
                normals = normal_groups.setdefault(color, [])
                for face in facets.findall('f'):
                    try:
                        ids = [int(v) for v in face.get('v', '').split()]
                    except ValueError as exc:
                        raise ValueError('模型缓存三角面无效') from exc
                    if len(ids) != 3 or any(i < 0 or i >= len(vertices) for i in ids):
                        raise ValueError('模型缓存三角面索引无效')
                    indices.extend(ids)
                    corner_normals = face.findall('n')
                    if corner_normals and len(corner_normals) != 3:
                        raise ValueError('模型缓存顶点法线无效')
                    normals.extend([_normal(_numbers(n.get('d', ''), 3), transform)
                                    for n in corner_normals] if corner_normals else [None]*3)
                    triangle_count += 1
                    if triangle_count > 500_000:
                        raise ValueError('模型缓存三角面过多')
            for color, indices in groups.items():
                if indices:
                    attributes = {'position': {'array': positions}}
                    normals = normal_groups[color]
                    if all(n is not None for n in normals):
                        # A STEP corner can have several normals at a sharp edge.
                        # Split such corners instead of smoothing a shared index.
                        split_positions, split_normals, split_indices, seen = [], [], [], {}
                        for index, normal in zip(indices, normals):
                            key = (index, *normal)
                            if key not in seen:
                                seen[key] = len(seen)
                                split_positions.extend(positions[index*3:index*3+3])
                                split_normals.extend(normal)
                            split_indices.append(seen[key])
                        attributes = {'position': {'array': split_positions},
                                      'normal': {'array': split_normals}}
                        indices = split_indices
                    meshes.append({'attributes': attributes,
                                   'index': {'array': indices}, 'color': _color(color)})
        for child in node.findall('child'):
            matrix = _numbers(child.get('xform', ''), 16)
            if matrix[3:12:4] != [0, 0, 0] or matrix[15] != 1:
                raise ValueError('模型缓存矩阵无效')
            # Child translations use the parent's unit; the linear block is
            # dimensionless. Child geometry carries its own unit separately.
            matrix[12:15] = [v * scale for v in matrix[12:15]]
            visit(child.get('ref'), _multiply(transform, matrix), ancestors + [shape_id])

    visit(root.get('root'), IDENTITY, [])
    if not meshes:
        raise ValueError('模型缓存不含三角面')
    return meshes

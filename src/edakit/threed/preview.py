"""Render real OBJ geometry to PNG for Capture's browser without WebGL.

Orthographic projection with a depth buffer and shaded faces; this is a visual
preview, not a mesh measurement or CAD export engine.
"""
from __future__ import annotations

import math
import struct
import zlib
from array import array
from dataclasses import dataclass
from functools import lru_cache
from ..render.scheduling import coalesced, bounded_render



@dataclass(frozen=True)
class Mesh:
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[tuple[int, ...], tuple[float, float, float]], ...]


@lru_cache(maxsize=8)
def parse_obj(data: bytes) -> Mesh:
    if len(data) > 20_000_000:
        raise ValueError("3D 模型过大，无法预览")
    vertices, faces, materials = [], [], {}
    material = ""
    for line in data.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "v" and len(fields) >= 4:
            point = tuple(float(v) for v in fields[1:4])
            if not all(math.isfinite(v) for v in point):
                raise ValueError("3D 模型含无效坐标")
            vertices.append(point)
        elif fields[0] in ("newmtl", "usemtl") and len(fields) > 1:
            material = fields[1]
        elif fields[0] == "Kd" and len(fields) >= 4:
            materials[material] = tuple(max(0, min(1, float(v))) for v in fields[1:4])
        elif fields[0] == "f" and len(fields) >= 4:
            indices = []
            for field in fields[1:]:
                index = int(field.split("/")[0])
                index = index - 1 if index > 0 else len(vertices) + index
                if not 0 <= index < len(vertices):
                    raise ValueError("3D 模型面索引无效")
                indices.append(index)
            faces.append((tuple(indices), material))
        if len(vertices) > 300_000 or len(faces) > 100_000:
            raise ValueError("3D 模型过于复杂，无法预览")
    if not vertices or not faces:
        raise ValueError("未找到可显示的 3D 模型面")
    return Mesh(tuple(vertices), tuple((f, materials.get(m, (0.32, 0.37, 0.42))) for f, m in faces))


@lru_cache(maxsize=8)
def placed_vertices(data, transform):
    from .assembly import rotate
    mesh = parse_obj(data)
    if transform is None:
        return mesh.vertices
    angles, offset = transform
    return tuple(tuple(a+b for a,b in zip(rotate(point, angles), offset)) for point in mesh.vertices)


@coalesced
@lru_cache(maxsize=12)
@bounded_render
def render_model_png(data: bytes, size: int = 1024, yaw: int = 35, pitch: int = 55,
                     transform: tuple | None = None) -> bytes:
    """Depth-buffer rasterization prevents holes from overlapping OBJ triangles.

    Limit 3D bitmaps to 1024px for responsive CPU rendering in the legacy host.
    The viewport can still enlarge them. 2D previews retain their 4096px path.
    """
    size = min(1024, size)
    mesh = parse_obj(data)
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    points = []
    for x, y, z in placed_vertices(data, transform):
        rx, ry = x*cy-y*sy, x*sy+y*cy
        # Native CAD uses Y up; SVG uses Y down. Camera never changes mapping.
        points.append((rx, -(ry*cp+z*sp), z*cp-ry*sp))
    minx, maxx = min(p[0] for p in points), max(p[0] for p in points)
    miny, maxy = min(p[1] for p in points), max(p[1] for p in points)
    extent = max(maxx-minx, maxy-miny, 0.01)*1.18
    left, top = (minx+maxx-extent)/2, (miny+maxy-extent)/2
    projected = [((x-left)*size/extent, (y-top)*size/extent, z) for x,y,z in points]
    pixels = bytearray((247, 250, 252))*(size*size)
    depths = array('f', [float('-inf')])*(size*size)
    for indices, color in mesh.faces:
        for i in range(1, len(indices)-1):
            tri = [projected[j] for j in (indices[0], indices[i], indices[i+1])]
            a,b,c = tri
            # Use world projection for stable light, independent of pixel size.
            world = [points[j] for j in (indices[0], indices[i], indices[i+1])]
            u,v = [world[1][j]-world[0][j] for j in range(3)], [world[2][j]-world[0][j] for j in range(3)]
            n = (u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0])
            norm = math.sqrt(sum(t*t for t in n)) or 1
            shade = 0.48+0.52*abs((-0.3*n[0]-0.4*n[1]+0.86*n[2])/norm)
            rgb = bytes(max(0,min(255,int(t*shade*255))) for t in color)
            for row in range(max(0, math.ceil(min(p[1] for p in tri)-0.5)), min(size, math.ceil(max(p[1] for p in tri)-0.5))):
                y = row+0.5
                hits = []
                for p,q in ((a,b),(b,c),(c,a)):
                    if min(p[1],q[1]) <= y < max(p[1],q[1]):
                        t = (y-p[1])/(q[1]-p[1])
                        hits.append((p[0]+t*(q[0]-p[0]), p[2]+t*(q[2]-p[2])))
                if len(hits) != 2:
                    continue
                (x0,z0),(x1,z1) = sorted(hits)
                if x1-x0 < 1e-10:
                    continue
                dz = (z1-z0)/(x1-x0)
                start,end = max(0,math.ceil(x0-0.5)), min(size,math.ceil(x1-0.5))
                z = z0+(start+0.5-x0)*dz
                offset = row*size+start
                for col in range(start,end):
                    if z > depths[offset]:
                        depths[offset] = z
                        idx = offset*3
                        pixels[idx:idx+3] = rgb
                    offset += 1
                    z += dz
    def chunk(kind, content):
        return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content)&0xffffffff)
    rows = b''.join(b'\0'+pixels[row*size*3:(row+1)*size*3] for row in range(size))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')

"""Decode SVG circular endpoint arcs without discarding source geometry."""
import math
import re


def arc_bounds(arc):
    sx, sy = arc['start']
    ex, ey = arc['end']
    chord = math.hypot(ex-sx, ey-sy)
    radius = max(arc['radius'], chord/2)
    offset = math.sqrt(max(0, radius*radius-chord*chord/4))
    sign = (-1 if arc['clockwise'] else 1) * (-1 if arc['large'] else 1)
    cx = (sx+ex)/2 - (ey-sy)/chord*offset*sign
    cy = (sy+ey)/2 + (ex-sx)/chord*offset*sign
    start = math.atan2(sy-cy, sx-cx)
    end = math.atan2(ey-cy, ex-cx)
    direction = -1 if arc['clockwise'] else 1
    span = ((end-start)*direction) % math.tau
    points = [(sx, sy), (ex, ey)]
    for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
        if ((angle-start)*direction) % math.tau <= span + 1e-9:
            points.append((cx+radius*math.cos(angle), cy+radius*math.sin(angle)))
    return points


def circular_arcs(path, transform):
    number = r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'
    tokens = re.findall(r'[MmAa]|' + number, path)
    residue = re.sub(r'[MmAa]|' + number + r'|[\s,]', '', path)
    if residue or len(tokens) < 11 or tokens[0] != 'M':
        raise ValueError('ARC 路径必须由 M 起点和 A/a 圆弧组成')
    current = tuple(map(float, tokens[1:3]))
    result = []
    i = 3
    command = None
    while i < len(tokens):
        if tokens[i] in ('A', 'a'):
            command = tokens[i]
            i += 1
        if command is None or i + 7 > len(tokens):
            raise ValueError('ARC 路径参数不完整')
        rx, ry, rotation, large, sweep, x, y = map(float, tokens[i:i+7])
        i += 7
        if not all(math.isfinite(v) for v in (*current, rx, ry, rotation, x, y)):
            raise ValueError('ARC 包含无效数值')
        if rx <= 0 or ry <= 0 or abs(rx-ry) > 1e-5 or large not in (0, 1) or sweep not in (0, 1):
            raise ValueError('ARC 目前要求正圆半径和有效方向标志')
        end = (x + current[0], y + current[1]) if command == 'a' else (x, y)
        start_mm, end_mm = transform.pt(current), transform.pt(end)
        chord = math.dist(start_mm, end_mm)
        if chord > 1e-9:
            # SVG requires radii correction when endpoints exceed the diameter.
            radius = max(rx * 0.254, chord / 2)
            result.append({'start': start_mm, 'end': end_mm, 'radius': radius,
                           'large': bool(large), 'clockwise': bool(sweep) == transform.flip_y})
        current = end
    return result

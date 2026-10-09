"""Rasterise the Agent logos in assets/ into <agent>_logo.py RGB565 buffers for blit_buffer.

Each SVG is a set of filled paths. They are flattened to polygons and filled
with the nonzero winding rule, supersampled for anti-aliased edges over black.
Supports the path commands the logos use: M L H V C S A Z, absolute and relative.
"""
import colorsys
import math
import os
import re
import struct

ROOT = os.path.join(os.path.dirname(__file__), "..")
SIZE = 48
SUPERSAMPLE = 4
CURVE_STEPS = 8

# name: (svg, licence note, colour or None to take the SVG's hsl() fill)
LOGOS = {
    "claude": ("claude-logo.svg", "CC0", None),
    "copilot": ("copilot-logo.svg", "GitHub Octicons, MIT: see assets/octicons-LICENSE", (255, 255, 255)),
}


def arc(x1, y1, rx, ry, phi, large, sweep, x2, y2):
    """Points along an SVG elliptical arc, after (x1, y1), per the SVG spec's
    endpoint-to-centre conversion."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    cos, sin = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    xp, yp = cos * dx + sin * dy, -sin * dx + cos * dy
    scale = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
    den = rx * rx * yp * yp + ry * ry * xp * xp
    coef = math.sqrt(max(0, num / den)) * (-1 if large == sweep else 1)
    cxp, cyp = coef * rx * yp / ry, -coef * ry * xp / rx
    cx = cos * cxp - sin * cyp + (x1 + x2) / 2
    cy = sin * cxp + cos * cyp + (y1 + y2) / 2
    start = math.atan2((yp - cyp) / ry, (xp - cxp) / rx)
    end = math.atan2((-yp - cyp) / ry, (-xp - cxp) / rx)
    delta = end - start
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    points = []
    for s in range(1, CURVE_STEPS + 1):
        t = start + delta * s / CURVE_STEPS
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
    return points


def cubic(p0, p1, p2, p3):
    points = []
    for s in range(1, CURVE_STEPS + 1):
        t = s / CURVE_STEPS
        mt = 1 - t
        points.append(tuple(
            mt ** 3 * p0[k] + 3 * mt * mt * t * p1[k] + 3 * mt * t * t * p2[k] + t ** 3 * p3[k] for k in (0, 1)
        ))
    return points


def parse_path(d):
    """Flatten an SVG path into a list of closed polygons, one per subpath."""
    tokens = re.findall(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)", d)
    polygons, pos, start, i, cmd = [], (0.0, 0.0), (0.0, 0.0), 0, None
    last_control = None

    def nums(n):
        nonlocal i
        vals = [float(t) for t in tokens[i:i + n]]
        i += n
        return vals

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                pos, last_control = start, None
                continue
        rel = cmd.islower()
        c = cmd.lower()
        x, y = pos
        control = None
        if c in "ml":
            dx, dy = nums(2)
            pos = (x + dx, y + dy) if rel else (dx, dy)
            if c == "m":
                start = pos
                polygons.append([])
                cmd = "l" if rel else "L"  # further pairs are lines
            polygons[-1].append(pos)
        elif c == "h":
            (v,) = nums(1)
            pos = (x + v if rel else v, y)
            polygons[-1].append(pos)
        elif c == "v":
            (v,) = nums(1)
            pos = (x, y + v if rel else v)
            polygons[-1].append(pos)
        elif c in "cs":
            vals = nums(6 if c == "c" else 4)
            if rel:
                vals = [v + (x if k % 2 == 0 else y) for k, v in enumerate(vals)]
            if c == "c":
                p1, p2, end = (vals[0], vals[1]), (vals[2], vals[3]), (vals[4], vals[5])
            else:
                # The first control point mirrors the previous curve's second one.
                p1 = (2 * x - last_control[0], 2 * y - last_control[1]) if last_control else pos
                p2, end = (vals[0], vals[1]), (vals[2], vals[3])
            polygons[-1].extend(cubic(pos, p1, p2, end))
            pos, control = end, p2
        elif c == "a":
            rx, ry, phi, large, sweep, ex, ey = nums(7)
            end = (x + ex, y + ey) if rel else (ex, ey)
            polygons[-1].extend(arc(x, y, rx, ry, phi, int(large), int(sweep), *end))
            pos = end
        else:
            raise ValueError("unsupported path command " + cmd)
        last_control = control
    return polygons


def winding(polygons, px, py):
    """Nonzero winding number of the point across all polygons."""
    total = 0
    for poly in polygons:
        j = len(poly) - 1
        for k in range(len(poly)):
            (xi, yi), (xj, yj) = poly[k], poly[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                total += 1 if yi > yj else -1
            j = k
    return total


def rasterise(name):
    svg_name, licence, color = LOGOS[name]
    svg = open(os.path.join(ROOT, "assets", svg_name)).read()
    if color is None:
        h, s, l = (float(v) for v in re.search(r"hsl\(([\d.]+),\s*([\d.]+)%,\s*([\d.]+)%\)", svg).groups())
        color = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h / 360, l / 100, s / 100))
    view = float(re.search(r'viewBox="0 0 ([\d.]+)', svg).group(1))
    polygons = [p for d in re.findall(r' d="([^"]+)"', svg) for p in parse_path(d)]

    buf = bytearray()
    n = SUPERSAMPLE
    for row in range(SIZE):
        for col in range(SIZE):
            hits = sum(
                winding(polygons, (col + (sx + 0.5) / n) * view / SIZE, (row + (sy + 0.5) / n) * view / SIZE) != 0
                for sy in range(n) for sx in range(n)
            )
            a = hits / (n * n)
            r, g, b = (int(v * a) for v in color)
            buf += struct.pack(">H", (r & 0xF8) << 8 | (g & 0xFC) << 3 | b >> 3)

    with open(os.path.join(ROOT, name + "_logo.py"), "w") as f:
        f.write("# Generated by tools/make_logo.py from assets/%s (%s). Do not edit.\n" % (svg_name, licence))
        f.write("WIDTH = %d\nHEIGHT = %d\n" % (SIZE, SIZE))
        f.write("COLOR = (%d, %d, %d)\n" % color)
        f.write("BUFFER = %r\n" % bytes(buf))

    # ASCII preview for a quick sanity check.
    print(name)
    for row in range(0, SIZE, 2):
        print("".join(" .:#"[min(3, (buf[(row * SIZE + c) * 2] >> 3) // 8)] for c in range(SIZE)))


def main():
    for name in LOGOS:
        rasterise(name)


if __name__ == "__main__":
    main()

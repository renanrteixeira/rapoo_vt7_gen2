#!/usr/bin/env python3
"""Generates the Rapoo VT7 Battery application icon (Material style).

Vector SVG + PNGs (48/64/128/256/512) installed in the user's hicolor theme.
"""
import os
import re
import sys

import cairo

SIZE = 256

# Material Icons (google) - "mouse" and "bolt", viewBox 24x24
MOUSE = (
    "M13,1.07V9h7C20,4.63 17.04,1.5 13,1.07z "
    "M4,15C4,19.42 7.58,23 12,23s8,-3.58 8,-8v-4H4V15z "
    "M11,1.07C6.96,1.5 4,4.63 4,9h7V1.07z"
)
BOLT = "M7,2v11h3v9l7,-12h-4l4,-8H7z"

BG_TOP = (0.149, 0.651, 0.604)    # #26A69A (Teal 400)
BG_BOTTOM = (0.000, 0.475, 0.420)  # #00796B (Teal 700)
MOUSE_COLOR = (1.0, 1.0, 1.0)
BOLT_COLOR = (1.0, 0.757, 0.027)   # #FFC107 (Amber)

DEFAULT_OUT = os.path.expanduser("~/.local/share/icons/hicolor")
PROJECT_COPY = os.path.join(os.path.dirname(__file__), "..", "assets")


def _tokenize(d):
    toks = []
    i = 0
    while i < len(d):
        c = d[i]
        if c in " \t\n\r,":
            i += 1
            continue
        if c in "MLHVCSQTAZmlhvcsqtaz":
            toks.append(c)
            i += 1
            continue
        m = re.match(r"-?\d*\.?\d+(?:[eE][+-]?\d+)?", d[i:])
        if m:
            toks.append(float(m.group()))
            i += len(m.group())
            continue
        raise ValueError(f"unexpected token: {d[i:]!r}")
    return toks


def trace_path(ctx, d):
    """Interprets an SVG path (subset: M/L/H/V/C/S/Z + lowercase)."""
    toks = _tokenize(d)
    n = len(toks)
    i = 0
    x = y = 0.0
    start_x = start_y = 0.0
    ctrl_x = ctrl_y = 0.0
    prev = ""

    def num():
        nonlocal i
        v = toks[i]
        i += 1
        return v

    def more():
        return i < n and isinstance(toks[i], float)

    while i < n:
        tok = toks[i]
        if isinstance(tok, str):
            prev = tok
            i += 1
        cmd = prev
        if cmd == "M":
            x, y = num(), num()
            start_x, start_y = x, y
            ctx.move_to(x, y)
            while more():
                x, y = num(), num()
                ctx.line_to(x, y)
        elif cmd == "m":
            x += num()
            y += num()
            start_x, start_y = x, y
            ctx.move_to(x, y)
            while more():
                x += num()
                y += num()
                ctx.line_to(x, y)
        elif cmd == "L":
            while more():
                x, y = num(), num()
                ctx.line_to(x, y)
        elif cmd == "l":
            while more():
                x += num()
                y += num()
                ctx.line_to(x, y)
        elif cmd == "H":
            x = num()
            ctx.line_to(x, y)
        elif cmd == "h":
            x += num()
            ctx.line_to(x, y)
        elif cmd == "V":
            y = num()
            ctx.line_to(x, y)
        elif cmd == "v":
            y += num()
            ctx.line_to(x, y)
        elif cmd == "C":
            while i + 6 <= n and all(isinstance(t, float) for t in toks[i : i + 6]):
                x1, y1 = num(), num()
                x2, y2 = num(), num()
                x3, y3 = num(), num()
                ctx.curve_to(x1, y1, x2, y2, x3, y3)
                ctrl_x, ctrl_y = x2, y2
                x, y = x3, y3
        elif cmd == "c":
            while i + 6 <= n and all(isinstance(t, float) for t in toks[i : i + 6]):
                x1, y1 = x + num(), y + num()
                x2, y2 = x + num(), y + num()
                x3, y3 = x + num(), y + num()
                ctx.curve_to(x1, y1, x2, y2, x3, y3)
                ctrl_x, ctrl_y = x2, y2
                x, y = x3, y3
        elif cmd == "S":
            while i + 4 <= n and all(isinstance(t, float) for t in toks[i : i + 4]):
                if prev in ("C", "c", "S", "s"):
                    x1, y1 = 2 * x - ctrl_x, 2 * y - ctrl_y
                else:
                    x1, y1 = x, y
                x2, y2 = num(), num()
                x3, y3 = num(), num()
                ctx.curve_to(x1, y1, x2, y2, x3, y3)
                ctrl_x, ctrl_y = x2, y2
                x, y = x3, y3
        elif cmd == "s":
            while i + 4 <= n and all(isinstance(t, float) for t in toks[i : i + 4]):
                if prev in ("C", "c", "S", "s"):
                    x1, y1 = 2 * x - ctrl_x, 2 * y - ctrl_y
                else:
                    x1, y1 = x, y
                x2, y2 = x + num(), y + num()
                x3, y3 = x + num(), y + num()
                ctx.curve_to(x1, y1, x2, y2, x3, y3)
                ctrl_x, ctrl_y = x2, y2
                x, y = x3, y3
        elif cmd == "Z" or cmd == "z":
            ctx.close_path()
            x, y = start_x, start_y
        else:
            raise ValueError(f"unsupported command: {cmd!r}")
    return


def _rounded_rect(ctx, x, y, w, h, r):
    import math

    ctx.new_sub_path()
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.close_path()


def _glyph(ctx, path, scale, cx, cy, color):
    ctx.save()
    ctx.translate(cx - 12 * scale, cy - 12 * scale)
    ctx.scale(scale, scale)
    ctx.new_path()
    trace_path(ctx, path)
    ctx.set_source_rgba(*color)
    ctx.fill()
    ctx.restore()


def draw(ctx):
    # background: rounded square with teal gradient
    grad = cairo.LinearGradient(0, 0, SIZE, SIZE)
    grad.add_color_stop_rgb(0.0, *BG_TOP)
    grad.add_color_stop_rgb(1.0, *BG_BOTTOM)
    _rounded_rect(ctx, 0, 0, SIZE, SIZE, 56)
    ctx.set_source(grad)
    ctx.fill()

    # soft gloss on the top-left corner
    _rounded_rect(ctx, 0, 0, SIZE, SIZE, 56)
    gloss = cairo.RadialGradient(96, 72, 20, 96, 72, 300)
    gloss.add_color_stop_rgba(0.0, 1, 1, 1, 0.14)
    gloss.add_color_stop_rgba(0.5, 1, 1, 1, 0.03)
    gloss.add_color_stop_rgba(1.0, 1, 1, 1, 0)
    ctx.set_source(gloss)
    ctx.fill()

    # thin outline to stand out on light/dark themes
    _rounded_rect(ctx, 0, 0, SIZE, SIZE, 56)
    ctx.set_source_rgba(0, 0, 0, 0.08)
    ctx.set_line_width(2)
    ctx.stroke()

    # mouse (Material) + lightning bolt (battery/charging)
    _glyph(ctx, MOUSE, 6.4, 128, 142, MOUSE_COLOR)
    _glyph(ctx, BOLT, 3.0, 128, 138, BOLT_COLOR)


def write_png(path, size):
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surf)
    ctx.scale(size / SIZE, size / SIZE)
    draw(ctx)
    surf.write_to_png(path)
    surf.finish()


def write_svg(path):
    surf = cairo.SVGSurface(path, SIZE, SIZE)
    ctx = cairo.Context(surf)
    draw(ctx)
    surf.finish()


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    sizes = (48, 64, 128, 256, 512)
    for size in sizes:
        d = os.path.join(out, f"{size}x{size}", "apps")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "rapoo-vt7.png")
        write_png(p, size)
        print(f"PNG {size}x{size}: {p}")
    d = os.path.join(out, "scalable", "apps")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "rapoo-vt7.svg")
    write_svg(p)
    print(f"SVG: {p}")

    os.makedirs(PROJECT_COPY, exist_ok=True)
    write_svg(os.path.join(PROJECT_COPY, "rapoo-vt7.svg"))
    print(f"SVG copy: {os.path.join(PROJECT_COPY, 'rapoo-vt7.svg')}")

    os.system("gtk-update-icon-cache -f -t %s 2>/dev/null" % out)


if __name__ == "__main__":
    main()

import os

import cairo

ICON_W = 46
ICON_H = 24
ICON_PREFIX = "rapoo_mouse_"

DEFAULT_ICON_DIR = os.path.expanduser("~/.cache/rapoo-vt7/icons")

# Mouse (Material style) on the left, percentage number beside it.
_MOUSE = (1.0, 4.0, 13.0, 16.0)
_TEXT_X = 18.0
_TEXT_MAX_W = 27.0


def color_for(percent):
    if percent >= 50:
        return (0.30, 0.69, 0.31)
    if percent >= 20:
        return (0.96, 0.76, 0.05)
    return (0.95, 0.26, 0.21)


def icon_name(percent, charging=False):
    suffix = "_chg" if charging else ""
    return f"{ICON_PREFIX}{int(percent):03d}{suffix}"


UNKNOWN_NAME = f"{ICON_PREFIX}unknown"


def _round_rect(ctx, x, y, w, h, radius):
    ctx.new_path()
    ctx.move_to(x + radius, y)
    ctx.line_to(x + w - radius, y)
    ctx.arc(x + w - radius, y + radius, radius, -1.5708, 0)
    ctx.line_to(x + w, y + h - radius)
    ctx.arc(x + w - radius, y + h - radius, radius, 0, 1.5708)
    ctx.line_to(x + radius, y + h)
    ctx.arc(x + radius, y + h - radius, radius, 1.5708, 3.14159)
    ctx.line_to(x, y + radius)
    ctx.arc(x + radius, y + radius, radius, 3.14159, 4.71239)
    ctx.close_path()


def _bolt(ctx, cx, cy, w, h):
    x0 = cx - w / 2
    pts = [
        (x0 + 0.60 * w, cy - h / 2),
        (x0 + 0.20 * w, cy),
        (x0 + 0.45 * w, cy),
        (x0 + 0.30 * w, cy + h / 2),
        (x0 + 0.85 * w, cy - h / 2 * 0.3),
        (x0 + 0.55 * w, cy - h / 2 * 0.3),
        (x0 + 0.75 * w, cy - h / 2),
    ]
    ctx.move_to(*pts[0])
    for pt in pts[1:]:
        ctx.line_to(*pt)
    ctx.close_path()


def _material_mouse(ctx, color):
    """Flat Material-style mouse outline, filled with the battery color."""
    x, y, w, h = _MOUSE
    ctx.set_source_rgba(*(color + (0.95,)))
    _round_rect(ctx, x, y, w, h, 4.5)
    ctx.fill()

    # Cut-outs (button slit + wheel notch) in the background colour.
    ctx.set_operator(cairo.OPERATOR_CLEAR)
    slit = (x + 3.0, y + h * 0.30, w - 6.0, 1.0)
    _round_rect(ctx, *slit, 0.5)
    ctx.fill()
    wheel = (x + w / 2 - 1.6, y + h * 0.40, 3.2, 3.0)
    _round_rect(ctx, *wheel, 1.2)
    ctx.fill()
    ctx.set_operator(cairo.OPERATOR_OVER)


def _draw_number(ctx, text, color, charging=False):
    ctx.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(12.0)
    xb, yb, tw, th, _, _ = ctx.text_extents(text)
    if tw > _TEXT_MAX_W:
        ctx.set_font_size(max(7.0, 12.0 * _TEXT_MAX_W / max(tw, 1.0)))
        xb, yb, tw, th, _, _ = ctx.text_extents(text)
    cx = _TEXT_X + (ICON_W - _TEXT_X) / 2 - tw / 2 - xb
    cy = (ICON_H - th) / 2 - yb
    if charging:
        # Bolt between the mouse and the number.
        _bolt(ctx, (_TEXT_X + cx) / 2, ICON_H / 2, 4.5, 7.0)
        ctx.set_source_rgba(0.98, 0.82, 0.05, 0.95)
        ctx.set_line_width(1.0)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke_preserve()
        ctx.fill()
    ctx.set_source_rgba(*(color + (1,)))
    ctx.move_to(cx, cy)
    ctx.show_text(text)


def _percent_text(percent):
    return "%d%%" % max(0, min(100, int(percent)))


def render(percent, path, charging=False):
    percent = max(0, min(100, int(percent)))
    color = color_for(percent)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_W, ICON_H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()

    _material_mouse(ctx, color)
    _draw_number(ctx, _percent_text(percent), color, charging=charging)

    surface.write_to_png(path)
    surface.finish()


def render_unknown(path):
    color = (0.55, 0.55, 0.55)

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, ICON_W, ICON_H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(0, 0, 0, 0)
    ctx.paint()

    _material_mouse(ctx, color)
    _draw_number(ctx, "--%", color)

    surface.write_to_png(path)
    surface.finish()


def render_all(directory=DEFAULT_ICON_DIR):
    os.makedirs(directory, exist_ok=True)
    for percent in range(0, 101):
        for charging in (False, True):
            path = os.path.join(directory, icon_name(percent, charging) + ".png")
            if not os.path.exists(path):
                render(percent, path, charging=charging)
    unknown = os.path.join(directory, UNKNOWN_NAME + ".png")
    if not os.path.exists(unknown):
        render_unknown(unknown)
    return directory

import math
import os
import time

import cairo

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, Gtk, Gdk, GdkPixbuf

from . import buttons, dpi, i18n, parameters, performance as perf

# Product render shown in the battery tab. Resolved relative to this package
# (repo layout: <root>/assets/mouse2.png) so it also works from an install.
_MOUSE_IMAGE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets",
    "mouse2.png",
)
_mouse_pixbuf_cache = None  # None = not tried yet, False = load failed


def _mouse_pixbuf():
    """Lazy-loads the battery-tab mouse image (False cached on failure)."""
    global _mouse_pixbuf_cache
    if _mouse_pixbuf_cache is None:
        try:
            _mouse_pixbuf_cache = GdkPixbuf.Pixbuf.new_from_file(_MOUSE_IMAGE_PATH)
        except Exception:
            _mouse_pixbuf_cache = False
    return _mouse_pixbuf_cache if _mouse_pixbuf_cache is not False else None


def _draw_image_fit(cr, pb, w, h, pad=16):
    """Draws `pb` centered, scaled to fit (aspect preserved), with padding."""
    iw, ih = pb.get_width(), pb.get_height()
    if not iw or not ih:
        return
    box_w = max(w - 2 * pad, 1)
    box_h = max(h - 2 * pad, 1)
    scale = min(box_w / iw, box_h / ih)
    sw = max(int(iw * scale), 1)
    sh = max(int(ih * scale), 1)
    scaled = pb.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
    Gdk.cairo_set_source_pixbuf(cr, scaled, (w - sw) / 2, (h - sh) / 2)
    cr.paint()


def _round_rect(ctx, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.close_path()


def params_render_plan(info, error):
    """Pure §C widget-state plan (no GTK, headless-testable).

    `info` is a `parameters.read_section` payload (or None) and `error` a
    section-level error string (or None). Returns (checks, selects,
    read_onlys) where `checks` maps toggle name -> (active, sensitive),
    `selects` maps selectable-param name -> (display value on the step grid
    or None, sensitive) and `read_onlys` maps state-row name -> display text.
    On error the last-known values are retained (never nulled) and every
    input is disabled. A raw byte outside the A Hub range, or between two
    grid steps, never leaves the slider at a stale/misleading position: it
    is snapped to the grid when representable and disabled otherwise.
    """
    checks = {}
    selects = {}
    read_onlys = {}
    known = info.get("params", {}) if info else {}
    for name, _o, editable in parameters.PARAMS:
        p = known.get(name)
        if editable:
            checks[name] = (
                (bool(p["raw"]) if p else False),
                error is None and p is not None,
            )
        elif parameters.is_selectable(name):
            p_ok = error is None and p is not None
            display = parameters.byte_to_display(name, p["raw"]) if p else None
            if display is not None:
                lo, hi, step = parameters.param_range(name)
                if not (lo - 1e-9 <= display <= hi + 1e-9):
                    display = None
                else:
                    display = min(
                        lo + int(round((display - lo) / step)) * step, hi
                    )
            selects[name] = (display, p_ok and display is not None)
        else:
            read_onlys[name] = _param_state_text(name, p)
    return checks, selects, read_onlys


def _param_state_text(name, p):
    """Display text of a read-only §C row (raw int; the remaining §C fields
    have no confirmed unit, so they render unit-less)."""
    if p is None:
        return "--"
    return "%d" % p["raw"]


def params_status_text(t, info, error):
    """Pure §C status-line decision: returns (text, is_error). When several
    §C bytes break at once the line aggregates the remaining count."""
    if error is not None:
        return t("param_error").format(error=error), True
    if info is None:
        return t("param_unknown"), False
    errs = info.get("errors", {})
    if errs:
        first = next(iter(errs.values()))
        extra = len(errs) - 1
        line = t("param_error").format(error=first)
        if extra > 0:
            line += t("param_more_errors").format(n=extra)
        return line, True
    return "", False


def buttons_render_plan(info, error):
    """Pure per-button combo plan (no GTK, headless-testable).

    `info` is a `buttons.read_section` payload (or None) and `error` a
    section-level error string (or None). Returns (status, pickers) where
    `status` is (text, is_error) and `pickers` maps button name ->
    (current_fn_or_None, raw_hex_or_None, sensitive). On error the last-known
    values are retained (never nulled) and every picker is disabled.
    """
    if error is not None:
        status = ("buttons_error", True, {"error": error})
    elif info is None:
        status = ("buttons_unknown", False, {})
    else:
        errs = info.get("errors", {})
        if errs:
            first = next(iter(errs.values()))
            extra = len(errs) - 1
            if extra > 0:
                text = ("buttons_error", True, {"error": first + "+%d" % extra})
            else:
                text = ("buttons_error", True, {"error": first})
            status = text
        else:
            status = ("buttons_status", False, {"n": len(buttons.BUTTONS)})
    pickers = {}
    for name, _offset in buttons.BUTTONS:
        state = info["buttons"].get(name) if info is not None else None
        if state is None:
            pickers[name] = (None, None, False)
        else:
            pickers[name] = (
                state["fn"],
                state["raw_hex"],
                error is None and name not in info.get("errors", {}),
            )
    return status, pickers


def perf_rate_state(info, error):
    """Pure polling-rate radio plan: (active_slot_or_None, sensitive).

    On a tab-level error the radios are disabled but the last known rate
    stays marked (`info` is retained, never nulled — same policy as the §C
    toggles). No data -> nothing marked, radios disabled.
    """
    if error is not None:
        slot = info.get("slot") if info else None
        return slot, False
    if info is None:
        return None, False
    return info["slot"], True


def rf_radio_state(info, error, rf_error):
    """Pure RF radio plan: (strengthen_active_or_None, sensitive).

    The currently-set strategy is always the marked radio (None = adaptive,
    True = maximum RF). Tab-level and isolated RF-read errors disable the
    pair; the last-known state is kept marked when available.
    """
    if error is not None:
        rf = info.get("rf") if info else None
        return (bool(rf["rf_strengthen_switch"]) if rf else None), False
    if info is None:
        return None, False
    rf = info.get("rf")
    if rf_error is not None or rf is None:
        return (bool(rf["rf_strengthen_switch"]) if rf else None), False
    return bool(rf["rf_strengthen_switch"]), True


def perf_mode_name(t, mode):
    """Localized label of a performance-mode id, with a safe fallback.

    The device may hold a foreign/corrupt mode byte outside the valid 0..5
    range (`read_mode` returns it unvalidated); rendering must never KeyError.
    """
    if isinstance(mode, int) and 0 <= mode < perf.PERF_MODE_COUNT:
        return t("perf_mode_%d" % mode)
    return t("perf_mode_unknown")


def draw_mouse(ctx, w, h):
    """Stylized mouse (top view) on a 260x170 virtual canvas."""
    scale = min(w / 260.0, h / 170.0)
    ctx.save()
    ctx.translate(w / 2, h / 2)
    ctx.scale(scale, scale)
    ctx.translate(-130, -85)

    # shadow on the floor
    ctx.save()
    ctx.translate(130, 150)
    ctx.scale(1.0, 0.16)
    ctx.arc(0, 0, 55, 0, 2 * math.pi)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.20)
    ctx.fill()

    # body (ergonomic shape, nose at the top)
    ctx.new_path()
    ctx.move_to(120, 24)
    ctx.curve_to(154, 24, 176, 42, 184, 66)
    ctx.curve_to(192, 90, 187, 118, 170, 130)
    ctx.curve_to(155, 140, 135, 145, 120, 145)
    ctx.curve_to(105, 145, 85, 140, 70, 130)
    ctx.curve_to(53, 118, 48, 90, 56, 66)
    ctx.curve_to(64, 42, 86, 24, 120, 24)
    ctx.close_path()

    grad = cairo.LinearGradient(120, 24, 120, 145)
    grad.add_color_stop_rgb(0.0, 0.34, 0.35, 0.38)
    grad.add_color_stop_rgb(0.5, 0.22, 0.22, 0.24)
    grad.add_color_stop_rgb(1.0, 0.12, 0.12, 0.14)
    ctx.set_source(grad)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.05, 0.05, 0.06, 1)
    ctx.set_line_width(1.2)
    ctx.stroke_preserve()

    # soft gloss on the back
    ctx.save()
    ctx.clip_preserve()
    gloss = cairo.RadialGradient(120, 52, 8, 120, 52, 80)
    gloss.add_color_stop_rgba(0, 1, 1, 1, 0.16)
    gloss.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(gloss)
    ctx.paint()
    ctx.restore()

    # button divider line
    ctx.new_path()
    ctx.move_to(120, 27)
    ctx.line_to(120, 56)
    ctx.set_source_rgba(0.08, 0.08, 0.09, 1)
    ctx.set_line_width(1.4)
    ctx.stroke()

    # scroll wheel
    _round_rect(ctx, 108, 58, 24, 9, 3)
    ctx.set_source_rgba(0.08, 0.09, 0.10, 1)
    ctx.fill()
    ctx.set_source_rgba(0.62, 0.64, 0.68, 1)
    for x in (113, 117, 121):
        ctx.new_path()
        ctx.move_to(x, 60)
        ctx.line_to(x, 65)
        ctx.set_line_width(1.0)
        ctx.stroke()

    # DPI button
    _round_rect(ctx, 111, 74, 18, 6, 2)
    ctx.set_source_rgba(0.28, 0.29, 0.32, 1)
    ctx.fill()

    # left side buttons
    _round_rect(ctx, 62, 92, 12, 13, 3)
    ctx.set_source_rgba(0.26, 0.27, 0.30, 1)
    ctx.fill()
    _round_rect(ctx, 62, 108, 12, 11, 3)
    ctx.set_source_rgba(0.24, 0.25, 0.28, 1)
    ctx.fill()

    ctx.restore()


class BatteryWindow:
    def __init__(
        self,
        lang="pt_BR",
        on_lang_change=None,
        application=None,
        on_switch_gear=None,
        on_add_gear=None,
        on_delete_gear=None,
        on_set_value=None,
        on_set_perf=None,
        on_set_rf=None,
        on_set_param=None,
        on_set_rate=None,
        on_set_param_choice=None,
        on_set_button=None,
    ):
        self._lang = lang if lang in i18n.LANGS else "pt_BR"
        self._on_lang_change = on_lang_change
        self._on_switch_gear = on_switch_gear
        self._cb_add_gear = on_add_gear
        self._cb_delete_gear = on_delete_gear
        self._on_set_value = on_set_value
        self._on_set_perf = on_set_perf
        self._on_set_rf = on_set_rf
        self._on_set_param = on_set_param
        self._on_set_rate = on_set_rate
        self._on_set_param_choice = on_set_param_choice
        self._on_set_button = on_set_button
        self._known = False
        self._asleep = False
        self._last = None
        self._dpi = None
        self._dpi_error = None
        self._dpi_timers = {}
        self._dpi_loading = False
        self._perf = None
        self._perf_error = None
        self._perf_loading = False
        self._perf_radio = []
        self._rate_radio = []
        self._params = None
        self._params_error = None
        self._buttons = None
        self._buttons_error = None
        self._buttons_loading = False
        self._button_combos = {}

        if application is not None:
            self._win = Gtk.ApplicationWindow(application=application)
        else:
            self._win = Gtk.Window()
        self._win.set_icon_name("rapoo-vt7")
        self._win.set_title(self._t("window_title"))
        self._win.set_default_size(380, 520)
        self._win.set_position(Gtk.WindowPosition.CENTER)
        self._win.connect("delete-event", self._on_close)

        # Two tabs: Battery (image + info + language) | DPI settings.
        self._notebook = Gtk.Notebook()
        self._tab_battery = Gtk.Label(label=self._t("tab_battery"))
        self._tab_dpi = Gtk.Label(label=self._t("tab_dpi"))
        self._win.add(self._notebook)

        page1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page1.set_margin_top(16)
        page1.set_margin_bottom(16)
        page1.set_margin_start(16)
        page1.set_margin_end(16)
        self._notebook.append_page(page1, self._tab_battery)

        page2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page2.set_margin_top(16)
        page2.set_margin_bottom(16)
        page2.set_margin_start(16)
        page2.set_margin_end(16)
        self._notebook.append_page(page2, self._tab_dpi)

        self._area = Gtk.DrawingArea()
        self._area.set_size_request(300, 180)
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self._area.connect("draw", self._on_draw)
        page1.pack_start(self._area, True, True, 0)

        self._status_label = Gtk.Label()
        self._status_label.set_justify(Gtk.Justification.CENTER)
        self._status_label.set_line_wrap(True)
        self._status_label.set_halign(Gtk.Align.CENTER)
        page1.pack_start(self._status_label, False, False, 4)

        self._detail_label = Gtk.Label()
        self._detail_label.set_halign(Gtk.Align.CENTER)
        page1.pack_start(self._detail_label, False, False, 0)

        lang_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lang_row.set_halign(Gtk.Align.CENTER)
        lang_row.set_margin_top(12)
        self._lang_label = Gtk.Label(label=self._t("language_label"))
        lang_row.pack_start(self._lang_label, False, False, 0)

        self._combo = Gtk.ComboBoxText()
        for code, data in i18n.LANGS.items():
            self._combo.append(code, f"{data['flag']} {data['name']}")
        self._combo.set_active_id(self._lang)
        self._combo.connect("changed", self._on_lang_changed)
        lang_row.pack_start(self._combo, False, False, 0)
        page1.pack_start(lang_row, False, False, 0)

        self._build_dpi_section(page2)

        page3_scroll = Gtk.ScrolledWindow()
        page3_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page3.set_margin_top(16)
        page3.set_margin_bottom(16)
        page3.set_margin_start(16)
        page3.set_margin_end(16)
        page3_scroll.add(page3)
        self._tab_perf = Gtk.Label(label=self._t("tab_perf"))
        self._notebook.append_page(page3_scroll, self._tab_perf)
        self._build_perf_section(page3)

        page4_scroll = Gtk.ScrolledWindow()
        page4_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page4 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page4.set_margin_top(16)
        page4.set_margin_bottom(16)
        page4.set_margin_start(16)
        page4.set_margin_end(16)
        page4_scroll.add(page4)
        self._tab_params = Gtk.Label(label=self._t("tab_params"))
        self._notebook.append_page(page4_scroll, self._tab_params)
        self._build_params_section(page4)

        page5_scroll = Gtk.ScrolledWindow()
        page5_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        page5 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page5.set_margin_top(16)
        page5.set_margin_bottom(16)
        page5.set_margin_start(16)
        page5.set_margin_end(16)
        page5_scroll.add(page5)
        self._tab_buttons = Gtk.Label(label=self._t("tab_buttons"))
        self._notebook.append_page(page5_scroll, self._tab_buttons)
        self._build_buttons_section(page5)
        self._render()

    def _t(self, key):
        return i18n.LANGS[self._lang][key]

    # --- DPI section ---

    def _build_dpi_section(self, vbox):
        self._dpi_title = Gtk.Label()
        self._dpi_title.set_markup("<b>%s</b>" % GLib.markup_escape_text(self._t("dpi_section")))
        self._dpi_title.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._dpi_title, False, False, 0)

        self._dpi_status = Gtk.Label()
        self._dpi_status.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._dpi_status, False, False, 2)

        self._dpi_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self._dpi_grid.set_halign(Gtk.Align.CENTER)
        self._dpi_grid.set_margin_top(4)
        vbox.pack_start(self._dpi_grid, False, False, 0)

        self._dpi_add_btn = Gtk.Button(label=self._t("dpi_add"))
        self._dpi_add_btn.set_halign(Gtk.Align.CENTER)
        self._dpi_add_btn.set_margin_top(6)
        self._dpi_add_btn.set_sensitive(False)
        self._dpi_add_btn.connect("clicked", self._on_add_gear)
        vbox.pack_start(self._dpi_add_btn, False, False, 0)

        self._dpi_msg = Gtk.Label()
        self._dpi_msg.set_line_wrap(True)
        self._dpi_msg.set_halign(Gtk.Align.CENTER)
        self._dpi_msg.set_margin_top(6)
        vbox.pack_start(self._dpi_msg, False, False, 0)

    def _build_perf_section(self, vbox):
        self._perf_title = Gtk.Label()
        self._perf_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("perf_section"))
        )
        self._perf_title.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._perf_title, False, False, 0)

        self._perf_status = Gtk.Label()
        self._perf_status.set_halign(Gtk.Align.CENTER)
        self._perf_status.set_line_wrap(True)
        vbox.pack_start(self._perf_status, False, False, 2)

        self._perf_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._perf_box.set_margin_top(6)
        vbox.pack_start(self._perf_box, False, False, 0)

        group = None
        for mode in perf.PERF_MODES:
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, self._t(mode["key"])
            )
            radio.set_active(False)
            radio.connect("toggled", self._on_perf_toggled, mode["index"])
            group = radio
            self._perf_radio.append(radio)
            self._perf_box.pack_start(radio, False, False, 0)

        # Polling rate: a radio per slot (125..8000 Hz); the radio of the
        # currently-set rate is always the marked one (report 7 rpt_usb /
        # 0x0880 -> slot). Changing it writes the rateCode to MOUSE_REPORT.
        self._rate_title = Gtk.Label()
        self._rate_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("perf_rate_section"))
        )
        self._rate_title.set_halign(Gtk.Align.CENTER)
        self._rate_title.set_margin_top(8)
        vbox.pack_start(self._rate_title, False, False, 0)

        self._rate_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._rate_box.set_margin_top(4)
        vbox.pack_start(self._rate_box, False, False, 0)

        group = None
        for i, hz in enumerate(perf.RATE_HZ):
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, "%d Hz" % hz
            )
            radio.set_active(False)
            radio.connect("toggled", self._on_rate_toggled, hz)
            group = radio
            self._rate_radio.append(radio)
            self._rate_box.pack_start(radio, False, False, 0)

        # RF strategy + low-battery warning: shared byte 0x08D8 (state +
        # masked-write toggles; unrelated bits are preserved on write). The RF
        # strategy is a radio pair (Adaptive | Maximum) with the current one
        # always marked; the warning stays an on/off checkbox.
        self._rf_title = Gtk.Label()
        self._rf_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("rf_section"))
        )
        self._rf_title.set_halign(Gtk.Align.CENTER)
        self._rf_title.set_margin_top(8)
        vbox.pack_start(self._rf_title, False, False, 0)

        self._rf_status = Gtk.Label()
        self._rf_status.set_halign(Gtk.Align.CENTER)
        self._rf_status.set_line_wrap(True)
        vbox.pack_start(self._rf_status, False, False, 2)

        self._rf_radio = []
        group = None
        for active_full, key in ((False, "rf_radio_adaptive"), (True, "rf_radio_full")):
            radio = Gtk.RadioButton.new_with_label_from_widget(
                group, self._t(key)
            )
            radio.set_active(False)
            radio.connect("toggled", self._on_rf_toggled)
            group = radio
            self._rf_radio.append(radio)
            vbox.pack_start(radio, False, False, 0)

        self._rf_lowpow = Gtk.CheckButton(label=self._t("rf_low_toggle"))
        self._rf_lowpow.set_active(False)
        self._rf_lowpow.connect("toggled", self._on_rf_low_toggled)
        vbox.pack_start(self._rf_lowpow, False, False, 0)

    def _build_params_section(self, vbox):
        # Section C mouse parameters: a checkbox per CONFIRMED toggle (motion
        # sync, glass tracking, DC switch — validated on the device) and a
        # read-only state row for the numeric/unconfirmed bytes (parameters,
        # never guesswork toggles).
        self._param_title = Gtk.Label()
        self._param_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("param_section"))
        )
        self._param_title.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._param_title, False, False, 0)

        self._param_status = Gtk.Label()
        self._param_status.set_halign(Gtk.Align.CENTER)
        self._param_status.set_line_wrap(True)
        vbox.pack_start(self._param_status, False, False, 2)

        self._param_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._param_box.set_margin_top(4)
        self._param_check = {}
        self._param_state = {}
        self._param_readonly = set()
        self._param_timers = {}
        for name, _offset, editable in parameters.PARAMS:
            if editable:
                cb = Gtk.CheckButton(label=self._t("param_" + name))
                cb.set_active(False)
                cb.connect("toggled", self._on_param_toggled, name)
                self._param_check[name] = cb
                self._param_box.pack_start(cb, False, False, 0)
            else:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                lbl = Gtk.Label(label=self._t("param_" + name))
                lbl.set_halign(Gtk.Align.START)
                if parameters.is_selectable(name):
                    lo, hi, step = parameters.param_range(name)
                    scale = Gtk.Scale.new_with_range(
                        Gtk.Orientation.HORIZONTAL, lo, hi, step
                    )
                    scale.set_digits(parameters.param_digits(name))
                    scale.set_draw_value(True)
                    scale.set_value_pos(Gtk.PositionType.RIGHT)
                    scale.set_size_request(140, -1)
                    scale.set_hexpand(True)
                    scale.set_tooltip_text(
                        parameters.choice_label(name, lo)
                        + " \u2013 "
                        + parameters.choice_label(name, hi)
                    )
                    scale.connect("value-changed", self._on_param_scale, name)
                    widget = scale
                else:
                    widget = Gtk.Label()
                    widget.set_halign(Gtk.Align.END)
                    widget.set_tooltip_text(self._t("param_read_only"))
                    self._param_readonly.add(name)
                row.pack_start(lbl, True, True, 0)
                row.pack_start(widget, False, False, 0)
                self._param_state[name] = (lbl, widget)
                if name == "low_power":
                    lbl.set_tooltip_text(self._t("param_low_power_tt"))
                self._param_box.pack_start(row, False, False, 0)
        vbox.pack_start(self._param_box, False, False, 0)

    def _build_buttons_section(self, vbox):
        # Button remap: a combo per physical button with the confirmed 4-byte
        # functions. The left-click rule (≥1 left button) is enforced inside
        # `buttons.set_function`, so the pickers can offer everything.
        self._buttons_title = Gtk.Label()
        self._buttons_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("buttons_section"))
        )
        self._buttons_title.set_halign(Gtk.Align.CENTER)
        vbox.pack_start(self._buttons_title, False, False, 0)

        self._buttons_status = Gtk.Label()
        self._buttons_status.set_halign(Gtk.Align.CENTER)
        self._buttons_status.set_line_wrap(True)
        vbox.pack_start(self._buttons_status, False, False, 2)

        self._buttons_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        self._buttons_grid.set_margin_top(4)
        vbox.pack_start(self._buttons_grid, False, False, 0)

    def _rebuild_buttons(self):
        self._buttons_loading = True
        try:
            self._render_buttons_locked()
        finally:
            self._buttons_loading = False

    def _render_buttons_locked(self):
        status, pickers = buttons_render_plan(self._buttons, self._buttons_error)
        key, is_error, fmt = status
        if is_error:
            self._buttons_status.set_markup(
                "<span color='red'>%s</span>"
                % GLib.markup_escape_text(self._t(key).format(**fmt))
            )
        else:
            self._buttons_status.set_text(self._t(key).format(**fmt))

        for child in self._buttons_grid.get_children():
            self._buttons_grid.remove(child)
        self._button_combos = {}
        if self._buttons is not None:
            # On error the last-known values stay shown (never nulled); only
            # the pickers are disabled until the next successful read.
            self._render_buttons_pickers(pickers)

    def _render_buttons_pickers(self, pickers):
        """Rebuilds the per-button combos. Each combo lists every confirmed
        function plus the raw hex when the current method is unknown; the
        marked entry is the button's current function."""
        active = self._buttons_error is not None
        for i, (name, _offset) in enumerate(buttons.BUTTONS):
            lbl = Gtk.Label(label=self._t("btn_" + name))
            lbl.set_halign(Gtk.Align.START)
            combo = Gtk.ComboBoxText()
            current, raw_hex, sensitive = pickers[name]
            for fid in buttons.METHODS:
                combo.append(fid, self._t("fn_" + fid))
            if current is not None and current not in buttons.METHODS:
                # Decode-only current (e.g. the BLE left-click variant): shown
                # as a labelled row but not a writable option — re-selecting
                # it is a no-op in _on_button_changed.
                combo.append(current, self._t("fn_" + current))
                combo.set_active_id(current)
            elif current is None and raw_hex is not None:
                combo.append("__raw__", self._t("button_raw").format(hex=raw_hex))
                combo.set_active_id("__raw__")
            else:
                combo.set_active_id(current)
            combo.set_sensitive(not active and sensitive)
            combo.connect("changed", self._on_button_changed, name)
            self._button_combos[name] = combo
            self._buttons_grid.attach(lbl, 0, i, 1, 1)
            self._buttons_grid.attach(combo, 1, i, 1, 1)
        self._buttons_grid.show_all()

    def _on_button_changed(self, combo, name):
        if self._buttons_loading:
            return
        if not combo.get_active() or not self._on_set_button:
            return
        fid = combo.get_active_id()
        if fid == "__raw__":
            return
        if fid not in buttons.METHODS:
            # Decode-only row (BLE left-click variant, gated combos): shows the
            # current function but is not a writable option.
            return
        state = self._buttons["buttons"].get(name)
        if state is not None and fid == state["fn"]:
            return
        self._on_set_button(name, fid)

    def update_buttons(self, info):
        self._buttons = info
        self._buttons_error = None
        self._rebuild_buttons()

    def set_buttons_error(self, message):
        self._buttons_error = message
        self._rebuild_buttons()

    def get_buttons_info(self):
        return self._buttons

    def has_buttons(self):
        return self._buttons is not None and self._buttons_error is None

    def _on_param_toggled(self, btn, name):
        if self._perf_loading:
            return
        if self._on_set_param:
            self._on_set_param(name, btn.get_active())

    def _on_param_scale(self, scale, name):
        if self._perf_loading:
            return
        if not self._on_set_param_choice:
            return
        lo, hi, step = parameters.param_range(name)
        value = scale.get_value()
        grid = int(round((value - lo) / step))
        value = min(max(lo + grid * step, lo), hi)
        timer = self._param_timers.get(name)
        if timer is not None:
            GLib.source_remove(timer)
        self._param_timers[name] = GLib.timeout_add(
            150, self._on_param_scale_flush, name, value
        )

    def _on_param_scale_flush(self, name, value):
        # Coalesces a drag into ONE EEPROM write (value-changed fires per
        # tick; without this every tick would submit a wake=True write).
        self._param_timers.pop(name, None)
        if not self._perf_loading and self._on_set_param_choice:
            self._on_set_param_choice(name, value)
        return False

    def _on_rate_toggled(self, btn, hz):
        if self._perf_loading:
            return
        if btn.get_active() and self._on_set_rate:
            self._on_set_rate(hz)

    def _on_rf_toggled(self, btn, *args):
        if self._perf_loading:
            return
        # A radio group fires "toggled" on BOTH radios per click (the one
        # turning off and the one turning on); only act on the newly active.
        if btn.get_active() and self._on_set_rf:
            self._on_set_rf("rf", self._rf_radio[1].get_active())

    def _on_rf_low_toggled(self, btn):
        if self._perf_loading:
            return
        if self._on_set_rf:
            self._on_set_rf("lowpow", btn.get_active())

    def update_perf(self, info):
        if info is not None and info.get("rf_error") and info.get("rf") is None:
            old = self._perf or {}
            if old.get("rf") is not None:
                # Isolated RF-read error: keep the last-known RF state so the
                # radio pair / low-power checkbox don't blank out (the mode and
                # rate sections are still valid). Never null it.
                info = dict(info)
                info["rf"] = old["rf"]
        self._perf = info
        self._perf_error = None
        self._render_perf()

    def set_perf_error(self, message):
        self._perf_error = message
        self._render_perf()

    def get_perf_info(self):
        return self._perf

    def update_params(self, info):
        self._params = info
        self._params_error = None
        self._render_perf()

    def set_params_error(self, message):
        self._params_error = message
        self._render_perf()

    def get_params_info(self):
        return self._params

    def _render_perf(self):
        self._perf_loading = True
        try:
            if self._perf_error:
                self._perf_status.set_markup(
                    "<span color='red'>%s</span>"
                    % GLib.markup_escape_text(
                        self._t("perf_error").format(error=self._perf_error)
                    )
                )
            elif self._perf is None:
                self._perf_status.set_text(self._t("perf_unknown"))
            else:
                selectable = perf.selectable_modes(self._perf["slot"])
                self._perf_status.set_text(
                    self._t("perf_status").format(
                        hz=perf.RATE_HZ[self._perf["slot"]],
                        name=perf_mode_name(self._t, self._perf["mode"]),
                    )
                )
                if self._perf["mode"] not in selectable:
                    # Mode byte is valid but not offered at this rate slot
                    # (e.g. after a rate change): explain why the marked radio
                    # is disabled and how to fix it.
                    hint = self._t("perf_mode_not_selectable").format(
                        hz=perf.RATE_HZ[self._perf["slot"]]
                    )
                    self._perf_status.set_tooltip_text(hint)
                else:
                    self._perf_status.set_tooltip_text("")
            for i, radio in enumerate(self._perf_radio):
                radio.set_active(self._perf is not None and i == self._perf["mode"])
                if self._perf is not None and self._perf_error is None:
                    radio.set_sensitive(
                        i in perf.selectable_modes(self._perf["slot"])
                    )
                else:
                    radio.set_sensitive(False)

            rate_active, rate_sensitive = perf_rate_state(self._perf, self._perf_error)
            for i, radio in enumerate(self._rate_radio):
                radio.set_active(rate_active is not None and i == rate_active)
                radio.set_sensitive(rate_sensitive)

            rf = self._perf.get("rf") if self._perf else None
            rf_error = self._perf.get("rf_error") if self._perf else None
            rf_active, rf_sensitive = rf_radio_state(
                self._perf, self._perf_error, rf_error
            )
            if self._perf_error is not None:
                # Tab-level error (mode read failed): the whole section is out.
                self._rf_status.set_text("")
            elif rf_error is not None or rf is None:
                # Isolated RF-read error: only the RF widgets are disabled, the
                # mode radios above stay functional.
                self._rf_status.set_markup(
                    "<span color='red'>%s</span>"
                    % GLib.markup_escape_text(
                        self._t("rf_error").format(error=rf_error or "?")
                    )
                )
            else:
                self._rf_status.set_text(
                    self._t("rf_status").format(
                        rf=self._t("rf_full")
                        if rf["rf_strengthen_switch"]
                        else self._t("rf_adaptive"),
                        low=self._t("rf_low_on")
                        if rf["low_power_warn_switch"]
                        else self._t("rf_low_off"),
                    )
                )
            for i, radio in enumerate(self._rf_radio):
                radio.set_active(rf_active is not None and i == int(rf_active))
                radio.set_sensitive(rf_sensitive)
            self._rf_lowpow.set_active(
                rf is not None and rf["low_power_warn_switch"]
            )
            self._rf_lowpow.set_sensitive(
                self._perf_error is None and rf_error is None and rf is not None
            )

            # Section C mouse parameters (independent of mode/RF: isolated
            # errors; last known values are retained, never nulled).
            checks, selects, read_onlys = params_render_plan(self._params, self._params_error)
            text, is_error = params_status_text(self._t, self._params, self._params_error)
            if is_error:
                self._param_status.set_markup(
                    "<span color='red'>%s</span>" % GLib.markup_escape_text(text)
                )
            else:
                self._param_status.set_text(text)
            for name, (active, sensitive) in checks.items():
                self._param_check[name].set_active(active)
                self._param_check[name].set_sensitive(sensitive)
            for name, (active, sensitive) in selects.items():
                scale = self._param_state[name][1]
                if active is not None and abs(scale.get_value() - active) > 1e-9:
                    scale.set_value(active)
                scale.set_sensitive(sensitive)
            for name, text_value in read_onlys.items():
                self._param_state[name][1].set_text(text_value)
        finally:
            self._perf_loading = False
        self._perf_box.show_all()
        self._param_box.show_all()

    def _on_perf_toggled(self, btn, mode):
        if self._perf_loading or not btn.get_active():
            return
        if self._perf is not None and mode == self._perf["mode"]:
            return
        if self._on_set_perf:
            self._on_set_perf(mode)

    def update_dpi(self, info):
        self._dpi = info
        self._dpi_error = None
        self._rebuild_dpi()

    def set_dpi_error(self, message):
        self._dpi_error = message
        self._render_dpi_widgets()

    def get_dpi_info(self):
        return self._dpi

    def has_dpi(self):
        return self._dpi is not None and self._dpi_error is None

    def _rebuild_dpi(self):
        self._cancel_dpi_timers()
        self._render_dpi_widgets()

    def _render_dpi_widgets(self):
        # The whole rebuild happens synchronously: raise the loading guard so
        # the set_active() calls (and every "toggled"/"value-changed" they
        # fire, including on the radio being deactivated) are ignored.
        self._dpi_loading = True
        try:
            self._render_dpi_widgets_locked()
        finally:
            self._dpi_loading = False

    def _render_dpi_widgets_locked(self):
        # Status / error
        if self._dpi_error:
            self._dpi_status.set_markup(
                "<span color='red'>%s</span>"
                % GLib.markup_escape_text(
                    self._t("dpi_error").format(error=self._dpi_error)
                )
            )
        elif self._dpi is None:
            self._dpi_status.set_text(self._t("dpi_unknown"))
        else:
            info = self._dpi
            gear = info["gear"]
            self._dpi_status.set_text(
                self._t("dpi_current_gear").format(
                    x=info["x"][gear],
                    n=gear + 1,
                    total=dpi.GEAR_LENGTH,
                    cycle=dpi.active_count(info["enable"]),
                )
            )

        # Gear editor: the active list (slots 0..enable). Each row is a radio
        # (selects the current gear) + DPI value spin + remove button. The
        # radios ARE the button cycle — editing a value never enables a gear.
        for child in self._dpi_grid.get_children():
            self._dpi_grid.remove(child)
        self._dpi_radio = []
        self._dpi_spin = []
        self._dpi_del = []
        self._dpi_add_btn.set_sensitive(
            self._dpi is not None
            and dpi.active_count(self._dpi["enable"]) < dpi.GEAR_LENGTH
        )
        if self._dpi is not None:
            info = self._dpi
            n = dpi.active_count(info["enable"])
            group = None
            for i in range(n):
                current = i == info["gear"]
                label = self._t("dpi_gear_row").format(n=i + 1, x=info["x"][i])
                radio = Gtk.RadioButton.new_with_label_from_widget(group, label)
                radio.set_active(current)
                radio.set_tooltip_text(
                    self._t("dpi_switch_tooltip").format(x=info["x"][i])
                )
                radio.connect("toggled", self._on_switcher_toggled, i)
                group = radio
                self._dpi_radio.append(radio)

                adj = Gtk.Adjustment(
                    value=info["x"][i],
                    lower=dpi.DPI_MIN,
                    upper=dpi.DPI_MAX,
                    step_increment=dpi.DPI_STEP,
                    page_increment=500,
                )
                spin = Gtk.SpinButton(adjustment=adj, climb_rate=0, digits=0)
                spin.set_numeric(True)
                spin.connect("value-changed", self._on_spin_changed, i)
                self._dpi_spin.append(spin)

                delbtn = Gtk.Button(label="\u2715")
                delbtn.set_relief(Gtk.ReliefStyle.NONE)
                delbtn.set_tooltip_text(
                    self._t("dpi_delete_tooltip").format(x=info["x"][i])
                )
                delbtn.connect("clicked", self._on_delete_gear, i)
                self._dpi_del.append(delbtn)

                self._dpi_grid.attach(radio, 0, i, 1, 1)
                self._dpi_grid.attach(spin, 1, i, 1, 1)
                self._dpi_grid.attach(delbtn, 2, i, 1, 1)

        # The window may already be visible: widgets packed into a shown
        # container stay invisible until explicitly shown, so re-show the
        # rebuilt grid.
        self._dpi_grid.show_all()

    def _on_switcher_toggled(self, btn, gear):
        if self._dpi_loading or not btn.get_active():
            return
        if self._dpi is not None and gear == self._dpi["gear"]:
            return
        if self._on_switch_gear:
            self._on_switch_gear(gear)

    def _on_spin_changed(self, spin, gear):
        if self._dpi_loading:
            return
        self._cancel_timer(gear)
        self._dpi_timers[gear] = GLib.timeout_add(600, self._apply_edit, gear)

    def _cancel_timer(self, gear):
        tid = self._dpi_timers.pop(gear, None)
        if tid is not None:
            GLib.source_remove(tid)

    def _cancel_dpi_timers(self):
        for gear in list(self._dpi_timers):
            self._cancel_timer(gear)

    def _apply_edit(self, gear):
        self._dpi_timers.pop(gear, None)
        self._emit_value(gear)
        return GLib.SOURCE_REMOVE

    def _emit_value(self, gear):
        """Spin edit: DPI value ONLY — the gear list/cycle is untouched."""
        if not self._on_set_value or self._dpi is None:
            return
        value = int(self._dpi_spin[gear].get_value())
        self._on_set_value(gear, value)

    def _on_add_gear(self, btn):
        if self._dpi_loading or self._dpi is None:
            return
        self._dpi_msg.set_text("")
        if self._cb_add_gear:
            self._cb_add_gear()

    def _on_delete_gear(self, btn, gear):
        if self._dpi_loading or self._dpi is None:
            return
        if dpi.active_count(self._dpi["enable"]) <= 1:
            self._dpi_msg.set_text(self._t("dpi_cant_delete"))
            return
        self._dpi_msg.set_text("")
        if self._cb_delete_gear:
            self._cb_delete_gear(gear)

    def show(self):
        self._win.show_all()

    def update(self, percent, charging=False, mode=None):
        self._known = True
        self._asleep = False
        self._last = (percent, charging, mode)
        self._render()

    def set_asleep(self):
        if self._known:
            self._asleep = True
            self._render()

    def _on_close(self, window, event):
        window.hide()
        return True

    def _on_draw(self, widget, cr):
        w = widget.get_allocated_width()
        h = widget.get_allocated_height()
        _round_rect(cr, 2, 2, w - 4, h - 4, 16)
        cr.set_source_rgb(0.93, 0.93, 0.95)
        cr.fill_preserve()
        cr.set_source_rgba(0, 0, 0, 0.08)
        cr.set_line_width(1.0)
        cr.stroke()
        pb = _mouse_pixbuf()
        if pb is not None:
            _draw_image_fit(cr, pb, w, h)
        else:
            draw_mouse(cr, w, h)
        return False

    def _on_lang_changed(self, combo):
        code = combo.get_active_id()
        if code in i18n.LANGS:
            self._lang = code
            self._win.set_title(self._t("window_title"))
            self._lang_label.set_text(self._t("language_label"))
            self._tab_battery.set_text(self._t("tab_battery"))
            self._tab_dpi.set_text(self._t("tab_dpi"))
            self._tab_perf.set_text(self._t("tab_perf"))
            self._tab_params.set_text(self._t("tab_params"))
            self._tab_buttons.set_text(self._t("tab_buttons"))
            self._dpi_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("dpi_section"))
            )
            self._dpi_add_btn.set_label(self._t("dpi_add"))
            self._perf_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("perf_section"))
            )
            self._rf_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("rf_section"))
            )
            self._rate_title.set_markup(
                "<b>%s</b>"
                % GLib.markup_escape_text(self._t("perf_rate_section"))
            )
            for i, radio in enumerate(self._rate_radio):
                radio.set_label("%d Hz" % perf.RATE_HZ[i])
            for i, radio in enumerate(self._perf_radio):
                radio.set_label(self._t("perf_mode_%d" % i))
            self._rf_radio[0].set_label(self._t("rf_radio_adaptive"))
            self._rf_radio[1].set_label(self._t("rf_radio_full"))
            self._rf_lowpow.set_label(self._t("rf_low_toggle"))
            self._param_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("param_section"))
            )
            self._buttons_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("buttons_section"))
            )
            for name, cb in self._param_check.items():
                cb.set_label(self._t("param_" + name))
            for name, (lbl, val) in self._param_state.items():
                lbl.set_text(self._t("param_" + name))
                if name == "low_power":
                    lbl.set_tooltip_text(self._t("param_low_power_tt"))
                if name in self._param_readonly:
                    val.set_tooltip_text(self._t("param_read_only"))
            self._rebuild_buttons()
            self._render()
            self._render_dpi_widgets()
            self._render_perf()
            if self._on_lang_change:
                self._on_lang_change(code)

    def _render(self):
        status = self._t("battery_unknown")
        detail = self._t("connect_device")
        if self._known:
            pct, charging, mode = self._last
            if self._asleep:
                status = self._t("asleep").format(pct=pct)
            else:
                status = self._t("battery").format(pct=pct)
                if charging:
                    status += " " + self._t("charging")
            parts = []
            if mode in i18n.MODES:
                parts.append(i18n.MODES[mode])
            parts.append(self._t("last_read").format(time=time.strftime("%H:%M")))
            detail = " · ".join(parts)
        self._status_label.set_markup(
            "<b><span size='x-large'>%s</span></b>"
            % GLib.markup_escape_text(status)
        )
        self._detail_label.set_text(detail)

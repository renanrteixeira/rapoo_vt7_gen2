import math
import time

import cairo

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from . import dpi, i18n, parameters, performance as perf


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
    section-level error string (or None). Returns (checks, read_onlys) where
    `checks` maps toggle name -> (active, sensitive) and `read_onlys` maps
    state-row name -> display text. On error the last-known values are
    retained (never nulled) and every toggle is disabled.
    """
    checks = {}
    read_onlys = {}
    if error is not None:
        known = info.get("params", {}) if info else {}
        for name, _o, editable in parameters.PARAMS:
            p = known.get(name)
            if editable:
                checks[name] = (bool(p["raw"]) if p else False, False)
            else:
                read_onlys[name] = _param_state_text(name, p)
        return checks, read_onlys
    if info is None:
        for name, _o, editable in parameters.PARAMS:
            if editable:
                checks[name] = (False, False)
            else:
                read_onlys[name] = "--"
        return checks, read_onlys
    known = info.get("params", {})
    for name, _o, editable in parameters.PARAMS:
        p = known.get(name)
        if editable:
            if p is None:
                checks[name] = (False, False)
            else:
                checks[name] = (p["value"], True)
        else:
            read_onlys[name] = _param_state_text(name, p)
    return checks, read_onlys


def _param_state_text(name, p):
    """Display text of a read-only §C row: raw int plus the documented unit
    (debounce ms, sleep min) where confirmed."""
    if p is None:
        return "--"
    unit = parameters.PARAM_UNITS.get(name)
    return "%d %s" % (p["raw"], unit) if unit else "%d" % p["raw"]


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
        self._params = None
        self._params_error = None

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

        page3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        page3.set_margin_top(16)
        page3.set_margin_bottom(16)
        page3.set_margin_start(16)
        page3.set_margin_end(16)
        self._tab_perf = Gtk.Label(label=self._t("tab_perf"))
        self._notebook.append_page(page3, self._tab_perf)
        self._build_perf_section(page3)
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

        # RF strategy + low-battery warning: shared byte 0x08D8 (state +
        # masked-write toggles; unrelated bits are preserved on write).
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

        self._rf_full = Gtk.CheckButton(label=self._t("rf_full_toggle"))
        self._rf_full.set_active(False)
        self._rf_full.connect("toggled", self._on_rf_toggled, "rf")
        vbox.pack_start(self._rf_full, False, False, 0)

        self._rf_lowpow = Gtk.CheckButton(label=self._t("rf_low_toggle"))
        self._rf_lowpow.set_active(False)
        self._rf_lowpow.connect("toggled", self._on_rf_toggled, "lowpow")
        vbox.pack_start(self._rf_lowpow, False, False, 0)

        # Section C mouse parameters: a checkbox per CONFIRMED toggle (motion
        # sync, glass tracking, DC switch — validated on the device) and a
        # read-only state row for the numeric/unconfirmed bytes (parameters,
        # never guesswork toggles).
        self._param_title = Gtk.Label()
        self._param_title.set_markup(
            "<b>%s</b>" % GLib.markup_escape_text(self._t("param_section"))
        )
        self._param_title.set_halign(Gtk.Align.CENTER)
        self._param_title.set_margin_top(8)
        vbox.pack_start(self._param_title, False, False, 0)

        self._param_status = Gtk.Label()
        self._param_status.set_halign(Gtk.Align.CENTER)
        self._param_status.set_line_wrap(True)
        vbox.pack_start(self._param_status, False, False, 2)

        self._param_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self._param_box.set_margin_top(4)
        self._param_check = {}
        self._param_state = {}
        for name, _offset, editable in parameters.PARAMS:
            if editable:
                cb = Gtk.CheckButton(label=self._t("param_" + name))
                cb.set_active(False)
                if name == "low_power":
                    cb.set_tooltip_text(self._t("param_low_power_tt"))
                cb.connect("toggled", self._on_param_toggled, name)
                self._param_check[name] = cb
                self._param_box.pack_start(cb, False, False, 0)
            else:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                lbl = Gtk.Label(label=self._t("param_" + name))
                lbl.set_halign(Gtk.Align.START)
                value = Gtk.Label()
                value.set_halign(Gtk.Align.END)
                value.set_tooltip_text(self._t("param_read_only"))
                row.pack_start(lbl, True, True, 0)
                row.pack_start(value, False, False, 0)
                self._param_state[name] = (lbl, value)
                self._param_box.pack_start(row, False, False, 0)
        self._param_scroll = Gtk.ScrolledWindow()
        self._param_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._param_scroll.set_propagate_natural_height(True)
        self._param_scroll.set_max_content_height(220)
        self._param_scroll.add(self._param_box)
        self._param_scroll.set_margin_top(4)
        vbox.pack_start(self._param_scroll, True, True, 0)

    def _on_param_toggled(self, btn, name):
        if self._perf_loading:
            return
        if self._on_set_param:
            self._on_set_param(name, btn.get_active())

    def _on_rf_toggled(self, btn, field):
        if self._perf_loading:
            return
        if self._on_set_rf:
            self._on_set_rf(field, btn.get_active())

    def update_perf(self, info):
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
                self._perf_status.set_text(
                    self._t("perf_status").format(
                        hz=perf.RATE_HZ[self._perf["slot"]],
                        name=self._t("perf_mode_%d" % self._perf["mode"]),
                    )
                )
            for i, radio in enumerate(self._perf_radio):
                radio.set_active(self._perf is not None and i == self._perf["mode"])
                if self._perf is not None and self._perf_error is None:
                    radio.set_sensitive(
                        i in perf.selectable_modes(self._perf["slot"])
                    )
                else:
                    radio.set_sensitive(False)

            rf = self._perf.get("rf") if self._perf else None
            rf_error = self._perf.get("rf_error") if self._perf else None
            if self._perf_error is not None:
                # Tab-level error (mode read failed): the whole section is out.
                self._rf_status.set_text("")
                self._rf_full.set_active(False)
                self._rf_lowpow.set_active(False)
                self._rf_full.set_sensitive(False)
                self._rf_lowpow.set_sensitive(False)
            elif rf_error is not None or rf is None:
                # Isolated RF-read error: only the RF widgets are disabled, the
                # mode radios above stay functional.
                self._rf_status.set_markup(
                    "<span color='red'>%s</span>"
                    % GLib.markup_escape_text(
                        self._t("rf_error").format(error=rf_error or "?")
                    )
                )
                self._rf_full.set_active(False)
                self._rf_lowpow.set_active(False)
                self._rf_full.set_sensitive(False)
                self._rf_lowpow.set_sensitive(False)
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
                self._rf_full.set_active(rf["rf_strengthen_switch"])
                self._rf_lowpow.set_active(rf["low_power_warn_switch"])
                self._rf_full.set_sensitive(True)
                self._rf_lowpow.set_sensitive(True)

            # Section C mouse parameters (independent of mode/RF: isolated
            # errors; last known values are retained, never nulled).
            checks, read_onlys = params_render_plan(self._params, self._params_error)
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
            self._rf_full.set_label(self._t("rf_full_toggle"))
            self._rf_lowpow.set_label(self._t("rf_low_toggle"))
            self._param_title.set_markup(
                "<b>%s</b>" % GLib.markup_escape_text(self._t("param_section"))
            )
            for name, cb in self._param_check.items():
                cb.set_label(self._t("param_" + name))
                if name == "low_power":
                    cb.set_tooltip_text(self._t("param_low_power_tt"))
            for name, (lbl, val) in self._param_state.items():
                lbl.set_text(self._t("param_" + name))
                val.set_tooltip_text(self._t("param_read_only"))
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

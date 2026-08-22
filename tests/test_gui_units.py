import unittest
from unittest import mock

from src.rapoo_vt7 import buttons, gui, i18n, parameters as par
from src.rapoo_vt7 import performance as perf


def t(key, **kw):
    return i18n.tr(key, lang="en", **kw)


def clean_info():
    params = {
        name: {
            "name": name,
            "addr": par.param_addr(name),
            "raw": 1 if editable else 3,
            "value": True if editable else 3,
            "editable": editable,
        }
        for name, _o, editable in par.PARAMS
    }
    return {"params": params, "errors": {}}


class ParamsRenderPlanTest(unittest.TestCase):
    def test_clean_info_enables_all_toggles(self):
        checks, selects, read_onlys = gui.params_render_plan(clean_info(), None)
        self.assertEqual(
            set(checks), {n for n, _o, e in par.PARAMS if e}
        )
        self.assertTrue(all(sensitive for _active, sensitive in checks.values()))
        self.assertTrue(all(active for active, _s in checks.values()))
        self.assertEqual(
            set(selects), {n for n, _o, e in par.PARAMS if not e and par.is_selectable(n)}
        )
        self.assertIn("linear_ripple", read_onlys)

    def test_read_only_rows_keep_plain_value(self):
        _checks, _sel, read_onlys = gui.params_render_plan(clean_info(), None)
        self.assertEqual(read_onlys["linear_ripple"], "3")
        self.assertEqual(read_onlys["low_power"], "3")

    def test_selectable_param_renders_slider_value(self):
        info = clean_info()
        info["params"]["press_debounce"]["raw"] = 4
        _checks, selects, read_onlys = gui.params_render_plan(info, None)
        self.assertEqual(selects["press_debounce"], (4, True))
        self.assertNotIn("press_debounce", read_onlys)

    def test_selectable_slider_with_offrange_value_unmarks_and_disables(self):
        info = clean_info()
        info["params"]["press_debounce"]["raw"] = 99
        _checks, selects, _ro = gui.params_render_plan(info, None)
        self.assertEqual(selects["press_debounce"], (None, False))

    def test_selectable_slider_offgrid_raw_snaps_to_grid(self):
        info = clean_info()
        info["params"]["press_debounce"]["raw"] = 3
        _checks, selects, _ro = gui.params_render_plan(info, None)
        self.assertEqual(selects["press_debounce"], (4, True))

    def test_lift_off_slider_value_scaled(self):
        info = clean_info()
        info["params"]["lift_off"]["raw"] = 11
        _checks, selects, _ro = gui.params_render_plan(info, None)
        self.assertEqual(selects["lift_off"], (2.0, True))

    def test_error_retains_last_known_and_disables(self):
        info = clean_info()
        checks, selects, _ro = gui.params_render_plan(info, "boom")
        for active, sensitive in checks.values():
            self.assertFalse(sensitive)
        self.assertTrue(all(active for active, _s in checks.values()))
        for active, sensitive in selects.values():
            self.assertIsNotNone(active)
            self.assertFalse(sensitive)

    def test_error_without_known_info_zeros_toggles(self):
        checks, _sel, _ro = gui.params_render_plan(None, "boom")
        for active, sensitive in checks.values():
            self.assertFalse(active)
            self.assertFalse(sensitive)

    def test_unknown_info_zeros_everything(self):
        checks, selects, read_onlys = gui.params_render_plan(None, None)
        for active, sensitive in checks.values():
            self.assertFalse(active)
            self.assertFalse(sensitive)
        self.assertTrue(all(active is None and not sensitive for active, sensitive in selects.values()))
        self.assertTrue(all(v == "--" for v in read_onlys.values()))


class ParamsStatusTextTest(unittest.TestCase):
    def test_clean_returns_empty(self):
        text, is_error = gui.params_status_text(t, clean_info(), None)
        self.assertEqual(text, "")
        self.assertFalse(is_error)

    def test_section_error(self):
        text, is_error = gui.params_status_text(t, clean_info(), "timeout")
        self.assertTrue(is_error)
        self.assertIn("timeout", text)

    def test_unknown(self):
        text, is_error = gui.params_status_text(t, None, None)
        self.assertEqual(text, t("param_unknown"))
        self.assertFalse(is_error)

    def test_multiple_errors_aggregate_count(self):
        info = {"params": {}, "errors": {"a": "x", "b": "y", "c": "z"}}
        text, is_error = gui.params_status_text(t, info, None)
        self.assertTrue(is_error)
        self.assertIn("x", text)
        self.assertIn(t("param_more_errors", n=2), text)

    def test_single_error_no_aggregate(self):
        info = {"params": {}, "errors": {"a": "x"}}
        text, is_error = gui.params_status_text(t, info, None)
        self.assertTrue(is_error)
        self.assertNotIn("more", text)


def perf_info(slot=3, mode=1, rf=None, rf_error=None):
    return {"slot": slot, "mode": mode, "rf": rf, "rf_error": rf_error}


class PerfRateStateTest(unittest.TestCase):
    def test_marks_the_current_slot(self):
        active, sensitive = gui.perf_rate_state(perf_info(slot=5), None)
        self.assertEqual(active, 5)
        self.assertTrue(sensitive)

    def test_error_retains_last_slot_and_disables(self):
        active, sensitive = gui.perf_rate_state(perf_info(slot=2), "boom")
        self.assertEqual(active, 2)
        self.assertFalse(sensitive)

    def test_unknown_disables_everything(self):
        active, sensitive = gui.perf_rate_state(None, None)
        self.assertIsNone(active)
        self.assertFalse(sensitive)


class PerfModeNameTest(unittest.TestCase):
    def test_known_mode_uses_translation(self):
        self.assertEqual(gui.perf_mode_name(t, 3), t("perf_mode_3"))

    def test_out_of_range_mode_falls_back(self):
        for bad in (6, 255, -1, None, "3"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    gui.perf_mode_name(t, bad), t("perf_mode_unknown")
                )


class RfRadioStateTest(unittest.TestCase):
    def test_adaptive_is_marked_when_off(self):
        rf = {"rf_strengthen_switch": False, "low_power_warn_switch": False}
        active, sensitive = gui.rf_radio_state(perf_info(rf=rf), None, None)
        self.assertFalse(active)
        self.assertTrue(sensitive)

    def test_full_is_marked_when_on(self):
        rf = {"rf_strengthen_switch": True, "low_power_warn_switch": True}
        active, sensitive = gui.rf_radio_state(perf_info(rf=rf), None, None)
        self.assertTrue(active)
        self.assertTrue(sensitive)

    def test_tab_error_retains_last_state_and_disables(self):
        rf = {"rf_strengthen_switch": True, "low_power_warn_switch": False}
        active, sensitive = gui.rf_radio_state(perf_info(rf=rf), "boom", None)
        self.assertTrue(active)
        self.assertFalse(sensitive)

    def test_rf_error_retains_last_state_and_disables(self):
        rf = {"rf_strengthen_switch": False, "low_power_warn_switch": False}
        active, sensitive = gui.rf_radio_state(perf_info(rf=rf), None, "read fail")
        self.assertFalse(active)
        self.assertFalse(sensitive)

    def test_unknown_disables_everything(self):
        active, sensitive = gui.rf_radio_state(None, None, None)
        self.assertIsNone(active)
        self.assertFalse(sensitive)


def buttons_info(fns=None, errors=None):
    fns = fns or {"mouse_left": "mouse_left"}
    buttons_ = {}
    for name, _o in buttons.BUTTONS:
        if name in fns:
            fid = fns[name]
            method = buttons.METHODS.get(fid)
            buttons_[name] = {
                "name": name,
                "addr": buttons.button_addr(name),
                "method": method,
                "fn": fid,
                "raw_hex": method.hex() if method else None,
            }
    return {"buttons": buttons_, "errors": errors or {}}


class ButtonsRenderPlanTest(unittest.TestCase):
    def test_clean_info_marks_current_function(self):
        status, pickers = gui.buttons_render_plan(buttons_info(), None)
        self.assertEqual(status[0], "buttons_status")
        self.assertFalse(status[1])
        self.assertEqual(pickers["mouse_left"], ("mouse_left", "03000100", True))
        self.assertEqual(len(pickers), len(buttons.BUTTONS))


class KeyboardFilterTest(unittest.TestCase):
    def test_empty_query_returns_all_keys(self):
        self.assertEqual(
            len(gui.BatteryWindow._filter_keys("")), len(buttons.KEYBOARD)
        )
        self.assertEqual(
            len(gui.BatteryWindow._filter_keys("  ")), len(buttons.KEYBOARD)
        )

    def test_matches_by_id_and_label(self):
        keys = gui.BatteryWindow._filter_keys("esc")
        self.assertEqual(keys, ["kb_esc"])
        keys = gui.BatteryWindow._filter_keys("f5")
        self.assertEqual(keys, ["kb_f5"])
        # Label match is case-insensitive too.
        keys = gui.BatteryWindow._filter_keys("PgUp")
        self.assertEqual(keys, ["kb_pgup"])

    def test_case_insensitive(self):
        keys = gui.BatteryWindow._filter_keys("HOME")
        self.assertEqual(keys, ["kb_home"])

    def test_substring_across_keys(self):
        keys = gui.BatteryWindow._filter_keys("arrow")
        self.assertIn("kb_arrow_up", keys)
        self.assertIn("kb_arrow_down", keys)
        self.assertEqual(len(keys), 4)

    def test_no_match(self):
        self.assertEqual(gui.BatteryWindow._filter_keys("zzzz"), [])


class ButtonFnLabelTest(unittest.TestCase):
    def _win(self, lang="en"):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = lang
        return window

    def test_confirmed_function_uses_i18n(self):
        self.assertEqual(
            self._win()._button_fn_label("mouse_left"),
            i18n.LANGS["en"]["fn_mouse_left"],
        )

    def test_keyboard_key_uses_neutral_label(self):
        self.assertEqual(self._win()._button_fn_label("kb_esc"), "Esc")
        self.assertEqual(self._win()._button_fn_label("kb_arrow_up"), "↑")

    def test_macro_label_numbering(self):
        self.assertEqual(
            self._win()._button_fn_label("macro_0"), "Macro 1"
        )
        self.assertEqual(
            self._win()._button_fn_label("macro_11"), "Macro 12"
        )

    def test_combo_uses_i18n(self):
        self.assertEqual(
            self._win()._button_fn_label("win_close"),
            i18n.LANGS["en"]["fn_win_close"],
        )

    def test_unknown_method_shows_raw_hex_and_stays_enabled(self):
        info = buttons_info()
        info["buttons"]["mouse_bottom"] = {
            "name": "mouse_bottom",
            "addr": buttons.button_addr("mouse_bottom"),
            "method": bytes.fromhex("00010203"),
            "fn": None,
            "raw_hex": "00010203",
        }
        status, pickers = gui.buttons_render_plan(info, None)
        self.assertEqual(pickers["mouse_bottom"], (None, "00010203", True))

    def test_error_retains_last_known_and_disables(self):
        status, pickers = gui.buttons_render_plan(buttons_info(), "boom")
        self.assertEqual(status[0], "buttons_error")
        self.assertTrue(status[1])
        for name, _o in buttons.BUTTONS:
            self.assertEqual(pickers[name][2], False)

    def test_error_without_known_info_disables_everything(self):
        status, pickers = gui.buttons_render_plan(None, "boom")
        self.assertEqual(status[0], "buttons_error")
        self.assertTrue(status[1])
        for name, _o in buttons.BUTTONS:
            self.assertEqual(pickers[name], (None, None, False))

    def test_unknown_info_unknown_status(self):
        status, pickers = gui.buttons_render_plan(None, None)
        self.assertEqual(status[0], "buttons_unknown")
        self.assertFalse(status[1])

    def test_isolated_error_aggregates_in_status_and_disables_one(self):
        info = {"buttons": {}, "errors": {"a": "x", "b": "y"}}
        status, pickers = gui.buttons_render_plan(info, None)
        self.assertEqual(status[0], "buttons_more_errors")
        self.assertTrue(status[1])
        self.assertEqual(status[2]["error"], "x")
        self.assertEqual(status[2]["n"], 1)

    def test_per_field_error_with_real_buttons_disables_only_that_one(self):
        info = buttons_info({name: "mouse_left" for name, _o in buttons.BUTTONS})
        # A broken field is absent from the payload (read_section isolates it
        # into `errors`), so the picker must show raw-unknown disabled while
        # every healthy button stays sensitive.
        info["buttons"].pop("mouse_left")
        info["errors"] = {"mouse_left": "short reply"}
        status, pickers = gui.buttons_render_plan(info, None)
        self.assertEqual(status[0], "buttons_error")
        self.assertEqual(pickers["mouse_left"], (None, None, False))
        for name, _o in buttons.BUTTONS:
            if name != "mouse_left":
                self.assertEqual(pickers[name][2], True)
        self.assertIn("short reply", status[2]["error"])

    def test_scroll_back_button_marks_backward(self):
        info = buttons_info({name: "mouse_left" for name, _o in buttons.BUTTONS})
        # The physical scroll-back button holds the shared 0bff00ff method;
        # read_button decodes direction contextually, so the render plan must
        # mark scroll_backward there and scroll_forward on the forward button.
        info["buttons"]["mouse_scroll_back"]["method"] = bytes.fromhex("0bff00ff")
        info["buttons"]["mouse_scroll_back"]["fn"] = buttons.method_name(
            bytes.fromhex("0bff00ff"), "mouse_scroll_back"
        )
        info["buttons"]["mouse_scroll_forward"]["method"] = bytes.fromhex("0bff00ff")
        info["buttons"]["mouse_scroll_forward"]["fn"] = buttons.method_name(
            bytes.fromhex("0bff00ff"), "mouse_scroll_forward"
        )
        status, pickers = gui.buttons_render_plan(info, None)
        self.assertEqual(status[0], "buttons_status")
        self.assertEqual(pickers["mouse_scroll_back"][0], "scroll_backward")
        self.assertEqual(pickers["mouse_scroll_forward"][0], "scroll_forward")

    def test_status_count_is_dynamic(self):
        status, _pickers = gui.buttons_render_plan(buttons_info(), None)
        self.assertEqual(status[2]["n"], len(buttons.BUTTONS))


class PairingRenderPlanTest(unittest.TestCase):
    def test_none_status_keeps_step_and_shows_matching(self):
        self.assertEqual(
            gui.pairing_render_plan(1, None), (1, "pairing_matching", False)
        )

    def test_matching_status_is_not_terminal(self):
        self.assertEqual(
            gui.pairing_render_plan(2, "matching"), (2, "pairing_matching", False)
        )

    def test_success_highlights_reported_step_not_error(self):
        self.assertEqual(
            gui.pairing_render_plan(2, gui.STATUS_SUCCESS),
            (2, "pairing_success", False),
        )
        self.assertEqual(
            gui.pairing_render_plan(0, gui.STATUS_SUCCESS),
            (0, "pairing_success", False),
        )

    def test_failed_highlights_reported_step_not_error(self):
        self.assertEqual(
            gui.pairing_render_plan(1, gui.STATUS_FAILED),
            (1, "pairing_failed", False),
        )

    def test_timeout_highlights_reported_step_not_error(self):
        self.assertEqual(
            gui.pairing_render_plan(1, gui.STATUS_TIMEOUT),
            (1, "pairing_timeout", False),
        )

    def test_cancelled_highlights_reported_step_not_error(self):
        self.assertEqual(
            gui.pairing_render_plan(1, gui.STATUS_CANCELLED),
            (1, "pairing_cancelled", False),
        )

    def test_error_is_marked_error(self):
        self.assertEqual(
            gui.pairing_render_plan(1, gui.STATUS_ERROR),
            (1, "pairing_error", True),
        )

    def test_terminal_step_clamped_into_0_2(self):
        # An early error (e.g. receiver-not-found at open, step 0) must never
        # highlight the L+M+R step; step_n is clamped into 0..2.
        self.assertEqual(
            gui.pairing_render_plan(0, gui.STATUS_ERROR),
            (0, "pairing_error", True),
        )
        self.assertEqual(
            gui.pairing_render_plan(None, gui.STATUS_ERROR),
            (0, "pairing_error", True),
        )
        self.assertEqual(
            gui.pairing_render_plan(99, gui.STATUS_ERROR),
            (2, "pairing_error", True),
        )

    def test_unknown_status_falls_back_to_matching(self):
        self.assertEqual(
            gui.pairing_render_plan(0, "bogus"), (0, "pairing_matching", False)
        )

    def test_step_none_defaults_to_zero(self):
        self.assertEqual(
            gui.pairing_render_plan(None, None), (0, "pairing_matching", False)
        )


class _W:
    """Headless Gtk widget stand-in: records the last value per setter."""

    def __init__(self, value=0.0, active=False, text=""):
        self.value = value
        self.active = active
        self.text = text
        self.sensitive = True
        self.tooltip = None
        self.label = None

    def get_value(self):
        return self.value

    def set_value(self, v):
        self.value = v

    def get_active(self):
        return self.active

    def set_active(self, v):
        self.active = v

    def set_sensitive(self, v):
        self.sensitive = v

    def get_text(self):
        return self.text

    def set_text(self, t):
        self.text = t

    def set_markup(self, m):
        self.text = m

    def set_tooltip_text(self, t):
        self.tooltip = t

    def set_label(self, l):
        self.label = l

    def set_placeholder_text(self, t):
        self.placeholder = t

    def get_active_id(self):
        return self.active_id

    def show_all(self):
        pass

    def set_title(self, t):
        self.title = t


def _en(key, **kw):
    return i18n.tr(key, lang="en", **kw)


class FilterKeysTest(unittest.TestCase):
    """`_filter_keys` (pure): the keyboard tab search of the picker dialog."""

    def test_empty_query_returns_every_key_in_order(self):
        self.assertEqual(gui.BatteryWindow._filter_keys(""), list(buttons.KEYBOARD))
        self.assertEqual(gui.BatteryWindow._filter_keys("  "), list(buttons.KEYBOARD))

    def test_matches_id_substring_case_insensitive(self):
        out = gui.BatteryWindow._filter_keys("ESC")
        self.assertIn("kb_esc", out)
        self.assertNotIn("kb_a", out)

    def test_matches_label_substring(self):
        # "Space" is in the label of kb_space but not its id.
        label_hits = [k for k in buttons.KEYBOARD if "space" in buttons.KEYBOARD_LABEL[k].lower()]
        if label_hits:
            self.assertIn(label_hits[0], gui.BatteryWindow._filter_keys("space"))

    def test_no_match_returns_empty(self):
        self.assertEqual(gui.BatteryWindow._filter_keys("zzzz"), [])


class PickerPickTest(unittest.TestCase):
    """Retro epic-4 F3: headless coverage of `_picker_pick` — a picker row
    click closes the dialog with OK and submits the function."""

    def test_pick_responds_ok_and_submits(self):
        calls = []
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._on_set_button = lambda name, fid: calls.append((name, fid))
        dialog = _W()
        dialog.responses = []
        dialog.response = lambda r: dialog.responses.append(r)
        window._picker_pick("kb_a", dialog, "mouse_right")
        self.assertEqual(dialog.responses, [gui.Gtk.ResponseType.OK])
        self.assertEqual(calls, [("mouse_right", "kb_a")])


class ParamScaleCoalesceTest(unittest.TestCase):
    """Retro epic-3 F3: a slider drag coalesces into ONE write (the declared
    AC had zero tests)."""

    def _window(self):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._perf_loading = False
        window._param_timers = {}
        window._submitted = []
        window._on_set_param_choice = (
            lambda name, value: window._submitted.append((name, value))
        )
        return window

    def test_drag_snap_and_single_flush_write(self):
        window = self._window()
        scale = _W(value=5.3)  # press_debounce: lo=0 step=2 -> snaps to 6
        with mock.patch.object(gui.GLib, "timeout_add", return_value=7) as mt:
            window._on_param_scale(scale, "press_debounce")
        self.assertEqual(mt.call_args[0][0], 150)
        cb, name, value = mt.call_args[0][1:4]
        self.assertEqual((name, value), ("press_debounce", 6))
        self.assertEqual(window._submitted, [])  # nothing written yet
        self.assertTrue(cb(name, value) is False)  # GTK timer: stop the source
        self.assertEqual(window._submitted, [("press_debounce", 6)])
        self.assertNotIn("press_debounce", window._param_timers)

    def test_second_drag_cancels_pending_timer(self):
        window = self._window()
        with mock.patch.object(
            gui.GLib, "timeout_add", return_value=7
        ), mock.patch.object(gui.GLib, "source_remove") as mr:
            window._on_param_scale(_W(value=4.0), "press_debounce")
            window._on_param_scale(_W(value=10.9), "press_debounce")  # snaps to 10
            mr.assert_called_once_with(7)  # the first drag's timer was cancelled
        # Flush the surviving (second) timer: exactly one submit, latest value.
        with mock.patch.object(gui.GLib, "timeout_add", return_value=8) as mt2:
            window._on_param_scale(_W(value=10.9), "press_debounce")
        cb, name, value = mt2.call_args[0][1:4]
        self.assertEqual((name, value), ("press_debounce", 10))
        self.assertTrue(cb(name, value) is False)
        self.assertEqual(window._submitted, [("press_debounce", 10)])

    def test_flush_skips_while_loading_or_without_callback(self):
        window = self._window()
        window._perf_loading = True
        window._on_param_scale_flush("press_debounce", 6)
        self.assertEqual(window._submitted, [])
        window._perf_loading = False
        window._on_set_param_choice = None
        self.assertFalse(window._on_param_scale_flush("press_debounce", 6))


class RfDoubleSubmitTest(unittest.TestCase):
    """Retro epic-3 F3: regression guard for the RF radio double-submit fix —
    a radio group fires `toggled` on BOTH radios; only the newly active one
    may submit."""

    def _window(self, on_active=True):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._perf_loading = False
        window._rf_calls = []
        window._on_set_rf = lambda kind, flag: window._rf_calls.append((kind, flag))
        window._rf_radio = (_W(active=False), _W(active=True))
        return window

    def test_only_newly_active_radio_submits(self):
        window = self._window()
        window._on_rf_toggled(window._rf_radio[1])  # turning ON
        self.assertEqual(window._rf_calls, [("rf", True)])
        window._on_rf_toggled(window._rf_radio[0])  # the turning-off radio
        self.assertEqual(window._rf_calls, [("rf", True)])  # unchanged

    def test_lowpow_checkbox_submits_state(self):
        window = self._window()
        box = _W(active=True)
        window._on_rf_low_toggled(box)
        self.assertEqual(window._rf_calls, [("lowpow", True)])

    def test_loading_guard_blocks_submission(self):
        window = self._window()
        window._perf_loading = True
        window._on_rf_toggled(window._rf_radio[1])
        window._on_rf_low_toggled(_W(active=True))
        self.assertEqual(window._rf_calls, [])


class SelectableModesSensitivityTest(unittest.TestCase):
    """Retro epic-3 F3: GUI-side `selectable_modes` sensitivity — at slot 3
    only modes {1,2,3,4,5} are clickable; mode 0's radio renders disabled."""

    def _window(self, perf_info=None, perf_error=None):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._t = _en
        window._perf = perf_info
        window._perf_error = perf_error
        window._params = clean_info()
        window._params_error = None
        info = window._params["params"]
        window._perf_status = _W()
        window._rf_status = _W()
        window._param_status = _W()
        window._perf_radio = [_W() for _ in range(perf.PERF_MODE_COUNT)]
        window._rate_radio = [_W() for _ in range(len(perf.RATE_HZ))]
        window._rf_radio = [_W(), _W()]
        window._rf_lowpow = _W()
        # Widget maps mirroring clean_info(): toggles for editable params,
        # (label, value) pairs for the read-only rows.
        window._param_check = {
            name: _W() for name, p in info.items() if p["editable"]
        }
        window._param_state = {
            name: (_W(), _W()) for name, p in info.items() if not p["editable"]
        }
        window._perf_box = _W()
        window._param_box = _W()
        return window

    def test_slot3_disables_unselectable_modes(self):
        window = self._window({"slot": 3, "mode": 2, "rf": {"rf_strengthen_switch": False, "low_power_warn_switch": True}})
        window._render_perf()
        selectable = set(perf.selectable_modes(3))
        for i, radio in enumerate(window._perf_radio):
            self.assertEqual(radio.sensitive, i in selectable, "mode %d" % i)
        self.assertFalse(window._perf_radio[0].sensitive)

    def test_tab_error_disables_every_mode_radio(self):
        window = self._window({"slot": 3, "mode": 2}, perf_error="boom")
        window._render_perf()
        self.assertTrue(all(not r.sensitive for r in window._perf_radio))
        self.assertTrue(all(not r.sensitive for r in window._rate_radio))

    def test_rate_radios_follow_reported_slot(self):
        window = self._window({"slot": 5, "mode": 3, "rf": {"rf_strengthen_switch": True, "low_power_warn_switch": False}})
        window._render_perf()
        marked = [i for i, r in enumerate(window._rate_radio) if r.active]
        self.assertEqual(marked, [5])
        self.assertTrue(all(r.sensitive for r in window._rate_radio))


class RelabelPerfWidgetsTest(unittest.TestCase):
    """Retro epic-3 F3: language change re-translates the perf/rate/RF/§C
    widgets (the exact gap the applied 3-1 patch flagged)."""

    def _window(self, lang="pt_BR"):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = lang
        window._t = lambda key, **kw: i18n.tr(key, lang=window._lang, **kw)
        window._win = _W()
        window._lang_label = _W()
        for attr in ("_tab_battery", "_tab_dpi", "_tab_perf", "_tab_params", "_tab_buttons", "_tab_system"):
            setattr(window, attr, _W())
        window._dpi_title = _W()
        window._dpi_add_btn = _W()
        window._perf_title = _W()
        window._rf_title = _W()
        window._rate_title = _W()
        window._rate_radio = [_W() for _ in range(len(perf.RATE_HZ))]
        window._perf_radio = [_W() for _ in range(perf.PERF_MODE_COUNT)]
        window._rf_radio = [_W(), _W()]
        window._rf_lowpow = _W()
        window._param_title = _W()
        window._buttons_title = _W()
        window._system_button = _W()
        window._system_hint = _W()
        window._name_title = _W()
        window._name_entry = _W()
        window._name_button = _W()
        window._pair_title = _W()
        window._pair_hint = _W()
        window._pair_button = _W()
        window._pair_cancel = _W()
        window._pair_steps = [_W() for _ in range(3)]
        window._pair_last_status = None
        window._pair_busy = False
        window._pair_status = _W()
        window._param_check = {}
        window._param_state = {}
        window._param_readonly = set()
        window.renders = []
        window._rebuild_buttons = lambda: window.renders.append("buttons")
        window._render = lambda: window.renders.append("battery")
        window._render_dpi_widgets = lambda: window.renders.append("dpi")
        window._render_perf = lambda: window.renders.append("perf")
        window.lang_changes = []
        window._on_lang_change = lambda code: window.lang_changes.append(code)
        return window

    def test_switch_to_en_relables_perf_rate_rf_and_params(self):
        window = self._window(lang="pt_BR")
        combo = _W()
        combo.active_id = "en"
        window._on_lang_changed(combo)
        self.assertEqual(
            [r.label for r in window._rate_radio],
            ["%d Hz" % hz for hz in perf.RATE_HZ],
        )
        self.assertEqual(
            [r.label for r in window._perf_radio],
            [_en("perf_mode_%d" % i) for i in range(perf.PERF_MODE_COUNT)],
        )
        self.assertEqual(window._rf_radio[0].label, _en("rf_radio_adaptive"))
        self.assertEqual(window._rf_radio[1].label, _en("rf_radio_full"))
        self.assertEqual(window._rf_lowpow.label, _en("rf_low_toggle"))
        self.assertIn("Performance", window._perf_title.text.replace("<b>", "").replace("</b>", ""))
        self.assertEqual(window.lang_changes, ["en"])
        self.assertEqual(window.renders, ["buttons", "battery", "dpi", "perf"])

    def test_pt_br_labels_differ_from_en(self):
        window = self._window(lang="en")
        combo = _W()
        combo.active_id = "pt_BR"
        window._on_lang_changed(combo)
        self.assertEqual(window._perf_radio[0].label, i18n.tr("perf_mode_0", lang="pt_BR"))
        self.assertNotEqual(
            window._perf_radio[0].label, _en("perf_mode_0")
        )


def _dpi_info(gear=1, enable=2):
    return {
        "gear": gear,
        "enable": enable,
        "x": [800, 1200, 5000, 1600, 3200, 6400, 26000],
        "y": [800, 1200, 5000, 1600, 3200, 6400, 26000],
    }


class DpiRenderPlanTest(unittest.TestCase):
    """Retro epic-2 F3: pure plan for the DPI tab — AC1's rendered status
    (gear value / number / cycle count) is asserted here for the first time."""

    def test_ac1_status_args(self):
        status = gui.dpi_render_plan(_dpi_info(), None)["status"]
        self.assertEqual(status, ("current", 1200, 2, gui.dpi.GEAR_LENGTH, 3))

    def test_unknown_and_error_status(self):
        self.assertEqual(gui.dpi_render_plan(None, None)["status"], ("unknown", None))
        self.assertEqual(gui.dpi_render_plan(None, "boom")["status"], ("error", "boom"))

    def test_rows_mark_only_the_current_slot(self):
        rows = gui.dpi_render_plan(_dpi_info(), None)["rows"]
        self.assertEqual([r["slot"] for r in rows], [0, 1, 2])
        self.assertEqual([r["value"] for r in rows], [800, 1200, 5000])
        self.assertEqual([r["current"] for r in rows], [False, True, False])

    def test_can_add_boundary(self):
        self.assertTrue(gui.dpi_render_plan(_dpi_info(enable=5), None)["can_add"])
        full = gui.dpi_render_plan(_dpi_info(enable=6), None)
        self.assertFalse(full["can_add"])
        self.assertEqual(len(full["rows"]), 7)

    def test_out_of_range_gear_degrades_to_unknown(self):
        plan = gui.dpi_render_plan(_dpi_info(gear=9), None)
        self.assertEqual(plan["status"], ("unknown", None))
        self.assertEqual([r["current"] for r in plan["rows"]], [False] * 3)


class DpiStatusTextTest(unittest.TestCase):
    """Regression (F3 unpack, found on-device): the plan "current" status is
    a FIVE-element tuple; the widget used to unpack it as 2 names and the
    ValueError killed the idle_add render — tab stayed empty and Add stayed
    disabled on every successful read. The pure helper owns the unpack now."""

    def test_current_formats_all_four_fields(self):
        expected = t("dpi_current_gear").format(
            x=1200, n=2, total=gui.dpi.GEAR_LENGTH, cycle=3
        )
        self.assertEqual(
            gui.dpi_status_text(t, _dpi_info(), None), (expected, False)
        )

    def test_unknown_status(self):
        self.assertEqual(gui.dpi_status_text(t, None, None), (t("dpi_unknown"), False))

    def test_error_status_is_flagged_red(self):
        self.assertEqual(
            gui.dpi_status_text(t, None, "boom"),
            (t("dpi_error").format(error="boom"), True),
        )


class _DpiWindowMixin:
    def _window(self):
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._dpi_loading = False
        window._dpi = _dpi_info()
        window._dpi_error = None
        window._dpi_busy = False
        window._dpi_generation = 0
        window._dpi_timers = {}
        window._dpi_msg = _W()
        window._dpi_add_btn = _W()
        window._dpi_radio = [_W(active=False), _W(active=True), _W(active=False)]
        window._dpi_spin = [_W(), _W(), _W()]
        window._dpi_del = [_W(), _W(), _W()]
        window.calls = []
        window._cb_add_gear = lambda: window.calls.append("add")
        window._cb_delete_gear = lambda g: window.calls.append(("delete", g))
        window._on_switch_gear = lambda g: window.calls.append(("switch", g))
        window._on_set_value = lambda g, v: window.calls.append(("set", g, v))
        return window


class DpiBusyGuardTest(_DpiWindowMixin, unittest.TestCase):
    """Retro epic-2 F6: user DPI actions are mutually exclusive — a click
    sets the busy guard and disables every action until the completion
    (update_dpi/set_dpi_error) clears it (mirrors the System-tab guard)."""

    def test_add_click_disables_everything_until_completion(self):
        w = self._window()
        w._on_add_gear(None)
        self.assertEqual(w.calls, ["add"])
        self.assertTrue(w._dpi_busy)
        self.assertFalse(w._dpi_add_btn.sensitive)
        self.assertFalse(any(r.sensitive for r in w._dpi_radio))
        self.assertFalse(any(s.sensitive for s in w._dpi_spin))
        self.assertFalse(any(d.sensitive for d in w._dpi_del))

    def test_second_click_while_busy_is_ignored(self):
        w = self._window()
        w._on_add_gear(None)
        w._on_delete_gear(None, 0)
        self.assertEqual(w.calls, ["add"])

    def test_delete_and_switch_set_the_guard_with_payload(self):
        w = self._window()
        w._on_delete_gear(None, 2)
        self.assertEqual(w.calls, [("delete", 2)])
        self.assertTrue(w._dpi_busy)
        radio = _W(active=True)
        w2 = self._window()
        w2._on_switcher_toggled(radio, 2)
        self.assertEqual(w2.calls, [("switch", 2)])
        self.assertTrue(w2._dpi_busy)

    def test_spin_edit_sets_the_guard_on_fire(self):
        w = self._window()
        w._dpi_spin[0].value = 900.0
        w._emit_value(0)
        self.assertEqual(w.calls, [("set", 0, 900)])
        self.assertTrue(w._dpi_busy)

    def test_completion_paths_clear_the_guard(self):
        w = self._window()
        w._on_add_gear(None)
        with mock.patch.object(gui.BatteryWindow, "_render_dpi_widgets"):
            w.update_dpi(_dpi_info())
        self.assertFalse(w._dpi_busy)
        w2 = self._window()
        w2._on_add_gear(None)
        with mock.patch.object(gui.BatteryWindow, "_render_dpi_widgets"):
            w2.set_dpi_error("boom")
        self.assertFalse(w2._dpi_busy)


class DpiStalenessTest(_DpiWindowMixin, unittest.TestCase):
    """Retro epic-2 F2: add/delete invalidate pending spin-edit timers — a
    stale edit must never write `set_value` through a compacted slot."""

    def _arm(self, w, gear, value):
        spin = _W(value=value)
        with mock.patch.object(gui.GLib, "timeout_add", return_value=42) as mt:
            w._on_spin_changed(spin, gear)
        cb, g, generation = mt.call_args[0][1:4]
        self.assertEqual(g, gear)
        return cb, generation

    def test_armed_edit_captures_generation_and_waits(self):
        w = self._window()
        cb, generation = self._arm(w, 0, 900)
        self.assertEqual(w._dpi_timers[0], 42)
        self.assertEqual(w.calls, [])  # nothing written before the timer fires

    def test_uninvalidated_edit_fires_and_submits_once(self):
        w = self._window()
        w._dpi_spin[0].value = 900.0
        cb, generation = self._arm(w, 0, 900)
        self.assertTrue(cb(0, generation) is False)
        self.assertEqual(w.calls, [("set", 0, 900)])
        self.assertNotIn(0, w._dpi_timers)

    def _invalidate_case(self, action):
        w = self._window()
        cb, generation = self._arm(w, 0, 900)
        with mock.patch.object(gui.GLib, "source_remove") as mr:
            if action == "delete":
                w._on_delete_gear(None, 2)
            else:
                w._on_add_gear(None)
        mr.assert_called_once_with(42)  # the armed timer was cancelled...
        self.assertNotIn(0, w._dpi_timers)
        # ...and even if the stale callback fires anyway (race), the
        # generation mismatch discards it without submitting.
        self.assertTrue(cb(0, generation) is False)
        return w

    def test_delete_invalidates_pending_edit(self):
        w = self._invalidate_case("delete")
        self.assertEqual(w.calls, [("delete", 2)])

    def test_add_invalidates_pending_edit(self):
        w = self._invalidate_case("add")
        self.assertEqual(w.calls, ["add"])

    def test_rebuild_bumps_generation_too(self):
        w = self._window()
        gen_before = w._dpi_generation
        with mock.patch.object(gui.BatteryWindow, "_render_dpi_widgets"):
            w._rebuild_dpi()
        self.assertGreater(w._dpi_generation, gen_before)
        self.assertEqual(w._dpi_timers, {})


if __name__ == "__main__":
    unittest.main()

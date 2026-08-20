import unittest

from src.rapoo_vt7 import buttons, gui, i18n, parameters as par


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


if __name__ == "__main__":
    unittest.main()

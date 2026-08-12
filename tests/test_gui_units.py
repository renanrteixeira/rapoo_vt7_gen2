import unittest

from src.rapoo_vt7 import gui, i18n, parameters as par


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

    def test_selectable_slider_with_offrange_value_unmarks(self):
        info = clean_info()
        info["params"]["press_debounce"]["raw"] = 99
        _checks, selects, _ro = gui.params_render_plan(info, None)
        self.assertEqual(selects["press_debounce"], (None, True))

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


if __name__ == "__main__":
    unittest.main()

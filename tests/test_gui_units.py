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
        checks, read_onlys = gui.params_render_plan(clean_info(), None)
        self.assertEqual(
            set(checks), {n for n, _o, e in par.PARAMS if e}
        )
        self.assertTrue(all(sensitive for _active, sensitive in checks.values()))
        self.assertTrue(all(active for active, _s in checks.values()))

    def test_read_only_rows_have_unit_suffix(self):
        checks, read_onlys = gui.params_render_plan(clean_info(), None)
        self.assertEqual(read_onlys["press_debounce"], "3 ms")
        self.assertEqual(read_onlys["sleep_time"], "3 min")
        self.assertEqual(read_onlys["lift_off"], "3")

    def test_error_retains_last_known_and_disables(self):
        info = clean_info()
        checks, _ro = gui.params_render_plan(info, "boom")
        for active, sensitive in checks.values():
            self.assertFalse(sensitive)
        self.assertTrue(all(active for active, _s in checks.values()))

    def test_error_without_known_info_zeros_toggles(self):
        checks, _ro = gui.params_render_plan(None, "boom")
        for active, sensitive in checks.values():
            self.assertFalse(active)
            self.assertFalse(sensitive)

    def test_unknown_info_zeros_everything(self):
        checks, read_onlys = gui.params_render_plan(None, None)
        for active, sensitive in checks.values():
            self.assertFalse(active)
            self.assertFalse(sensitive)
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


if __name__ == "__main__":
    unittest.main()

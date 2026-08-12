import unittest

from src.rapoo_vt7 import i18n


class I18nParityTest(unittest.TestCase):
    def test_all_locales_share_the_same_keys(self):
        keys = {code: set(lang.keys()) for code, lang in i18n.LANGS.items()}
        reference = next(iter(keys.values()))
        self.assertGreaterEqual(len(reference), 10)
        for code, k in keys.items():
            self.assertEqual(
                k,
                reference,
                "locale %s is missing/extra keys vs the reference set" % code,
            )

    def test_rf_keys_present_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            for key in (
                "rf_section",
                "rf_status",
                "rf_adaptive",
                "rf_full",
                "rf_low_on",
                "rf_low_off",
                "rf_full_toggle",
                "rf_low_toggle",
                "rf_changed",
                "rf_error",
            ):
                self.assertIn(key, lang, "locale %s missing key %r" % (code, key))

    def test_param_keys_present_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            for key in (
                "param_section",
                "param_unknown",
                "param_error",
                "param_changed",
                "param_on",
                "param_off",
                "param_read_only",
                "param_motion_sync",
                "param_glass_track",
                "param_dc_switch",
                "param_linear_ripple",
                "param_sensor_angle",
                "param_press_debounce",
                "param_release_debounce",
                "param_sleep_time",
                "param_lift_off",
                "param_low_power",
                "param_power_save",
            ):
                self.assertIn(key, lang, "locale %s missing key %r" % (code, key))

    def test_every_param_name_bound_to_i18n_key(self):
        from src.rapoo_vt7 import parameters

        expected = {"param_" + name for name, _o, _e in parameters.PARAMS}
        for code, lang in i18n.LANGS.items():
            missing = {key for key in expected if key not in lang}
            self.assertEqual(
                missing,
                set(),
                "locale %s missing derived param keys: %r" % (code, missing),
            )

    def test_status_format_placeholders(self):
        for code, lang in i18n.LANGS.items():
            try:
                lang["rf_status"].format(rf="x", low="y")
                lang["perf_status"].format(hz=1000, name="x")
                lang["rf_changed"].format(rf="x")
                lang["param_changed"].format(param="x", state="on")
                lang["param_error"].format(error="x")
            except (KeyError, IndexError) as exc:
                self.fail("locale %s placeholder mismatch: %s" % (code, exc))

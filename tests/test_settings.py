import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import protocol, settings
from src.rapoo_vt7.settings import Field


class RegistryTest(unittest.TestCase):
    def test_registry_covers_feature_table(self):
        expected = {
            "dpi_x_list",
            "dpi_y_list",
            "dpi_current",
            "dpi_enable_gear",
            "sensor_mode",
            "mouse_report",
            "mouse_scan",
            "mouse_slight",
            "mouse_motion",
            "rf_strengthen_switch",
            "low_power_warn_switch",
            "mouse_downdelay",
            "mouse_liftdelay",
            "mouse_sleeptime",
            "mouse_linear_ripple",
            "mouse_sensorangle",
            "mouse_glass",
            "mouse_lowpower",
            "mouse_powersave",
            "mouse_dcswitch",
            "mouse_left",
            "mouse_middle",
            "mouse_right",
            "mouse_dpi_add",
            "mouse_dpi_reduce",
            "mouse_forward",
            "mouse_back",
            "mouse_scroll_forward",
            "mouse_scroll_back",
            "mouse_scroll_right",
            "mouse_scroll_left",
            "mouse_bottom",
            "mouse_ble",
            "config_name",
        }
        self.assertEqual(set(settings.FIELDS), expected)

    def test_addresses_match_absolute_bank0_hex(self):
        cases = {
            "dpi_x_list": 0x0888,
            "dpi_y_list": 0x08C8,
            "dpi_current": 0x0898,
            "dpi_enable_gear": 0x0896,
            "sensor_mode": 0x08DC,
            "mouse_report": 0x0880,
            "mouse_scan": 0x0881,
            "mouse_slight": 0x0884,
            "mouse_motion": 0x0885,
            "rf_strengthen_switch": 0x08D8,
            "low_power_warn_switch": 0x08D8,
            "mouse_downdelay": 0x08C0,
            "mouse_liftdelay": 0x08C1,
            "mouse_sleeptime": 0x08C2,
            "mouse_linear_ripple": 0x08C3,
            "mouse_sensorangle": 0x08C4,
            "mouse_glass": 0x08C5,
            "mouse_lowpower": 0x08C6,
            "mouse_powersave": 0x08AC,
            "mouse_dcswitch": 0x08DA,
            "mouse_left": 0x0600,
            "mouse_middle": 0x0604,
            "mouse_right": 0x0608,
            "mouse_dpi_add": 0x060C,
            "mouse_dpi_reduce": 0x0610,
            "mouse_forward": 0x0614,
            "mouse_back": 0x0618,
            "mouse_scroll_forward": 0x0624,
            "mouse_scroll_back": 0x0628,
            "mouse_scroll_right": 0x062C,
            "mouse_scroll_left": 0x0630,
            "mouse_bottom": 0x0634,
            "mouse_ble": 0x0638,
            "config_name": 0x09EC,
        }
        self.assertEqual(set(cases), set(settings.FIELDS))
        for name, absolute in cases.items():
            with self.subTest(field=name):
                addr = settings.FIELDS[name].addr
                self.assertEqual(len(addr), 2)
                self.assertEqual((addr[1] << 8) | addr[0], absolute)

    def test_derived_addresses_match_eeprom_bank0(self):
        for name, field in settings.FIELDS.items():
            with self.subTest(field=name):
                absolute = (field.addr[1] << 8) | field.addr[0]
                self.assertEqual(
                    field.addr,
                    tuple(protocol.eeprom_bank0(absolute - protocol.EEPROM_BANK0_BASE)),
                )

    def test_registry_covers_docs_feature_table_addresses(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "docs", "FEATURES.md"), encoding="utf-8") as f:
            text = f.read()
        start = text.index("## 2.")
        end = text.index("## 3.")
        section = text[start:end]
        not_applicable = section.index("### F.")
        doc_addresses = set(re.findall(r"0x[0-9A-F]{4}", section[:not_applicable]))
        registered = {
            (field.addr[1] << 8) | field.addr[0] for field in settings.FIELDS.values()
        }
        self.assertTrue(doc_addresses)
        for addr in sorted(doc_addresses):
            with self.subTest(doc_address=addr):
                self.assertIn(int(addr, 16), registered)

    def test_baseline_path_constant(self):
        self.assertEqual(
            settings.EEPROM_BASELINE_PATH,
            os.path.expanduser("~/.cache/rapoo-vt7/eeprom_baseline.json"),
        )


class EncodeTest(unittest.TestCase):
    def test_uint_1byte_roundtrip(self):
        f = settings.FIELDS["dpi_current"]
        self.assertEqual(f.encode(5), b"\x05")
        self.assertEqual(f.decode(b"\x05"), 5)

    def test_uint_2byte_le_roundtrip(self):
        f = settings.FIELDS["dpi_x_list"]
        self.assertEqual(f.encode(5000), b"\x88\x13")
        self.assertEqual(f.decode(b"\x88\x13"), 5000)
        self.assertEqual(len(f.encode(26000)), 2)

    def test_bool(self):
        f = Field((0x96, 0x08), type="bool")
        self.assertEqual(f.encode(True), b"\x01")
        self.assertEqual(f.encode(False), b"\x00")
        self.assertEqual(f.decode(b"\x01"), True)
        self.assertEqual(f.decode(b"\x00"), False)

    def test_string_padded(self):
        f = settings.FIELDS["config_name"]
        self.assertEqual(f.size, 16)
        self.assertEqual(f.encode("VT7"), b"VT7" + b"\x00" * 13)
        self.assertEqual(f.decode(b"VT7" + b"\x00" * 13), "VT7")

    def test_string_truncated_to_size(self):
        f = settings.FIELDS["config_name"]
        self.assertEqual(len(f.encode("A" * 20)), 16)

    def test_string_null_trimmed(self):
        f = settings.FIELDS["config_name"]
        self.assertEqual(f.decode(b"VT7\x00\x11\x22"), "VT7")

    def test_out_of_range_raises_value_error(self):
        f = settings.FIELDS["dpi_x_list"]
        with self.assertRaises(ValueError):
            f.encode(49)
        with self.assertRaises(ValueError):
            f.encode(26001)

    def test_does_not_fit_in_size_raises_value_error(self):
        f = settings.FIELDS["dpi_current"]
        with self.assertRaises(ValueError):
            f.encode(300)
        with self.assertRaises(ValueError):
            f.encode(-1)

    def test_decode_is_unvalidated(self):
        f = settings.FIELDS["dpi_x_list"]
        self.assertEqual(f.decode(b"\xff\xff"), 65535)

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            Field((0x00, 0x06), type="nope").encode(1)


if __name__ == "__main__":
    unittest.main()

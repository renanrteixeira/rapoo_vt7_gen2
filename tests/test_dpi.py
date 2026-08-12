import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import dpi, protocol, settings


class FakeDev:
    """RapooDevice stand-in: read_eeprom returns the address bytes as data
    unless `data` overrides a value at a given absolute address; write_eeprom
    records the write and stores it so the re-read verify sees it."""

    def __init__(self, data=None):
        self.path = "/dev/hidraw2"
        self.data = dict(data or {})
        self.writes = []

    def read_eeprom(self, addr, length=1):
        base = (addr[1] << 8) | addr[0]
        if base in self.data:
            data = bytes(self.data[base])
        else:
            data = bytes((base + i) & 0xFF for i in range(length))
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + len(data)] = data
        return bytes(resp)

    def write_eeprom(self, addr, data):
        self.writes.append(((addr[1] << 8) | addr[0], bytes(data)))
        base = (addr[1] << 8) | addr[0]
        self.data[base] = bytes(data)
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        return bytes(resp)

    def write_eeprom_verify(self, addr, data):
        self.write_eeprom(addr, data)
        return self.read_eeprom(addr, len(data))[
            protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + len(data)
        ]


def sample_info(**overrides):
    """A 3-gear config ([800, 1200, 5000]) used by add/delete tests."""
    info = {
        "gear": 1,
        "enable": 2,
        "x": [800, 1200, 5000, 1600, 3200, 6400, 26000],
        "y": [800, 1200, 5000, 1600, 3200, 6400, 26000],
    }
    info.update(overrides)
    return info


class ReadDpiTest(unittest.TestCase):
    def test_reads_gear_enable_and_tables(self):
        dev = FakeDev(
            data={
                0x0898: b"\x02",                       # dpi_current = gear 2
                0x0896: b"\x01",                       # enable
                0x0888 + 2 * 2: b"\x88\x13",           # x[2] = 5000
                0x08C8 + 2 * 2: b"\x88\x13",           # y[2] = 5000
            }
        )
        info = dpi.read_dpi(dev)
        self.assertEqual(info["gear"], 2)
        self.assertEqual(info["enable"], 1)
        self.assertEqual(len(info["x"]), dpi.GEAR_LENGTH)
        self.assertEqual(len(info["y"]), dpi.GEAR_LENGTH)
        self.assertEqual(info["x"][2], 5000)
        self.assertEqual(info["y"][2], 5000)

    def test_short_reply_raises(self):
        dev = FakeDev()

        def short(addr, length):
            resp = bytearray(protocol.EEPROM_DATA_OFFSET + 1)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = short
        with self.assertRaises(ValueError):
            dpi.read_dpi(dev)


class ActiveCountTest(unittest.TestCase):
    def test_count_is_enable_plus_one(self):
        self.assertEqual(dpi.active_count(0), 1)
        self.assertEqual(dpi.active_count(1), 2)
        self.assertEqual(dpi.active_count(6), 7)

    def test_clamped_to_gear_length(self):
        self.assertEqual(dpi.active_count(7), 7)
        self.assertEqual(dpi.active_count(0xFF), 7)


class ActiveGearsTest(unittest.TestCase):
    def test_factory_config_cycles_first_two_slots(self):
        info = sample_info(gear=1, enable=1,
                           x=[800, 5000, 800, 800, 800, 800, 800])
        self.assertEqual(dpi.active_gears(info), [(0, 800), (1, 5000)])

    def test_full_enable_lists_all_seven_slots(self):
        info = sample_info(enable=6)
        self.assertEqual(dpi.active_gears(info), list(enumerate(info["x"])))

    def test_missing_enable_means_single_gear(self):
        info = {"x": [800] * 7, "y": [800] * 7}
        self.assertEqual(dpi.active_gears(info), [(0, 800)])


class SetGearTest(unittest.TestCase):
    def test_writes_and_verifies_current_gear(self):
        dev = FakeDev()
        result = dpi.set_gear(dev, 3)
        self.assertEqual(result["gear"], 3)
        self.assertEqual(dev.writes, [(0x0898, b"\x03")])

    def test_gear_out_of_range_rejected(self):
        dev = FakeDev()
        for bad in (-1, 7, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dpi.set_gear(dev, bad)
        self.assertEqual(dev.writes, [])


class SetValueTest(unittest.TestCase):
    def test_sets_x_and_y_for_gear_in_place(self):
        dev = FakeDev()
        # sample_info: [800, 1200, 5000], current gear 1 (1200).
        info = sample_info()
        result = dpi.set_value(dev, info, 0, 1200, 2400)
        self.assertEqual(result["gear"], 0)
        self.assertEqual(result["x"], 1200)
        self.assertEqual(result["y"], 2400)
        self.assertFalse(result["applied"])
        self.assertEqual(result["current"], 1)
        self.assertEqual(result["cur_x"], 1200)
        # only the slot's X/Y are written (no list reorder, no enable, no re-select)
        self.assertEqual(dev.writes, [
            (0x0888, b"\xb0\x04"),
            (0x08C8, b"\x60\x09"),
        ])

    def test_editing_current_gear_is_applied(self):
        dev = FakeDev()
        info = sample_info(gear=1)  # current = 1200 at slot 1
        result = dpi.set_value(dev, info, 1, 5000)
        self.assertTrue(result["applied"])
        self.assertEqual(result["cur_x"], 5000)  # DPI in use = the new value
        self.assertEqual(dev.writes, [
            (0x088A, b"\x88\x13"),
            (0x08CA, b"\x88\x13"),
        ])

    def test_editing_other_gear_only_stores_value(self):
        dev = FakeDev()
        info = sample_info(gear=1)  # current = 1200 (slot 1)
        result = dpi.set_value(dev, info, 0, 5000)
        self.assertFalse(result["applied"])
        self.assertEqual(result["cur_x"], 1200)  # DPI in use unchanged
        self.assertEqual(dev.writes, [
            (0x0888, b"\x88\x13"),
            (0x08C8, b"\x88\x13"),
        ])

    def test_y_defaults_to_x(self):
        dev = FakeDev()
        result = dpi.set_value(dev, sample_info(gear=1), 0, 5000)
        self.assertEqual(result["y"], 5000)

    def test_invalid_values_rejected(self):
        dev = FakeDev()
        info = sample_info(gear=1)
        for bad in (49, 26050, 5055, 2501, "x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dpi.set_value(dev, info, 0, bad)
        self.assertEqual(dev.writes, [])

    def test_gear_out_of_active_range_rejected(self):
        dev = FakeDev()
        info = sample_info(enable=1)  # only slots 0..1 are in the cycle
        for bad in (-1, 2, 7, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dpi.set_value(dev, info, bad, 1200)
        self.assertEqual(dev.writes, [])


class SetGearsTest(unittest.TestCase):
    def test_writes_compact_list_and_enable(self):
        dev = FakeDev()
        result = dpi.set_gears(dev, [800, 1200], [800, 1200])
        self.assertEqual(result["list"], [800, 1200])
        self.assertEqual(result["enable"], 1)
        self.assertEqual(dev.writes, [
            (0x0888, b"\x20\x03\xb0\x04"),
            (0x08C8, b"\x20\x03\xb0\x04"),
            (0x0896, b"\x01"),
        ])

    def test_y_defaults_to_x(self):
        dev = FakeDev()
        dpi.set_gears(dev, [5000])
        self.assertEqual(dev.writes[0], (0x0888, (5000).to_bytes(2, "little")))
        self.assertEqual(dev.writes[1], (0x08C8, (5000).to_bytes(2, "little")))
        self.assertEqual(dev.writes[2], (0x0896, b"\x00"))

    def test_bad_length_rejected(self):
        dev = FakeDev()
        for bad in ([], list(range(8))):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dpi.set_gears(dev, bad)
        self.assertEqual(dev.writes, [])

    def test_x_y_length_mismatch_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            dpi.set_gears(dev, [800, 1200], [800])
        self.assertEqual(dev.writes, [])

    def test_invalid_value_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            dpi.set_gears(dev, [0, 1200])
        self.assertEqual(dev.writes, [])


class AddGearTest(unittest.TestCase):
    def test_appends_default_gear_sorted(self):
        dev = FakeDev()
        # active [800, 1200], current gear 1 (1200). Add 800 -> [800, 800, 1200].
        result = dpi.add_gear(dev, sample_info(enable=1))
        self.assertEqual(result["list"], [800, 800, 1200])
        self.assertEqual(result["enable"], 2)
        self.assertEqual(result["slot"], 0)
        self.assertEqual(result["x"], 800)
        # current keeps value 1200 -> slot 2
        self.assertEqual(result["current"], 2)
        self.assertEqual(dev.writes, [
            (0x0888, b"\x20\x03\x20\x03\xb0\x04"),
            (0x08C8, b"\x20\x03\x20\x03\xb0\x04"),
            (0x0896, b"\x02"),
            (0x0898, b"\x02"),
        ])

    def test_appends_explicit_value_sorted(self):
        dev = FakeDev()
        result = dpi.add_gear(dev, sample_info(enable=1), 5000)
        self.assertEqual(result["list"], [800, 1200, 5000])
        self.assertEqual(result["enable"], 2)
        self.assertEqual(result["slot"], 2)
        # current gear 1 (1200) keeps its slot
        self.assertEqual(result["current"], 1)

    def test_invalid_value_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            dpi.add_gear(dev, sample_info(enable=1), 5055)
        self.assertEqual(dev.writes, [])

    def test_full_list_rejected(self):
        dev = FakeDev()
        info = sample_info(enable=6)  # all 7 slots active
        with self.assertRaises(ValueError):
            dpi.add_gear(dev, info)
        self.assertEqual(dev.writes, [])


class DeleteGearTest(unittest.TestCase):
    def test_compacts_list_and_reselects_current(self):
        dev = FakeDev()
        result = dpi.delete_gear(dev, sample_info(gear=1), 1)
        self.assertEqual(result["list"], [800, 5000])
        self.assertEqual(result["enable"], 1)
        self.assertEqual(result["current"], 0)
        self.assertEqual(dev.writes, [
            (0x0888, b"\x20\x03\x88\x13"),
            (0x08C8, b"\x20\x03\x88\x13"),
            (0x0896, b"\x01"),
            (0x0898, b"\x00"),
        ])

    def test_deleting_current_gear_selects_first(self):
        dev = FakeDev()
        result = dpi.delete_gear(dev, sample_info(gear=0), 0)
        self.assertEqual(result["list"], [1200, 5000])
        self.assertEqual(result["current"], 0)
        self.assertEqual(dev.writes[-1], (0x0898, b"\x00"))

    def test_deleting_after_current_shifts_current(self):
        dev = FakeDev()
        result = dpi.delete_gear(dev, sample_info(gear=0), 2)
        self.assertEqual(result["list"], [800, 1200])
        self.assertEqual(result["current"], 0)
        self.assertEqual(dev.writes[-1], (0x0898, b"\x00"))

    def test_slot_out_of_active_range_rejected(self):
        dev = FakeDev()
        for bad in (3, -1, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    dpi.delete_gear(dev, sample_info(), bad)
        self.assertEqual(dev.writes, [])

    def test_deleting_last_gear_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            dpi.delete_gear(dev, sample_info(enable=0), 0)
        self.assertEqual(dev.writes, [])


if __name__ == "__main__":
    unittest.main()

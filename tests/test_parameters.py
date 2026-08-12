import unittest

from src.rapoo_vt7 import main, parameters as par, protocol
from src.rapoo_vt7.device import CommandTimeout

# --- fakes ---------------------------------------------------------------


class FakeDev:
    """RapooDevice stand-in: read_eeprom returns `data` for an address, or
    the address bytes; write_eeprom records the write and stores it."""

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
        self.data[(addr[1] << 8) | addr[0]] = bytes(data)
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        return bytes(resp)

    def write_eeprom_verify(self, addr, data):
        self.write_eeprom(addr, data)
        return self.read_eeprom(addr, len(data))[
            protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + len(data)
        ]


class ShortDev:
    def read_eeprom(self, addr, length=1):
        return b"\x00" * 4


class BoomParamDev(FakeDev):
    """FakeDev whose read_eeprom returns a short reply for the linear-correction
    byte (0x08C3), simulating one broken §C byte among healthy ones."""

    def read_eeprom(self, addr, length=1):
        if (addr[1] << 8) | addr[0] == 0x08C3:
            return b"\x00" * protocol.EEPROM_DATA_OFFSET
        return super().read_eeprom(addr, length)


class NoVerifyDev:
    def write_eeprom_verify(self, addr, data):
        return b"\xff" * len(data)


class FakeMonitor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        self.jobs.append((fn, on_done, on_error, wake))


# --- tests ---------------------------------------------------------------


class RegistryTest(unittest.TestCase):
    def test_three_confirmed_toggles_only(self):
        editable = [name for name, _o, e in par.PARAMS if e]
        self.assertEqual(editable, ["motion_sync", "glass_track", "dc_switch"])

    def test_all_section_c_fields_registered(self):
        self.assertEqual(
            {name for name, _o, _e in par.PARAMS},
            {
                "motion_sync",
                "glass_track",
                "dc_switch",
                "linear_ripple",
                "sensor_angle",
                "press_debounce",
                "release_debounce",
                "sleep_time",
                "lift_off",
                "low_power",
                "power_save",
            },
        )

    def test_addresses_match_bank0(self):
        cases = {
            "motion_sync": protocol.MOUSE_MOTION,
            "glass_track": protocol.MOUSE_GLASS,
            "dc_switch": protocol.MOUSE_DCSWITCH,
            "linear_ripple": protocol.MOUSE_LINEAR_RIPPLE,
            "sensor_angle": protocol.MOUSE_SENSORANGLE,
            "press_debounce": protocol.MOUSE_DOWNDELAY,
            "release_debounce": protocol.MOUSE_LIFTDELAY,
            "sleep_time": protocol.MOUSE_SLEEPTIME,
            "lift_off": protocol.MOUSE_SLIGHT,
            "low_power": protocol.MOUSE_LOWPOWER,
            "power_save": protocol.MOUSE_POWERSAVE,
        }
        for name, offset in cases.items():
            with self.subTest(param=name):
                self.assertEqual(
                    par.param_addr(name),
                    "0x{:04X}".format(protocol.EEPROM_BANK0_BASE + offset),
                )


class ReadParamTest(unittest.TestCase):
    def test_reads_confirmed_toggle(self):
        dev = FakeDev(data={0x0885: b"\x01"})
        p = par.read_param(dev, "motion_sync")
        self.assertEqual(p["addr"], "0x0885")
        self.assertEqual(p["raw"], 1)
        self.assertIs(p["value"], True)
        self.assertIs(p["editable"], True)

    def test_reads_state_param_as_raw_int(self):
        dev = FakeDev(data={0x08C3: b"\x03"})
        p = par.read_param(dev, "linear_ripple")
        self.assertEqual(p["value"], 3)
        self.assertFalse(p["editable"])

    def test_short_reply_raises(self):
        with self.assertRaises(ValueError):
            par.read_param(ShortDev(), "motion_sync")

    def test_non_binary_toggle_raises(self):
        dev = FakeDev(data={0x0885: b"\x02"})
        with self.assertRaises(ValueError):
            par.read_param(dev, "motion_sync")

    def test_non_binary_toggle_isolated_by_section(self):
        dev = FakeDev(data={0x0885: b"\x02", 0x08C5: b"\x01"})
        info = par.read_section(dev)
        self.assertIn("motion_sync", info["errors"])
        self.assertNotIn("glass_track", info["errors"])
        self.assertTrue(info["params"]["glass_track"]["value"])

    def test_unknown_name_raises(self):
        with self.assertRaises(KeyError):
            par.read_param(FakeDev(), "nope")


class ReadSectionTest(unittest.TestCase):
    def test_reads_all_params_without_errors(self):
        dev = FakeDev(
            data={
                0x0885: b"\x01",
                0x08C5: b"\x00",
                0x08DA: b"\x00",
                0x08C3: b"\x03",
                0x08C4: b"\x00",
                0x08C0: b"\x02",
                0x08C1: b"\x02",
                0x08C2: b"\x02",
                0x0884: b"\x01",
                0x08C6: b"\x00",
                0x08AC: b"\x00",
            }
        )
        info = par.read_section(dev)
        self.assertEqual(info["errors"], {})
        self.assertEqual(
            set(info["params"]), {name for name, _o, _e in par.PARAMS}
        )
        self.assertIs(info["params"]["motion_sync"]["value"], True)
        self.assertEqual(info["params"]["linear_ripple"]["value"], 3)

    def test_isolates_one_broken_field(self):
        dev = BoomParamDev(data={0x0885: b"\x01", 0x08C5: b"\x01"})
        info = par.read_section(dev)
        self.assertIn("linear_ripple", info["errors"])
        self.assertNotIn("motion_sync", info["errors"])
        self.assertEqual(info["params"]["motion_sync"]["value"], True)
        self.assertTrue(info["params"]["glass_track"])

    def test_command_timeout_propagates(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with self.assertRaises(CommandTimeout):
            par.read_section(dev)


class SetParamTest(unittest.TestCase):
    def test_writes_toggle_and_verifies(self):
        dev = FakeDev(data={0x0885: b"\x00"})
        res = par.set_param(dev, "motion_sync", True)
        self.assertEqual(dev.writes, [(0x0885, b"\x01")])
        self.assertTrue(res["value"])
        res = par.set_param(dev, "motion_sync", False)
        self.assertEqual(dev.writes[-1], (0x0885, b"\x00"))
        self.assertFalse(res["value"])

    def test_int_01_accepted(self):
        dev = FakeDev(data={0x08DA: b"\x00"})
        res = par.set_param(dev, "dc_switch", 1)
        self.assertEqual(dev.writes, [(0x08DA, b"\x01")])
        self.assertTrue(res["value"])

    def test_refuses_read_only_param(self):
        dev = FakeDev(data={0x08C3: b"\x03"})
        for name in ("linear_ripple", "press_debounce", "low_power"):
            with self.subTest(param=name):
                with self.assertRaises(ValueError):
                    par.set_param(dev, name, True)
        self.assertEqual(dev.writes, [])

    def test_invalid_enabled_rejected(self):
        dev = FakeDev()
        for bad in ("yes", None, 2, -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    par.set_param(dev, "motion_sync", bad)
        self.assertEqual(dev.writes, [])

    def test_verify_mismatch_raises_and_is_not_accepted(self):
        dev = NoVerifyDev()
        with self.assertRaises(ValueError):
            par.set_param(dev, "motion_sync", True)

    def test_unknown_name_raises_without_write(self):
        dev = FakeDev()
        with self.assertRaises(KeyError):
            par.set_param(dev, "nope", True)
        self.assertEqual(dev.writes, [])


class SetParamChoiceTest(unittest.TestCase):
    def test_writes_choice_and_verifies(self):
        dev = FakeDev(data={0x08C0: b"\x00"})
        res = par.set_param_choice(dev, "press_debounce", 4)
        self.assertEqual(dev.writes, [(0x08C0, b"\x04")])
        self.assertEqual(res["raw"], 4)
        self.assertEqual(res["value"], 4)
        self.assertTrue(res["option"])

    def test_encodes_signed_angle(self):
        dev = FakeDev(data={0x08C4: b"\x00"})
        res = par.set_param_choice(dev, "sensor_angle", -2)
        self.assertEqual(dev.writes[-1], (0x08C4, b"\xFE"))
        self.assertEqual(res["value"], -2)

    def test_encodes_lift_off_mm(self):
        dev = FakeDev(data={0x0884: b"\x01"})
        res = par.set_param_choice(dev, "lift_off", 1.5)
        self.assertEqual(dev.writes, [(0x0884, b"\x06")])
        self.assertEqual(res["value"], 1.5)

    def test_refuses_value_off_grid(self):
        dev = FakeDev(data={0x08C0: b"\x00"})
        with self.assertRaises(ValueError):
            par.set_param_choice(dev, "press_debounce", 7)
        self.assertEqual(dev.writes, [])

    def test_refuses_value_out_of_range(self):
        dev = FakeDev(data={0x08C2: b"\x02"})
        with self.assertRaises(ValueError):
            par.set_param_choice(dev, "sleep_time", 150)
        self.assertEqual(dev.writes, [])

    def test_refuses_param_without_options(self):
        dev = FakeDev(data={0x08C3: b"\x03"})
        with self.assertRaises(ValueError):
            par.set_param_choice(dev, "linear_ripple", 3)
        self.assertEqual(dev.writes, [])

    def test_verify_mismatch_raises(self):
        dev = NoVerifyDev()
        with self.assertRaises(ValueError):
            par.set_param_choice(dev, "press_debounce", 2)

    def test_unknown_name_raises(self):
        dev = FakeDev()
        with self.assertRaises(KeyError):
            par.set_param_choice(dev, "nope", 1)
        self.assertEqual(dev.writes, [])


class ChoiceMetadataTest(unittest.TestCase):
    def test_selectable_fields_declared(self):
        self.assertTrue(par.is_selectable("press_debounce"))
        self.assertTrue(par.is_selectable("release_debounce"))
        self.assertTrue(par.is_selectable("sleep_time"))
        self.assertTrue(par.is_selectable("sensor_angle"))
        self.assertTrue(par.is_selectable("lift_off"))
        self.assertFalse(par.is_selectable("linear_ripple"))
        self.assertFalse(par.is_selectable("low_power"))

    def test_ranges_match_a_hub(self):
        self.assertEqual(par.param_range("press_debounce"), (0, 32, 2))
        self.assertEqual(par.param_range("release_debounce"), (0, 32, 2))
        self.assertEqual(par.param_range("sleep_time"), (2, 120, 1))
        self.assertEqual(par.param_range("sensor_angle"), (-30, 30, 1))
        self.assertEqual(par.param_range("lift_off"), (1.0, 2.0, 0.1))

    def test_byte_round_trip(self):
        for name in ("press_debounce", "release_debounce", "sleep_time"):
            lo, hi, step = par.param_range(name)
            for v in range(lo, hi + 1, step):
                with self.subTest(param=name, value=v):
                    self.assertEqual(
                        par.byte_to_display(name, par.display_to_byte(name, v)),
                        v,
                    )
        for v in (-30, 0, 7, 30):
            self.assertEqual(
                par.byte_to_display("sensor_angle", par.display_to_byte("sensor_angle", v)),
                v,
            )
        for v in (1.0, 1.5, 2.0):
            self.assertEqual(
                par.byte_to_display("lift_off", par.display_to_byte("lift_off", v)),
                v,
            )

    def test_angle_signed_decode(self):
        self.assertEqual(par.byte_to_display("sensor_angle", 0), 0)
        self.assertEqual(par.byte_to_display("sensor_angle", 0xFE), -2)
        self.assertEqual(par.byte_to_display("sensor_angle", 30), 30)

    def test_choice_labels(self):
        self.assertEqual(par.choice_label("press_debounce", 4), "4 ms")
        self.assertEqual(par.choice_label("sleep_time", 10), "10 min")
        self.assertEqual(par.choice_label("lift_off", 1.5), "1.5 mm")
        self.assertEqual(par.choice_label("sensor_angle", 0), "0 °")


class MainParamTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        return app

    def test_on_set_param_submits_write_with_wake(self):
        app = self._app()
        app._on_set_param("motion_sync", True)
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        self.assertTrue(callable(on_error))
        state = fn(FakeDev(data={0x0885: b"\x00"}))
        self.assertTrue(state["value"])
        self.assertEqual(state["name"], "motion_sync")

    def test_on_set_param_never_writes_unconfirmed_field(self):
        app = self._app()
        app._on_set_param("linear_ripple", True)
        fn, _on_done, _on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)  # still attempted (user action)
        with self.assertRaises(ValueError):
            fn(FakeDev(data={0x08C3: b"\x03"}))


if __name__ == "__main__":
    unittest.main()
import unittest
from types import SimpleNamespace
from unittest import mock

from src.rapoo_vt7 import main, performance as perf, protocol

# --- fakes ---------------------------------------------------------------


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


class ShortDev:
    def read_eeprom(self, addr, length=1):
        return b"\x00" * 4


class NoVerifyDev:
    def write_eeprom_verify(self, addr, data):
        return b"\xff" * len(data)


class BadVerifyDev:
    """read_eeprom reports a byte at 0x08D8 but write_eeprom_verify returns a
    different value (simulating a readback that did not stick)."""

    def __init__(self, current=0x00):
        self.current = current
        self.writes = []

    def read_eeprom(self, addr, length=1):
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.EEPROM_DATA_OFFSET] = self.current
        return bytes(resp)

    def write_eeprom_verify(self, addr, data):
        self.writes.append(((addr[1] << 8) | addr[0], bytes(data)))
        return b"\xff"


class FakeMonitor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        self.jobs.append((fn, on_done, on_error, wake))


# --- tests ---------------------------------------------------------------


class RateIndexTest(unittest.TestCase):
    def test_maps_rate_codes_to_slots(self):
        self.assertEqual(perf.rate_index_from_code(8), 0)  # 125 Hz
        self.assertEqual(perf.rate_index_from_code(4), 1)  # 250 Hz
        self.assertEqual(perf.rate_index_from_code(2), 2)  # 500 Hz
        self.assertEqual(perf.rate_index_from_code(1), 3)  # 1000 Hz
        self.assertEqual(perf.rate_index_from_code(132), 4)  # 2000 Hz
        self.assertEqual(perf.rate_index_from_code(130), 5)  # 4000 Hz
        self.assertEqual(perf.rate_index_from_code(129), 6)  # 8000 Hz

    def test_accepts_raw_index(self):
        self.assertEqual(perf.rate_index_from_code(0), 0)
        self.assertEqual(perf.rate_index_from_code(6), 6)

    def test_unknown_value_falls_back_to_1000hz(self):
        self.assertEqual(perf.rate_index_from_code(255), perf.SLOT_DEFAULT)
        self.assertEqual(perf.rate_index_from_code(None), perf.SLOT_DEFAULT)

    def test_unhashable_input_falls_back_without_raising(self):
        self.assertEqual(perf.rate_index_from_code([8]), perf.SLOT_DEFAULT)
        self.assertEqual(perf.rate_index_from_code(b"\x08"), perf.SLOT_DEFAULT)


class ReadTableTest(unittest.TestCase):
    def test_reads_all_seven_slots(self):
        dev = FakeDev(data={0x08DC: bytes([0, 1, 2, 3, 4, 5, 0])})
        self.assertEqual(perf.read_table(dev), [0, 1, 2, 3, 4, 5, 0])

    def test_short_reply_raises(self):
        with self.assertRaises(ValueError):
            perf.read_table(ShortDev())


class ReadModeTest(unittest.TestCase):
    def test_reads_mode_for_slot(self):
        dev = FakeDev(data={0x08DF: bytes([4])})
        self.assertEqual(perf.read_mode(dev, 3), 4)

    def test_slot_out_of_range_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            perf.read_mode(dev, 7)
        with self.assertRaises(ValueError):
            perf.read_mode(dev, -1)


class RfBoomDev(FakeDev):
    """FakeDev whose read_eeprom fails for the shared RF byte (0x08D8),
    simulating a broken RF read while the mode slot still works."""

    def read_eeprom(self, addr, length=1):
        base = (addr[1] << 8) | addr[0]
        if base == (perf.RF_SHARED_ADDR[1] << 8) | perf.RF_SHARED_ADDR[0]:
            return b"\x00" * 3
        return super().read_eeprom(addr, length)


class ReadPerfStateTest(unittest.TestCase):
    def test_returns_mode_and_rf_together(self):
        dev = FakeDev(
            data={
                0x08DF: bytes([4]),  # slot 3 mode
                0x08D8: bytes([0x03]),  # RF full + low-power warn on
            }
        )
        info = perf.read_perf_state(dev, 3)
        self.assertEqual(info["slot"], 3)
        self.assertEqual(info["mode"], 4)
        self.assertEqual(info["rf"]["rf_strengthen_switch"], True)
        self.assertEqual(info["rf"]["low_power_warn_switch"], True)
        self.assertIsNone(info["rf_error"])

    def test_isolates_rf_read_failure(self):
        dev = RfBoomDev(data={0x08DF: bytes([2])})
        info = perf.read_perf_state(dev, 3)
        self.assertEqual(info["mode"], 2)
        self.assertIsNone(info["rf"])
        self.assertIsNotNone(info["rf_error"])

    def test_mode_read_failure_raises(self):
        dev = ShortDev()
        with self.assertRaises(ValueError):
            perf.read_perf_state(dev, 3)


class SetModeTest(unittest.TestCase):
    def test_writes_one_byte_at_slot_and_verifies(self):
        dev = FakeDev(data={0x08DC: bytes(7)})
        res = perf.set_mode(dev, 3, 4)
        self.assertEqual(res, {"slot": 3, "mode": 4})
        self.assertEqual(dev.writes, [(0x08DF, b"\x04")])
        self.assertEqual(perf.read_mode(dev, 3), 4)

    def test_invalid_mode_rejected(self):
        dev = FakeDev()
        for bad in (-1, 6, "3", None):
            with self.assertRaises(ValueError):
                perf.set_mode(dev, 3, bad)
        self.assertEqual(dev.writes, [])

    def test_slot_out_of_range_rejected(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            perf.set_mode(dev, 7, 1)
        with self.assertRaises(ValueError):
            perf.set_mode(dev, -1, 1)
        self.assertEqual(dev.writes, [])

    def test_verify_mismatch_raises(self):
        with self.assertRaises(ValueError):
            perf.set_mode(NoVerifyDev(), 3, 4)

    def test_modes_constant_has_six_entries(self):
        self.assertEqual(len(perf.PERF_MODES), 6)
        self.assertEqual(perf.PERF_MODES[0]["index"], 0)
        self.assertEqual(perf.PERF_MODES[5]["index"], 5)

    def test_selectable_modes_filtering(self):
        self.assertEqual(perf.selectable_modes(0), (0, 1))
        self.assertEqual(perf.selectable_modes(3), (1, 2, 3, 4, 5))
        self.assertEqual(perf.selectable_modes(6), (3, 4, 5))
        self.assertEqual(perf.selectable_modes(999), tuple(range(6)))


class MainPerfSlotTest(unittest.TestCase):
    def test_perf_slot_from_monitor_uses_rpt_usb(self):
        monitor = type("M", (), {})()
        monitor._rpt_usb = 4
        self.assertEqual(main._perf_slot_from_monitor(monitor), 1)

    def test_perf_slot_from_monitor_defaults_when_missing(self):
        monitor = type("M", (), {})()
        self.assertEqual(main._perf_slot_from_monitor(monitor), perf.SLOT_DEFAULT)

    def test_perf_slot_ignores_rpt_24g(self):
        # rpt_24g is NOT a rate code: with rpt_usb missing it must not select a
        # slot, even if rpt_24g carries a plausible-looking rate byte.
        monitor = type("M", (), {})()
        monitor._rpt_usb = None
        monitor._rpt_24g = 8
        self.assertEqual(main._perf_slot_from_monitor(monitor), perf.SLOT_DEFAULT)


class RfReadTest(unittest.TestCase):
    def test_reads_shared_byte_and_decodes_both_switches(self):
        dev = FakeDev(data={0x08D8: b"\x03"})
        state = perf.read_rf(dev)
        self.assertEqual(state["addr"], "0x08D8")
        self.assertEqual(state["raw"], 3)
        self.assertTrue(state["rf_strengthen_switch"])
        self.assertTrue(state["low_power_warn_switch"])

    def test_read_exposes_state_consistently(self):
        # Both switches come from the same byte: bit 0 = RF, bit 1 = low-power.
        self.assertEqual(perf.read_rf(FakeDev(data={0x08D8: b"\x01"})), {
            "addr": "0x08D8",
            "raw": 1,
            "rf_strengthen_switch": True,
            "low_power_warn_switch": False,
        })
        self.assertEqual(perf.read_rf(FakeDev(data={0x08D8: b"\x02"})), {
            "addr": "0x08D8",
            "raw": 2,
            "rf_strengthen_switch": False,
            "low_power_warn_switch": True,
        })

    def test_read_failure_surfaces_error(self):
        with self.assertRaises(ValueError):
            perf.read_rf(ShortDev())


class RfWriteTest(unittest.TestCase):
    def test_rf_strengthen_write_preserves_low_power_bit(self):
        dev = FakeDev(data={0x08D8: b"\x02"})  # low-power on, RF off
        state = perf.write_rf_strengthen(dev, True)
        self.assertEqual(dev.writes, [(0x08D8, b"\x03")])
        self.assertTrue(state["rf_strengthen_switch"])
        self.assertTrue(state["low_power_warn_switch"])

    def test_rf_strengthen_disable_preserves_other_bits(self):
        dev = FakeDev(data={0x08D8: b"\x03"})
        state = perf.write_rf_strengthen(dev, False)
        self.assertEqual(dev.writes, [(0x08D8, b"\x02")])
        self.assertFalse(state["rf_strengthen_switch"])
        self.assertTrue(state["low_power_warn_switch"])

    def test_low_power_write_preserves_rf_bit(self):
        dev = FakeDev(data={0x08D8: b"\x01"})  # RF full, warning off
        state = perf.write_low_power_warn(dev, True)
        self.assertEqual(dev.writes, [(0x08D8, b"\x03")])
        self.assertTrue(state["rf_strengthen_switch"])
        self.assertTrue(state["low_power_warn_switch"])

    def test_verify_mismatch_raises_and_is_not_accepted(self):
        dev = BadVerifyDev(current=0x00)
        with self.assertRaises(ValueError):
            perf.write_rf_strengthen(dev, True)
        self.assertEqual(dev.writes, [(0x08D8, b"\x01")])

    def test_invalid_enabled_value_rejected(self):
        dev = FakeDev()
        for bad in ("yes", None, 2, -1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    perf.write_rf_strengthen(dev, bad)
                with self.assertRaises(ValueError):
                    perf.write_low_power_warn(dev, bad)
        self.assertEqual(dev.writes, [])


class RfSharedMaskTest(unittest.TestCase):
    def test_writes_never_zero_unrelated_bits(self):
        # Full byte: toggling either field must leave all other bits intact.
        dev = FakeDev(data={0x08D8: b"\xff"})
        perf.write_rf_strengthen(dev, True)
        self.assertEqual(dev.writes, [(0x08D8, b"\xff")])
        dev = FakeDev(data={0x08D8: b"\xfe"})
        perf.write_rf_strengthen(dev, False)
        self.assertEqual(dev.writes, [(0x08D8, b"\xfe")])
        dev = FakeDev(data={0x08D8: b"\xfd"})
        perf.write_low_power_warn(dev, True)
        self.assertEqual(dev.writes, [(0x08D8, b"\xff")])

    def test_both_fields_share_one_address(self):
        self.assertEqual(
            perf.RF_SHARED_ADDR,
            tuple(protocol.eeprom_bank0(protocol.RF_STRENGTHEN_SWITCH)),
        )
        self.assertEqual(
            protocol.RF_STRENGTHEN_SWITCH, protocol.LOW_POWE_WARN_SWITCH
        )
        self.assertNotEqual(protocol.RF_STRENGTHEN_MASK, protocol.LOW_POWE_WARN_MASK)


class PollingRateHzTest(unittest.TestCase):
    def test_maps_all_codes_to_hz(self):
        self.assertEqual(perf.rate_hz(8), 125)
        self.assertEqual(perf.rate_hz(4), 250)
        self.assertEqual(perf.rate_hz(2), 500)
        self.assertEqual(perf.rate_hz(1), 1000)
        self.assertEqual(perf.rate_hz(132), 2000)
        self.assertEqual(perf.rate_hz(130), 4000)
        self.assertEqual(perf.rate_hz(129), 8000)

    def test_unknown_value_falls_back_to_default_hz(self):
        self.assertEqual(perf.rate_hz(255), 1000)
        self.assertEqual(perf.rate_hz(None), 1000)


class SetRateTest(unittest.TestCase):
    def _addr(self):
        return tuple(protocol.eeprom_bank0(protocol.MOUSE_REPORT))

    def test_writes_rate_code_and_returns_triple(self):
        dev = FakeDev()
        result = perf.set_rate(dev, 2000)
        self.assertEqual(result, {"hz": 2000, "code": 132, "slot": 4})
        self.assertEqual(dev.writes, [((0x0880), b"\x84")])
        self.assertEqual(dev.data[0x0880], b"\x84")

    def test_restores_rate_and_code_from_code_table(self):
        dev = FakeDev()
        perf.set_rate(dev, 125)
        self.assertEqual(dev.writes[0], ((0x0880), b"\x08"))
        perf.set_rate(dev, 8000)
        self.assertEqual(dev.writes[-1], ((0x0880), b"\x81"))

    def test_rejects_invalid_rate(self):
        with self.assertRaises(ValueError):
            perf.set_rate(FakeDev(), 999)
        with self.assertRaises(ValueError):
            perf.set_rate(FakeDev(), True)

    def test_verify_mismatch_raises(self):
        dev = NoVerifyDev()
        with self.assertRaises(ValueError):
            perf.set_rate(dev, 1000)

    def test_short_reply_raises(self):
        class ShortWriteDev:
            def read_eeprom(self, addr, length=1):
                return b"\x00" * (protocol.EEPROM_DATA_OFFSET - 1)

            def write_eeprom_verify(self, addr, data):
                return self.read_eeprom(addr, len(data))[
                    protocol.EEPROM_DATA_OFFSET:
                ]

        with self.assertRaises(ValueError):
            perf.set_rate(ShortWriteDev(), 1000)


class MainRateTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = SimpleNamespace(_lang="pt_BR")
        return app

    def test_on_set_rate_submits_write_with_wake(self):
        app = self._app()
        app._on_set_rate(4000)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        result = fn(FakeDev())
        self.assertEqual(result["hz"], 4000)
        self.assertEqual(result["slot"], 5)

    def test_rate_changed_refreshes_perf_for_new_slot(self):
        app = self._app()
        refreshed = []

        def refresh(slot=None):
            refreshed.append(slot)

        app._refresh_perf = refresh
        with mock.patch.object(main.Notify.Notification, "new"):
            app._rate_changed({"hz": 2000, "code": 132, "slot": 4})
        self.assertEqual(refreshed, [4])


class MainPerfTest(unittest.TestCase):
    def _app(self, perf_info=None):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = SimpleNamespace(
            _lang="pt_BR",
            get_perf_info=lambda: perf_info,
            set_perf_error=lambda _msg: None,
        )
        return app

    def test_on_set_perf_submits_mode_write_for_displayed_slot_with_wake(self):
        app = self._app({"slot": 3, "mode": 1, "rf": None, "rf_error": None})
        app._on_set_perf(4)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        result = fn(FakeDev())
        # Writes to 0x08DC + displayed slot 3, not the live monitor rate.
        self.assertEqual(result, {"slot": 3, "mode": 4})

    def test_on_set_perf_targets_displayed_slot_not_live_rpt_usb(self):
        # The monitor's rpt_usb lags after a rate change; the mode write must
        # target the slot the window is showing, not the reported rate.
        app = self._app({"slot": 5, "mode": 3, "rf": None, "rf_error": None})
        app._on_set_perf(4)
        fn = app._monitor.jobs[0][0]
        dev = FakeDev()
        result = fn(dev)
        self.assertEqual(result, {"slot": 5, "mode": 4})
        self.assertEqual(dev.writes, [((0x08E1), b"\x04")])

    def test_on_set_perf_rejects_mode_not_selectable_in_slot(self):
        errors = []
        app = self._app({"slot": 0, "mode": 0, "rf": None, "rf_error": None})
        app._perf_error = errors.append
        app._on_set_perf(5)  # slot 0 only offers (0, 1)
        self.assertEqual(app._monitor.jobs, [])
        self.assertEqual(len(errors), 1)

    def test_on_set_perf_falls_back_to_monitor_slot_when_tab_empty(self):
        app = self._app(None)
        app._monitor._rpt_usb = 129  # 8000 Hz -> slot 6
        app._on_set_perf(4)
        fn = app._monitor.jobs[0][0]
        result = fn(FakeDev())
        self.assertEqual(result, {"slot": 6, "mode": 4})

    def test_perf_changed_refreshes_using_written_slot(self):
        app = self._app(None)
        refreshed = []

        def refresh(slot=None):
            refreshed.append(slot)

        app._refresh_perf = refresh
        with mock.patch.object(main.Notify.Notification, "new"):
            app._perf_changed({"slot": 4, "mode": 3})
        self.assertEqual(refreshed, [4])

    def test_perf_changed_survives_out_of_range_mode_byte(self):
        app = self._app(None)
        app._refresh_perf = lambda slot=None: None
        with mock.patch.object(main.Notify.Notification, "new") as m:
            app._perf_changed({"slot": 3, "mode": 9})
        self.assertEqual(m.call_count, 1)

    def test_maybe_refresh_perf_retries_on_isolated_rf_error(self):
        app = self._app({"slot": 3, "mode": 1, "rf": None, "rf_error": "boom"})
        refreshed = []
        app._refresh_perf = lambda slot=None: refreshed.append(slot)
        app._maybe_refresh_perf()
        self.assertEqual(len(refreshed), 1)

    def test_maybe_refresh_perf_retries_when_tab_empty(self):
        app = self._app(None)
        refreshed = []
        app._refresh_perf = lambda slot=None: refreshed.append(slot)
        app._maybe_refresh_perf()
        self.assertEqual(len(refreshed), 1)

    def test_maybe_refresh_perf_skips_when_healthy(self):
        app = self._app({"slot": 3, "mode": 1, "rf": {}, "rf_error": None})
        refreshed = []
        app._refresh_perf = lambda slot=None: refreshed.append(slot)
        app._maybe_refresh_perf()
        self.assertEqual(refreshed, [])


class MainRfTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = SimpleNamespace(set_perf_error=lambda _msg: None)
        return app

    def test_on_set_rf_rejects_unknown_field(self):
        errors = []
        app = self._app()
        app._perf_error = errors.append
        app._on_set_rf("bogus", True)
        self.assertEqual(app._monitor.jobs, [])
        self.assertEqual(len(errors), 1)

    def test_on_set_rf_submits_masked_write_with_wake(self):
        app = self._app()
        app._on_set_rf("rf", True)
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        self.assertTrue(callable(on_error))
        # Running the task writes only the RF bit and preserves the low-power
        # bit that was already set.
        state = fn(FakeDev(data={0x08D8: b"\x02"}))
        self.assertTrue(state["rf_strengthen_switch"])
        self.assertTrue(state["low_power_warn_switch"])

    def test_on_set_lowpow_submits_masked_write_with_wake(self):
        app = self._app()
        app._on_set_rf("lowpow", False)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        state = fn(FakeDev(data={0x08D8: b"\x01"}))  # RF full, warning on
        self.assertTrue(state["rf_strengthen_switch"])
        self.assertFalse(state["low_power_warn_switch"])


if __name__ == "__main__":
    unittest.main()

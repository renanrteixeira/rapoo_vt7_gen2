import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import battery, protocol
from src.rapoo_vt7.battery import BatteryMonitor
from src.rapoo_vt7.device import CommandTimeout, DeviceNotFound


class FakeClock:
    """Fake clock for time.monotonic() — deterministic in tests."""

    def __init__(self, start=1000.0):
        self.t = start

    def monotonic(self):
        return self.t

    def advance(self, delta):
        self.t += delta


class FakeDev:
    """Simula um RapooDevice aberto (interface receptor ou cabo USB)."""

    def __init__(
        self,
        path,
        prefix,
        battery=(None, None),
        clock=None,
        read_delta=1.0,
        reads=(),
    ):
        self.path = path
        self.prefix = prefix
        self._battery = battery
        self.clock = clock
        self.read_delta = read_delta
        self._reads = list(reads)
        self.query_count = 0
        self.closed = False

    def open(self):
        return self

    def get_battery(self):
        self.query_count += 1
        if callable(self._battery):
            return self._battery()
        if self._battery[0] is None:
            raise CommandTimeout("asleep")
        return self._battery

    def read_report(self, timeout):
        if self.clock is not None:
            self.clock.advance(self.read_delta)
        if self._reads:
            return self._reads.pop(0)
        return None

    def close(self):
        self.closed = True


def passive_report(mode, status, percent):
    """Report passivo (rid 7) com data[1] nibble baixo = modo."""
    data = bytearray(19)
    data[0] = protocol.REPORT_PASSIVE
    data[1] = mode & 0x0F
    data[7] = status
    data[8] = percent
    return bytes(data)


class Collector:
    def __init__(self):
        self.updates = []
        self.states = []

    def on_update(self, percent, charging=False, mode=None):
        self.updates.append((percent, charging, mode))

    def on_state(self, name, **kwargs):
        self.states.append((name, kwargs))


class QueryBatteryTest(unittest.TestCase):
    def test_usb_interface_sets_mode_usb_and_charging(self):
        dev = FakeDev(
            "/dev/hidraw5",
            protocol.PREFIX_USB,
            battery=(protocol.BATTERY_STATUS_CHARGING, 97),
        )
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._query_battery(dev)
        self.assertEqual(col.updates, [(97, True, protocol.MODE_USB)])
        self.assertEqual(mon._mode, protocol.MODE_USB)
        self.assertEqual(col.states[0][0], "connected")

    def test_wireless_interface_sets_mode_wireless(self):
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 55),
        )
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._query_battery(dev)
        self.assertEqual(col.updates, [(55, False, protocol.MODE_WIRELESS)])
        self.assertEqual(mon._mode, protocol.MODE_WIRELESS)

    def test_invalid_status_skips_update(self):
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_INVALID, 0),
        )
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._query_battery(dev)
        self.assertEqual(col.updates, [])
        self.assertEqual(col.states[0][0], "connected")


class PassiveReportTest(unittest.TestCase):
    def test_24g_report_updates(self):
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._handle_report(
            passive_report(protocol.MODE_WIRELESS, protocol.BATTERY_STATUS_OK, 60)
        )
        self.assertEqual(col.updates, [(60, False, protocol.MODE_WIRELESS)])

    def test_usb_report_updates_charging(self):
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._handle_report(
            passive_report(protocol.MODE_USB, protocol.BATTERY_STATUS_CHARGING, 97)
        )
        self.assertEqual(col.updates, [(97, True, protocol.MODE_USB)])

    def test_short_or_wrong_rid_ignored(self):
        col = Collector()
        mon = BatteryMonitor(on_update=col.on_update, on_state=col.on_state)
        mon._handle_report(bytes([protocol.REPORT_PASSIVE]))  # curto
        mon._handle_report(bytes([9]) + bytes(18))  # rid errado
        self.assertEqual(col.updates, [])
        self.assertEqual(col.states, [])


class PollTest(unittest.TestCase):
    def test_awake_silent_rescans_after_recheck(self):
        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw5",
            protocol.PREFIX_USB,
            battery=(protocol.BATTERY_STATUS_CHARGING, 80),
            clock=clock,
            read_delta=1.0,
        )
        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=999.0,
            recheck=3.0,
        )
        with mock.patch.object(battery.time, "monotonic", clock.monotonic):
            mon._poll(dev)
        self.assertEqual(col.updates, [(80, True, protocol.MODE_USB)])
        self.assertEqual(dev.query_count, 1)

    def test_asleep_silent_sends_no_queries_and_returns(self):
        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_CHARGING, 80),
            clock=clock,
            read_delta=1.0,
        )
        mon = BatteryMonitor(recheck=1.0, fallback=999.0)
        mon._asleep = True
        with mock.patch.object(battery.time, "monotonic", clock.monotonic):
            mon._poll(dev)
        self.assertEqual(dev.query_count, 0)
        self.assertTrue(mon._asleep)

    def test_fallback_query_then_asleep(self):
        calls = {"n": 0}

        def batt():
            calls["n"] += 1
            if calls["n"] == 1:
                return (protocol.BATTERY_STATUS_CHARGING, 90)
            raise CommandTimeout("asleep")

        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=batt,
            clock=clock,
            read_delta=1.0,
        )
        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=2.0,
            recheck=10.0,
        )
        with mock.patch.object(battery.time, "monotonic", clock.monotonic):
            mon._poll(dev)
        self.assertEqual(calls["n"], 2)
        self.assertTrue(mon._asleep)
        self.assertEqual(mon._mode, protocol.MODE_WIRELESS)
        self.assertEqual(col.updates, [(90, True, protocol.MODE_WIRELESS)])
        self.assertIn(("asleep", {}), col.states)

    def test_refresh_wakes_asleep_and_queries(self):
        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 50),
            clock=clock,
            read_delta=1.0,
        )
        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=999.0,
            recheck=3.0,
        )
        mon._asleep = True
        mon.request_refresh()
        with mock.patch.object(battery.time, "monotonic", clock.monotonic):
            mon._poll(dev)
        self.assertEqual(dev.query_count, 1)
        self.assertEqual(col.updates, [(50, False, protocol.MODE_WIRELESS)])


class InterfaceChangeTest(unittest.TestCase):
    def test_run_wakes_up_when_cable_plugged(self):
        receiver = FakeDev(
            "/dev/hidraw1", protocol.PREFIX_WIRELESS, battery=(None, None)
        )
        usb = FakeDev(
            "/dev/hidraw5",
            protocol.PREFIX_USB,
            battery=(protocol.BATTERY_STATUS_CHARGING, 80),
        )
        queue = [receiver, receiver, usb]
        state = {"i": 0}

        def factory():
            i = state["i"]
            state["i"] += 1
            return queue[min(i, len(queue) - 1)]

        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=999.0,
            recheck=0.25,
            retry=0.05,
        )
        with mock.patch.object(battery, "RapooDevice", factory):
            mon.start()
            time.sleep(1.8)
            mon.stop()
            mon._thread.join(3)

        self.assertFalse(mon._thread.is_alive())
        self.assertTrue(any(n == "asleep" for n, _ in col.states))
        usb_updates = [u for u in col.updates if u[2] == protocol.MODE_USB]
        self.assertTrue(usb_updates, "no USB-mode update after plugging the cable")
        self.assertEqual(usb_updates[0], (80, True, protocol.MODE_USB))
        self.assertEqual(mon._dev_path, "/dev/hidraw5")

    def test_run_reconnects_after_device_gone(self):
        clock = FakeClock()
        dev1 = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 80),
            clock=clock,
            read_delta=1.0,
        )
        dev2 = FakeDev(
            "/dev/hidraw2",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 60),
            clock=clock,
            read_delta=1.0,
        )

        class Gone:
            def open(self):
                raise DeviceNotFound("gone")

            def close(self):
                pass

        queue = [dev1, Gone(), Gone(), dev2, dev2, dev2]
        state = {"i": 0}

        def factory():
            i = state["i"]
            state["i"] += 1
            return queue[min(i, len(queue) - 1)]

        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=999.0,
            recheck=0.25,
            retry=0.05,
        )
        with mock.patch.object(battery, "RapooDevice", factory):
            mon.start()
            time.sleep(1.5)
            mon.stop()
            mon._thread.join(3)

        self.assertFalse(mon._thread.is_alive())
        names = [n for n, _ in col.states]
        self.assertIn("disconnected", names)
        self.assertGreaterEqual(names.count("connected"), 2)
        self.assertIn((80, False, protocol.MODE_WIRELESS), col.updates)
        self.assertIn((60, False, protocol.MODE_WIRELESS), col.updates)
        self.assertEqual(mon._dev_path, "/dev/hidraw2")


class TaskQueueTest(unittest.TestCase):
    def _run_monitor(self, queue_devs):
        state = {"i": 0}

        def factory():
            i = state["i"]
            state["i"] += 1
            return queue_devs[min(i, len(queue_devs) - 1)]

        col = Collector()
        mon = BatteryMonitor(
            on_update=col.on_update,
            on_state=col.on_state,
            fallback=999.0,
            recheck=0.25,
            retry=0.05,
        )
        with mock.patch.object(battery, "RapooDevice", factory):
            mon.start()
        return mon

    def _wait(self, pred, timeout=4.0):
        end = time.time() + timeout
        while not pred() and time.time() < end:
            time.sleep(0.02)
        return pred()

    def test_submit_runs_task_with_device_and_reports_result(self):
        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 80),
            clock=clock,
            read_delta=1.0,
        )
        mon = self._run_monitor([dev, dev])
        results, errors = [], []
        mon.submit(lambda d: d.path, on_done=results.append, on_error=errors.append)
        self.assertTrue(self._wait(lambda: results or errors))
        mon.stop()
        mon._thread.join(3)
        self.assertEqual(results, ["/dev/hidraw1"])
        self.assertEqual(errors, [])

    def test_task_exception_reports_error(self):
        clock = FakeClock()
        dev = FakeDev(
            "/dev/hidraw1",
            protocol.PREFIX_WIRELESS,
            battery=(protocol.BATTERY_STATUS_OK, 80),
            clock=clock,
            read_delta=1.0,
        )
        mon = self._run_monitor([dev, dev])
        results, errors = [], []

        def boom(d):
            raise ValueError("bad dpi")

        mon.submit(boom, on_done=results.append, on_error=errors.append)
        self.assertTrue(self._wait(lambda: results or errors))
        mon.stop()
        mon._thread.join(3)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertEqual(str(errors[0]), "bad dpi")

    def test_task_while_asleep_rejected_with_command_timeout(self):
        dev = FakeDev("/dev/hidraw1", protocol.PREFIX_WIRELESS, battery=(None, None))
        mon = self._run_monitor([dev, dev, dev])
        results, errors = [], []
        mon.submit(lambda d: "never", on_done=results.append, on_error=errors.append)
        self.assertTrue(self._wait(lambda: results or errors))
        mon.stop()
        mon._thread.join(3)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], CommandTimeout)

    def test_wake_task_is_attempted_while_asleep(self):
        # wake=True (explicit user action) leaves sleep mode and runs the
        # task; only a device timeout flips the monitor back to asleep.
        dev = FakeDev("/dev/hidraw1", protocol.PREFIX_WIRELESS, battery=(None, None))
        mon = self._run_monitor([dev, dev, dev])
        results, errors = [], []
        mon.submit(
            lambda d: "ran", on_done=results.append, on_error=errors.append, wake=True
        )
        self.assertTrue(self._wait(lambda: results or errors))
        mon.stop()
        mon._thread.join(3)
        self.assertEqual(results, ["ran"])
        self.assertEqual(errors, [])

    def test_report7_emits_on_report_with_dpi(self):
        # The physical DPI button mirrors itself via report 7: (gear, x, y).
        got = []
        mon = BatteryMonitor(on_report=lambda g, x, y: got.append((g, x, y)))
        report = bytearray(18)
        report[0] = protocol.REPORT_PASSIVE
        report[1] = 0x10
        report[2] = 2
        report[3] = 0x88
        report[4] = 0x13  # dpiX = 5000
        report[5] = 0x88
        report[6] = 0x13  # dpiY = 5000
        report[7] = 1
        report[8] = 80
        mon._handle_report(bytes(report))
        self.assertEqual(got, [(2, 5000, 5000)])


if __name__ == "__main__":
    unittest.main()

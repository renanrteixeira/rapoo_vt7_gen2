import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import probe
from src.rapoo_vt7 import i18n, main, parameters, protocol, system
from src.rapoo_vt7 import __version__ as APP_VERSION_STR
from src.rapoo_vt7.device import CommandTimeout
from src.rapoo_vt7.pairing_session import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
)

# --- fakes ---------------------------------------------------------------


def factory_state():
    return {
        protocol.EEPROM_BANK0_BASE + protocol.MOUSE_DPI_CUR: b"\x05",
        protocol.EEPROM_BANK0_BASE + protocol.RF_STRENGTHEN_SWITCH: b"\x00",
        protocol.EEPROM_BANK0_BASE + protocol.SENSOR_MODE: bytes(system.FACTORY_SENSOR_MODE),
    }


def user_state():
    return {
        protocol.EEPROM_BANK0_BASE + protocol.MOUSE_DPI_CUR: b"\x02",
        protocol.EEPROM_BANK0_BASE + protocol.RF_STRENGTHEN_SWITCH: b"\x03",
        protocol.EEPROM_BANK0_BASE + protocol.SENSOR_MODE: bytes([5, 5, 5, 5, 5, 5, 5]),
    }


def ack_reply():
    resp = bytearray(32)
    resp[0] = protocol.REPORT_CMD
    resp[1] = protocol.RESP_ACK
    return bytes(resp)


class FakeDev:
    """RapooDevice stand-in for the factory-reset flow.

    read_eeprom returns `data` for an address (or synthetic address bytes);
    send_command(RETURN_FACTORY_SETTINGS) swaps `data` for the factory state
    (the reset) and queues a plain ACK that read_response returns. The
    `before` reads happen before the send, the `after` reads see the factory
    state.
    """

    def __init__(self, data=None, factory=None):
        self.path = "/dev/hidraw2"
        self.data = dict(data or {})
        self.factory = dict(factory or {})
        self.sent = []
        self.writes = []
        self._pending = None

    def open(self):
        pass

    def close(self):
        pass

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

    def send_command(self, cmd_id, args=(), prefix=None):
        self.sent.append((cmd_id, bytes(args)))
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.data = dict(self.factory)
            self._pending = ack_reply()
            return
        raise AssertionError("unexpected send cmd 0x%02X" % cmd_id)

    def read_response(self, cmd_id=None, timeout=1.0, capture_report7=()):
        resp, self._pending = self._pending, None
        return resp

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        # Guard: the destructive 0xAD path must use send/read directly
        # (single execution), never query()'s replay-on-timeout loop.
        raise AssertionError("factory reset must not go through query()")

    def write_eeprom(self, addr, data):
        self.writes.append(((addr[1] << 8) | addr[0], bytes(data)))
        self.data[(addr[1] << 8) | addr[0]] = bytes(data)
        return ack_reply()

    def write_eeprom_verify(self, addr, data):
        self.write_eeprom(addr, data)
        readback = self.read_eeprom(addr, len(data))
        return readback[
            protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + len(data)
        ]


class ShortDev:
    def read_eeprom(self, addr, length=1):
        return b"\x00" * 4


class NoAckDev(FakeDev):
    """send_command(0xAD) queues a non-ACK (empty) reply."""

    def send_command(self, cmd_id, args=(), prefix=None):
        self.sent.append(cmd_id)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            resp = bytearray(32)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_EMPTY
            self._pending = bytes(resp)
            return
        raise AssertionError("unexpected send cmd 0x%02X" % cmd_id)


class TimeoutDev(FakeDev):
    """The mouse never answers: read_response times out (returns None)."""

    def read_response(self, cmd_id=None, timeout=1.0, capture_report7=()):
        return None


class RebootDev(FakeDev):
    """The first post-reset reads raise CommandTimeout (mouse rebooting), then
    the reads succeed and reflect the factory state."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.resets = 0
        self.fail_after_reset = 1

    def send_command(self, cmd_id, args=(), prefix=None):
        super().send_command(cmd_id, args, prefix)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.resets += 1

    def read_eeprom(self, addr, length=1):
        if self.resets and self.fail_after_reset:
            self.fail_after_reset -= 1
            raise CommandTimeout("rebooting")
        return super().read_eeprom(addr, length)


class BoomDev(FakeDev):
    """Every post-reset read fails (the mouse never answers again)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.resets = 0

    def send_command(self, cmd_id, args=(), prefix=None):
        super().send_command(cmd_id, args, prefix)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.resets += 1

    def read_eeprom(self, addr, length=1):
        if self.resets:
            raise CommandTimeout("rebooting")
        return super().read_eeprom(addr, length)


class FakeMonitor:
    def __init__(self):
        self.jobs = []
        self.quiet = False

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        self.jobs.append((fn, on_done, on_error, wake))

    def set_quiet(self, quiet):
        self.quiet = bool(quiet)


class _sync_idle:
    """Context manager: make GLib.idle_add invoke callbacks synchronously."""

    def __enter__(self):
        from src.rapoo_vt7 import main

        self._original = main.GLib.idle_add

        def sync(fn, *args, **kwargs):
            fn(*args, **kwargs)
            return None

        main.GLib.idle_add = sync
        return self

    def __exit__(self, *_exc):
        from src.rapoo_vt7 import main

        main.GLib.idle_add = self._original
        return False


class FakeWindow:
    def __init__(self):
        self._lang = "en"
        self.messages = []

    def set_system_message(self, message, is_error=False, op=None):
        self.messages.append((message, is_error, op))


class FakeNotification:
    def show(self):
        pass


class _FakePairingSession:
    """PairingSession stand-in for main.py wiring tests: records the callback
    kwargs and exposes `is_running`/`start`/`cancel`."""

    def __init__(self, **kwargs):
        self.on_step = kwargs.get("on_step")
        self.on_result = kwargs.get("on_result")
        self.started = False
        self.cancelled = False
        self.running = False

    @property
    def is_running(self):
        return self.running

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


# --- system module tests -------------------------------------------------


class FactoryDefaultsTest(unittest.TestCase):
    def test_factory_sensor_mode_is_the_validated_table(self):
        self.assertEqual(list(system.FACTORY_SENSOR_MODE), [0, 0, 1, 2, 3, 3, 3])
        self.assertEqual(len(system.FACTORY_SENSOR_MODE), 7)

    def test_is_factory_state_matches_defaults(self):
        state = {
            "dpi_cur": system.FACTORY_DPI_CUR,
            "rf_byte": system.FACTORY_RF_BYTE,
            "sensor_mode": list(system.FACTORY_SENSOR_MODE),
        }
        self.assertTrue(system._is_factory_state(state))

    def test_is_factory_state_rejects_each_field(self):
        base = {
            "dpi_cur": system.FACTORY_DPI_CUR,
            "rf_byte": system.FACTORY_RF_BYTE,
            "sensor_mode": list(system.FACTORY_SENSOR_MODE),
        }
        for field, bad in (("dpi_cur", 2), ("rf_byte", 3), ("sensor_mode", [1, 1, 1, 1, 1, 1, 1])):
            with self.subTest(field=field):
                state = dict(base)
                state[field] = bad
                self.assertFalse(system._is_factory_state(state))


class ReadVerifyStateTest(unittest.TestCase):
    def test_reads_three_markers(self):
        dev = FakeDev(
            data={
                0x0898: b"\x02",
                0x08D8: b"\x03",
                0x08DC: bytes([0, 0, 1, 1, 3, 3, 3]),
            }
        )
        state = system.read_verify_state(dev)
        self.assertEqual(
            state,
            {"dpi_cur": 2, "rf_byte": 3, "sensor_mode": [0, 0, 1, 1, 3, 3, 3]},
        )

    def test_short_reply_raises(self):
        with self.assertRaises(ValueError):
            system.read_verify_state(ShortDev())


class FactoryResetTest(unittest.TestCase):
    def test_sends_0xad_payload_ack_and_verifies_factory_defaults(self):
        dev = FakeDev(data=user_state(), factory=factory_state())
        result = system.factory_reset(dev)
        self.assertEqual(
            dev.sent,
            [(protocol.RETURN_FACTORY_SETTINGS, bytes(system.FACTORY_RESET_PAYLOAD))],
        )
        self.assertEqual(dev.writes, [])
        self.assertTrue(result["acked"])
        self.assertEqual(result["before"], system.read_verify_state(FakeDev(data=user_state())))
        self.assertEqual(
            result["after"],
            {"dpi_cur": 5, "rf_byte": 0, "sensor_mode": list(system.FACTORY_SENSOR_MODE)},
        )

    def test_no_replay_on_timeout_single_execution(self):
        # 0.AD is destructive: when the reply times out (mouse asleep) the
        # command must NOT be re-sent (query() would replay it on the other
        # interface). Exactly one send, then the localized timeout surfaces.
        dev = TimeoutDev(data=user_state(), factory=factory_state())
        with self.assertRaises(CommandTimeout):
            system.factory_reset(dev)
        self.assertEqual(len([s for s in dev.sent if s[0] == protocol.RETURN_FACTORY_SETTINGS]), 1)

    def test_non_ack_reply_raises_ack_error(self):
        dev = NoAckDev(data=user_state(), factory=factory_state())
        with self.assertRaises(system.FactoryResetAckError):
            system.factory_reset(dev)
        self.assertEqual(dev.writes, [])

    def test_no_change_detected_raises_verify_error(self):
        # The user config already equals the factory defaults: after the reset
        # the state is unchanged, so the change check fails (Ask First case —
        # surfaced as an error here, never silently accepted).
        dev = FakeDev(data=factory_state(), factory=factory_state())
        with self.assertRaises(system.FactoryResetVerifyError):
            system.factory_reset(dev)
        self.assertEqual(dev.writes, [])

    def test_post_reset_not_at_defaults_raises_verify_error(self):
        # The reset "happened" but the mouse did not return to the known
        # factory defaults (e.g. a third-party state): verification fails.
        partial = factory_state()
        partial[protocol.EEPROM_BANK0_BASE + protocol.SENSOR_MODE] = bytes([1, 1, 1, 1, 1, 1, 1])
        dev = FakeDev(data=user_state(), factory=partial)
        with self.assertRaises(system.FactoryResetVerifyError):
            system.factory_reset(dev)
        self.assertEqual(dev.writes, [])

    def test_asleep_timeout_propagates(self):
        dev = TimeoutDev(data=user_state(), factory=factory_state())
        with self.assertRaises(CommandTimeout):
            system.factory_reset(dev)

    def test_retries_reads_while_mouse_reboots(self):
        dev = RebootDev(data=user_state(), factory=factory_state())
        result = system.factory_reset(dev, attempts=3, delay=0)
        self.assertTrue(result["acked"])
        self.assertEqual(result["after"]["dpi_cur"], 5)

    def test_all_post_reset_reads_fail_raises_verify_error(self):
        # The reset was ACKed but the mouse never answered the post-reset
        # reads: the failure must surface as a verification error (localized),
        # not as a raw CommandTimeout ("no response / mouse asleep").
        dev = BoomDev(data=user_state(), factory=factory_state())
        with self.assertRaises(system.FactoryResetVerifyError):
            system.factory_reset(dev, attempts=2, delay=0)


# --- probe --factory-reset gate + main (D3) -------------------------------


class ProbeFactoryResetGateTest(unittest.TestCase):
    class NonTtyStdin:
        def isatty(self):
            return False

    class TtyStdin:
        def isatty(self):
            return True

    class Args:
        def __init__(self, risks=False):
            self.i_understand_risks = risks

    def test_refused_without_risks_flag(self):
        with self.assertRaises(ValueError) as ctx:
            probe.factory_reset_gate(self.Args(), stdin=self.NonTtyStdin())
        self.assertIn("--i-understand-risks", str(ctx.exception))

    def test_non_tty_auto_refuses_even_with_risks_flag(self):
        with self.assertRaises(ValueError) as ctx:
            probe.factory_reset_gate(
                self.Args(risks=True), stdin=self.NonTtyStdin()
            )
        self.assertIn("TTY", str(ctx.exception))

    def test_tty_wrong_answer_refuses(self):
        with self.assertRaises(ValueError) as ctx:
            probe.factory_reset_gate(
                self.Args(risks=True),
                stdin=self.TtyStdin(),
                prompt=lambda m: "no",
            )
        self.assertIn("confirmation", str(ctx.exception))

    def test_tty_eof_refuses_cleanly(self):
        def eof(m):
            raise EOFError()

        with self.assertRaises(ValueError) as ctx:
            probe.factory_reset_gate(
                self.Args(risks=True), stdin=self.TtyStdin(), prompt=eof
            )
        self.assertIn("EOF", str(ctx.exception))

    def test_tty_confirmation_allows(self):
        self.assertTrue(
            probe.factory_reset_gate(
                self.Args(risks=True),
                stdin=self.TtyStdin(),
                prompt=lambda m: "yes",
            )
        )


class ProbeFactoryResetMainTest(unittest.TestCase):
    def test_happy_path_prints_ack_and_state(self):
        dev = FakeDev(data=user_state(), factory=factory_state())
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.factory_reset_main(attempts=3)
        self.assertEqual(rc, 0)
        self.assertIn("ACKED", out.getvalue())
        self.assertIn("AFTER", out.getvalue())
        self.assertEqual(
            dev.sent,
            [(protocol.RETURN_FACTORY_SETTINGS, bytes(system.FACTORY_RESET_PAYLOAD))],
        )

    def test_ack_error_prints_error_and_exits_nonzero(self):
        dev = NoAckDev(data=user_state(), factory=factory_state())
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.factory_reset_main(attempts=3)
        self.assertEqual(rc, 1)
        self.assertIn("factory reset failed", err.getvalue())

    def test_command_timeout_prints_asleep_and_exits_nonzero(self):
        dev = TimeoutDev(data=user_state(), factory=factory_state())
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.factory_reset_main(attempts=3)
        self.assertEqual(rc, 1)
        self.assertIn("no response", err.getvalue())

    def test_open_error_prints_probe_error_and_exits_nonzero(self):
        def raise_notfound():
            raise Exception("not found")

        with mock.patch.object(probe, "RapooDevice") as mdev, \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            mdev.return_value.open.side_effect = raise_notfound
            rc = probe.factory_reset_main()
        self.assertEqual(rc, 1)
        self.assertIn("not found", out.getvalue())

    def test_main_dispatch_non_tty_auto_refuses(self):
        with mock.patch.object(probe, "RapooDevice") as mdev, \
                mock.patch.object(
                    sys,
                    "stdin",
                    ProbeFactoryResetGateTest.NonTtyStdin(),
                ), mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--factory-reset", "--i-understand-risks"],
                ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("REFUSED", err.getvalue())
        mdev.assert_not_called()

    def test_main_dispatch_confirmed_runs(self):
        dev = FakeDev(data=user_state(), factory=factory_state())
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(
                    sys,
                    "stdin",
                    ProbeFactoryResetGateTest.TtyStdin(),
                ), mock.patch.object(
                    probe, "_confirm_prompt", return_value="yes"
                ), mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--factory-reset", "--i-understand-risks"],
                ), mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertIn("ACKED", out.getvalue())

    def test_main_dispatch_requires_factory_reset(self):
        with mock.patch.object(
            sys, "argv", ["probe", "--i-understand-risks"]
        ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("only apply with", err.getvalue())


# --- device-name module tests --------------------------------------------


class DeviceNameEncodeTest(unittest.TestCase):
    def test_pads_to_exactly_16_bytes(self):
        self.assertEqual(system.encode_name("CFG1"), b"CFG1" + b"\x00" * 12)

    def test_trimmed_leading_and_trailing_spaces(self):
        self.assertEqual(
            system.encode_name("  My Mouse  "), b"My Mouse" + b"\x00" * 8
        )

    def test_multibyte_char_counts_as_two_bytes(self):
        # "é" is 2 bytes in UTF-8: 8 of them fill the 16-byte field exactly.
        self.assertEqual(len(system.encode_name("\u00e9" * 8)), 16)

    def test_refuses_more_than_16_bytes(self):
        with self.assertRaises(system.NameTooLongError):
            system.encode_name("X" * 17)
        # 9 multibyte chars = 18 bytes > 16.
        with self.assertRaises(system.NameTooLongError):
            system.encode_name("\u00e9" * 9)

    def test_refuses_empty_and_whitespace_only(self):
        for blank in ("", "   ", "\t\n"):
            with self.subTest(blank=repr(blank)):
                with self.assertRaises(system.NameEmptyError):
                    system.encode_name(blank)

    def test_refuses_embedded_nul_byte(self):
        # An embedded NUL would silently truncate the name on readback, so it
        # is rejected before any device write.
        with self.assertRaises(system.DeviceNameError):
            system.encode_name("CF\x00G1")

    def test_error_types_share_the_device_name_base(self):
        self.assertTrue(issubclass(system.NameEmptyError, system.DeviceNameError))
        self.assertTrue(issubclass(system.NameTooLongError, system.DeviceNameError))
        self.assertTrue(issubclass(system.NameVerifyError, system.DeviceNameError))

    def test_device_name_error_does_not_shadow_the_builtin(self):
        # The base is named DeviceNameError so the module never shadows the
        # Python builtin NameError.
        self.assertIs(system.DeviceNameError, system.DeviceNameError)
        self.assertIsNot(system.DeviceNameError, NameError)
        self.assertTrue(issubclass(system.DeviceNameError, ValueError))


class DeviceNameReadTest(unittest.TestCase):
    def test_read_nul_strips_and_decodes(self):
        dev = FakeDev(data={0x09EC: b"CFG1" + b"\x00" * 12})
        self.assertEqual(system.read_device_name(dev), "CFG1")

    def test_read_no_nul_returns_full_text(self):
        dev = FakeDev(data={0x09EC: b"ABCDEFGHIJKLMNOP"})
        self.assertEqual(system.read_device_name(dev), "ABCDEFGHIJKLMNOP")

    def test_read_decodes_utf8_with_replace(self):
        dev = FakeDev(data={0x09EC: b"\xff\xfeCFG" + b"\x00" * 11})
        self.assertEqual(system.read_device_name(dev), "\ufffd\ufffdCFG")

    def test_read_short_reply_raises(self):
        with self.assertRaises(ValueError):
            system.read_device_name(ShortDev())


class DeviceNameWriteTest(unittest.TestCase):
    def test_write_encodes_pads_and_verifies(self):
        dev = FakeDev()
        result = system.write_device_name(dev, "CFG1")
        self.assertEqual(dev.writes, [(0x09EC, b"CFG1" + b"\x00" * 12)])
        self.assertEqual(result, "CFG1")

    def test_write_roundtrip_shows_trimmed_decoded_readback(self):
        dev = FakeDev()
        result = system.write_device_name(dev, "  My Mouse  ")
        self.assertEqual(result, "My Mouse")
        self.assertEqual(dev.writes, [(0x09EC, b"My Mouse" + b"\x00" * 8)])

    def test_validation_refuses_before_any_write(self):
        dev = FakeDev()
        with self.assertRaises(system.NameTooLongError):
            system.write_device_name(dev, "X" * 17)
        with self.assertRaises(system.NameEmptyError):
            system.write_device_name(dev, "   ")
        self.assertEqual(dev.writes, [])

    def test_verify_mismatch_raises_verify_error(self):
        class CorruptDev(FakeDev):
            def write_eeprom_verify(self, addr, data):
                self.write_eeprom(addr, data)
                # Mirrors device.py: the readback is compared and a mismatch
                # raises ValueError, which write_device_name maps to
                # NameVerifyError.
                raise ValueError("write_eeprom_verify: data mismatch")

        dev = CorruptDev()
        with self.assertRaises(system.NameVerifyError):
            system.write_device_name(dev, "CFG1")


# --- app (main.py) tests -------------------------------------------------


class MainFactoryResetTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = FakeWindow()
        return app

    def test_on_factory_reset_submits_with_wake(self):
        app = self._app()
        app._on_factory_reset()
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        self.assertTrue(callable(on_error))
        result = fn(FakeDev(data=user_state(), factory=factory_state()))
        self.assertTrue(result["acked"])

    def test_ack_error_is_localized(self):
        app = self._app()
        with _sync_idle():
            app._factory_reset_error(system.FactoryResetAckError("ack"))
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["factory_reset_ack_error"], True, "system"),
        )

    def test_verify_error_is_localized(self):
        app = self._app()
        with _sync_idle():
            app._factory_reset_error(system.FactoryResetVerifyError("verify"))
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["factory_reset_verify_error"], True, "system"),
        )

    def test_timeout_surfaces_raw_message(self):
        app = self._app()
        with _sync_idle():
            app._factory_reset_error(CommandTimeout("no response"))
        self.assertEqual(app._window.messages[-1], ("no response", True, "system"))

    def test_done_refreshes_every_tab_and_notifies(self):
        app = self._app()
        refreshed = []

        def refresh():
            refreshed.append(1)

        app._refresh_dpi = refresh
        app._refresh_perf = refresh
        app._refresh_params = refresh
        app._refresh_buttons = refresh
        shown = []
        originals = {}
        originals["new"] = main.Notify.Notification.new
        originals["idle_add"] = main.GLib.idle_add

        def fake_new(_app, body, _icon):
            shown.append(body)
            return FakeNotification()

        def fake_idle(fn):
            fn()
            return None

        main.Notify.Notification.new = fake_new
        main.GLib.idle_add = fake_idle
        try:
            app._factory_reset_done({"acked": True})
        finally:
            main.Notify.Notification.new = originals["new"]
            main.GLib.idle_add = originals["idle_add"]
        self.assertEqual(len(refreshed), 4)
        # The real _refresh_name ran: it submitted a passive name read, so the
        # reset also re-reads the (restored-to-factory) device name.
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, _on_done, _on_error, wake = app._monitor.jobs[0]
        self.assertIs(fn, system.read_device_name)
        self.assertFalse(wake)
        self.assertEqual(len(shown), 1)
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["factory_reset_success"], False, "system"),
        )


class FactoryResetI18nTest(unittest.TestCase):
    def test_reset_keys_present_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            for key in (
                "tab_system",
                "factory_reset_button",
                "factory_reset_hint",
                "factory_reset_cancel",
                "factory_reset_ok",
                "factory_reset_dialog_title",
                "factory_reset_dialog_message",
                "factory_reset_success",
                "factory_reset_ack_error",
                "factory_reset_verify_error",
            ):
                self.assertIn(key, lang, "locale %s missing key %r" % (code, key))


class _FakeDialog:
    """Gtk.MessageDialog stand-in: records construction and yields a canned
    `run()` response, so the confirmation flow is testable headlessly."""

    result = None
    created = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.secondary = None
        self.buttons = []
        self.default = None
        self.destroyed = False
        self.__class__.created.append(self)

    def format_secondary_text(self, text):
        self.secondary = text

    def add_button(self, label, response):
        self.buttons.append((label, response))

    def set_default_response(self, response):
        self.default = response

    def run(self):
        return self.__class__.result

    def destroy(self):
        self.destroyed = True


class FactoryResetDialogTest(unittest.TestCase):
    """Headless coverage of the confirmation dialog in gui.py: dialog content
    (title/message/buttons), Cancel closes without sending, OK triggers the
    reset callback."""

    def _window_and_dialog(self, result):
        from src.rapoo_vt7 import gui

        calls = []
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._win = object()
        window._system_button = _StubButton()
        window._on_factory_reset = lambda: calls.append("reset")
        _FakeDialog.result = result
        _FakeDialog.created[:] = []
        original = gui.Gtk.MessageDialog
        gui.Gtk.MessageDialog = _FakeDialog
        self.addCleanup(setattr, gui.Gtk, "MessageDialog", original)
        return window, calls

    def test_dialog_has_localized_wipe_warning_and_cancel_ok(self):
        from src.rapoo_vt7 import gui

        window, _calls = self._window_and_dialog(gui.Gtk.ResponseType.CANCEL)
        window._on_factory_reset_clicked(None)
        dialog = _FakeDialog.created[0]
        self.assertEqual(dialog.kwargs["text"], i18n.LANGS["en"]["factory_reset_dialog_title"])
        self.assertEqual(dialog.secondary, i18n.LANGS["en"]["factory_reset_dialog_message"])
        self.assertIn("wipe", dialog.secondary.lower())
        self.assertIn(
            (i18n.LANGS["en"]["factory_reset_cancel"], gui.Gtk.ResponseType.CANCEL),
            dialog.buttons,
        )
        self.assertIn(
            (i18n.LANGS["en"]["factory_reset_ok"], gui.Gtk.ResponseType.OK),
            dialog.buttons,
        )
        self.assertEqual(dialog.default, gui.Gtk.ResponseType.CANCEL)
        self.assertTrue(dialog.destroyed)

    def test_cancel_closes_without_sending_reset(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.CANCEL)
        window._on_factory_reset_clicked(None)
        self.assertEqual(calls, [])
        self.assertTrue(_FakeDialog.created[0].destroyed)

    def test_ok_triggers_reset_callback(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._on_factory_reset_clicked(None)
        self.assertEqual(calls, ["reset"])

    def test_ok_marks_busy_and_disables_button(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._on_factory_reset_clicked(None)
        self.assertEqual(calls, ["reset"])
        self.assertTrue(window._system_busy)
        self.assertFalse(window._system_button.sensitive)

    def test_busy_ignores_second_click(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._on_factory_reset_clicked(None)
        self.assertEqual(calls, ["reset"])
        # A second OK while the reset is still in flight must not queue another.
        window._on_factory_reset_clicked(None)
        self.assertEqual(calls, ["reset"])

    def test_system_message_clears_busy_and_re_enables_button(self):
        from src.rapoo_vt7 import gui

        window, _calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._system_status = _StubLabel()
        window._on_factory_reset_clicked(None)
        self.assertTrue(window._system_busy)
        self.assertFalse(window._system_button.sensitive)
        window.set_system_message("done", False, op="system")
        self.assertFalse(window._system_busy)
        self.assertTrue(window._system_button.sensitive)

    def test_retranslate_reads_current_language(self):
        # The dialog reads its labels at show time via _t, so the same handler
        # yields the localized strings of whatever language is active.
        window, _calls = self._window_and_dialog(42)
        window._lang = "pt_BR"
        window._on_factory_reset_clicked(None)
        dialog = _FakeDialog.created[0]
        self.assertEqual(dialog.kwargs["text"], i18n.LANGS["pt_BR"]["factory_reset_dialog_title"])
        self.assertEqual(dialog.secondary, i18n.LANGS["pt_BR"]["factory_reset_dialog_message"])


class _StubWidget:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.halign = None
        self.sensitive = True
        self._text = None

    def set_halign(self, halign):
        self.halign = halign

    def set_line_wrap(self, _wrap):
        pass

    def set_margin_top(self, _m):
        pass

    def connect(self, _signal, _handler):
        pass

    def set_active(self, _active):
        pass

    def set_label(self, label):
        self.label = label

    def set_markup(self, markup):
        self.markup = markup

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive

    def set_title(self, _title):
        pass

    def set_tooltip_text(self, _text):
        pass

    def set_text(self, text):
        self._text = text


class _StubButton(_StubWidget):
    pass


class _StubLabel(_StubWidget):
    pass


class _StubEntry(_StubWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.text = ""
        self.placeholder = None
        self.focused = False
        self.set_text_calls = []

    def set_placeholder_text(self, text):
        self.placeholder = text

    def set_width_chars(self, _n):
        pass

    def has_focus(self):
        return self.focused

    def set_text(self, text):
        self.text = text
        self.set_text_calls.append(text)

    def get_text(self):
        return self.text


class _StubVBox:
    def __init__(self):
        self.children = []

    def pack_start(self, child, *args):
        self.children.append(child)


class _StubBox(_StubWidget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.children = []

    def pack_start(self, child, *args):
        self.children.append(child)


class _StubContainer:
    """Grid/box stand-in: children list + show_all for headless re-renders."""

    def __init__(self):
        self.children = []

    def get_children(self):
        return self.children

    def remove(self, child):
        if child in self.children:
            self.children.remove(child)

    def show_all(self):
        pass


class _StubCombo:
    def __init__(self, code):
        self.code = code

    def get_active_id(self):
        return self.code


class _StubScale:
    def __init__(self):
        self.value = 0.0
        self.sensitive = True

    def get_value(self):
        return self.value

    def set_value(self, value):
        self.value = value

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive


class FactoryResetTabTest(unittest.TestCase):
    """Headless coverage of the System tab construction: the device-name row
    (entry + rename button) and the factory reset button labeled with the
    localized strings, plus the hint (matrix rows 1-2)."""

    def _build(self):
        from src.rapoo_vt7 import gui

        original_button = gui.Gtk.Button
        original_label = gui.Gtk.Label
        original_entry = gui.Gtk.Entry
        original_box = gui.Gtk.Box
        gui.Gtk.Button = _StubButton
        gui.Gtk.Label = _StubLabel
        gui.Gtk.Entry = _StubEntry
        gui.Gtk.Box = _StubBox
        self.addCleanup(setattr, gui.Gtk, "Button", original_button)
        self.addCleanup(setattr, gui.Gtk, "Label", original_label)
        self.addCleanup(setattr, gui.Gtk, "Entry", original_entry)
        self.addCleanup(setattr, gui.Gtk, "Box", original_box)

        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        vbox = _StubVBox()
        window._build_system_section(vbox)
        return vbox

    def test_system_tab_builds_localized_reset_button_and_hint(self):
        vbox = self._build()
        labels = [
            w for w in vbox.children if isinstance(w, _StubLabel) and "label" in w.kwargs
        ]
        self.assertIn(
            i18n.LANGS["en"]["factory_reset_hint"],
            [w.kwargs["label"] for w in labels],
        )
        buttons = [w for w in vbox.children if isinstance(w, _StubButton)]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(
            buttons[0].kwargs["label"], i18n.LANGS["en"]["rename_button"]
        )
        self.assertEqual(
            buttons[1].kwargs["label"], i18n.LANGS["en"]["factory_reset_button"]
        )

    def test_system_tab_builds_localized_name_row(self):
        vbox = self._build()
        entries = [w for w in vbox.children if isinstance(w, _StubEntry)]
        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].placeholder, i18n.LANGS["en"]["device_name_placeholder"]
        )
        buttons = [w for w in vbox.children if isinstance(w, _StubButton)]
        self.assertEqual(
            buttons[0].kwargs["label"], i18n.LANGS["en"]["rename_button"]
        )
        titles = [
            w
            for w in vbox.children
            if isinstance(w, _StubLabel) and getattr(w, "markup", None)
        ]
        self.assertTrue(
            any(
                i18n.LANGS["en"]["device_name_section"] in t.markup
                for t in titles
            )
        )


class SystemNameRowTest(unittest.TestCase):
    """Headless coverage of the System-tab name row behaviour: rename click
    hands the entry text to the callback with a busy guard, the shared status
    message clears the busy state, and opening the System tab re-reads."""

    def _window(self, on_rename=None, on_read_name=None, on_read_versions=None):
        from src.rapoo_vt7 import gui

        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._on_rename = on_rename
        window._on_read_name = on_read_name
        window._on_read_versions = on_read_versions
        window._name_entry = _StubEntry()
        window._name_button = _StubButton()
        window._system_button = _StubButton()
        window._versions_title = _StubLabel()
        window._fw_mouse_label = _StubLabel()
        window._fw_receiver_label = _StubLabel()
        window._sw_label = _StubLabel()
        window._fw_mouse = None
        window._fw_receiver = None
        window._system_status = _StubLabel()
        window._system_busy = False
        window._name_busy = False
        return window

    def test_rename_click_passes_entry_text_and_busy_guard(self):
        calls = []
        window = self._window(on_rename=lambda text: calls.append(text))
        window._name_entry.text = "CFG1"
        window._on_rename_clicked(None)
        self.assertEqual(calls, ["CFG1"])
        self.assertTrue(window._name_busy)
        self.assertFalse(window._name_button.sensitive)

    def test_rename_second_click_ignored_while_busy(self):
        calls = []
        window = self._window(on_rename=lambda text: calls.append(text))
        window._on_rename_clicked(None)
        window._on_rename_clicked(None)
        self.assertEqual(len(calls), 1)

    def test_no_callback_is_noop(self):
        window = self._window(on_rename=None)
        window._on_rename_clicked(None)
        self.assertFalse(window._name_busy)

    def test_system_message_clears_rename_busy_and_re_enables(self):
        window = self._window(on_rename=lambda text: None)
        window._on_rename_clicked(None)
        self.assertTrue(window._name_busy)
        self.assertFalse(window._name_button.sensitive)
        window.set_system_message("done", False, op="name")
        self.assertFalse(window._name_busy)
        self.assertTrue(window._name_button.sensitive)

    def test_update_device_name_sets_entry_text(self):
        window = self._window()
        window.update_device_name("CFG1")
        self.assertEqual(window._name_entry.text, "CFG1")
        window.update_device_name(None)
        self.assertEqual(window._name_entry.text, "")

    def test_tab_switch_reads_name_only_on_system_page(self):
        calls = []
        window = self._window(
            on_read_name=lambda: calls.append("read"),
            on_read_versions=lambda: calls.append("versions"),
        )
        window._system_page = object()
        page = object()
        window._on_tab_switch(None, page, 5)
        self.assertEqual(calls, [])
        window._on_tab_switch(None, window._system_page, 6)
        self.assertEqual(calls, ["read", "versions"])

    def test_tab_switch_skips_read_while_rename_in_flight(self):
        calls = []
        window = self._window(
            on_read_name=lambda: calls.append("read"),
            on_read_versions=lambda: calls.append("versions"),
        )
        window._system_page = object()
        window._name_busy = True
        window._on_tab_switch(None, window._system_page, 6)
        # The rename busy guard only skips the NAME read; the passive
        # versions refresh still runs (independent informational section).
        self.assertEqual(calls, ["versions"])

    def test_update_versions_renders_rows_and_fallback(self):
        window = self._window()
        window.update_versions("v0.145", "V1.45-V1.45")
        self.assertIn("v0.145", window._fw_mouse_label._text)
        self.assertIn("V1.45-V1.45", window._fw_receiver_label._text)
        self.assertIn(APP_VERSION_STR, window._sw_label._text)
        window.update_versions(None, None)
        self.assertIn("--", window._fw_mouse_label._text)
        self.assertIn("--", window._fw_receiver_label._text)

    def test_update_device_name_skips_set_text_while_focused(self):
        window = self._window()
        window._name_entry.focused = True
        window._name_entry.text = "typing..."
        window.update_device_name("CFG1")
        self.assertEqual(window._name_entry.text, "typing...")
        self.assertEqual(window._name_entry.set_text_calls, [])
        window._name_entry.focused = False
        window.update_device_name("CFG1")
        self.assertEqual(window._name_entry.text, "CFG1")
        self.assertEqual(window._name_entry.set_text_calls, ["CFG1"])

    def test_rename_callback_exception_releases_the_busy_guard(self):
        def boom(_text):
            raise UnicodeEncodeError("utf-8", "x", 0, 1, "lone surrogate")

        window = self._window(on_rename=boom)
        with self.assertRaises(UnicodeEncodeError):
            window._on_rename_clicked(None)
        self.assertFalse(window._name_busy)
        self.assertTrue(window._name_button.sensitive)

    def test_system_op_does_not_clear_name_busy(self):
        window = self._window(on_rename=lambda text: None)
        window._on_rename_clicked(None)
        self.assertTrue(window._name_busy)
        window.set_system_message("reset done", False, op="system")
        self.assertTrue(window._name_busy)
        self.assertFalse(window._name_button.sensitive)

    def test_name_op_does_not_clear_system_busy(self):
        window = self._window(on_rename=lambda text: None)
        window._system_busy = True
        window._system_button.set_sensitive(False)
        window.set_system_message("renamed", False, op="name")
        self.assertTrue(window._system_busy)
        self.assertFalse(window._system_button.sensitive)

    def test_passive_error_does_not_clear_name_busy(self):
        window = self._window(on_rename=lambda text: None)
        window._on_rename_clicked(None)
        self.assertTrue(window._name_busy)
        window.set_system_message("read failed", True)
        self.assertTrue(window._name_busy)
        self.assertFalse(window._name_button.sensitive)
        self.assertTrue(window._system_status.markup is not None)

    def test_passive_error_does_not_clear_system_busy(self):
        window = self._window(on_rename=lambda text: None)
        window._system_busy = True
        window._system_button.set_sensitive(False)
        window.set_system_message("read failed", True, None)
        self.assertTrue(window._system_busy)
        self.assertFalse(window._system_button.sensitive)


class NameRowRetranslateTest(unittest.TestCase):
    """Headless coverage of `_on_lang_changed` re-translating the device-name
    row (title/placeholder/button) when the language is switched."""

    def _window(self):
        from src.rapoo_vt7 import gui

        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "pt_BR"
        window._win = _StubWidget()
        window._lang_label = _StubLabel()
        window._tab_battery = _StubLabel()
        window._tab_dpi = _StubLabel()
        window._tab_perf = _StubLabel()
        window._tab_params = _StubLabel()
        window._tab_buttons = _StubLabel()
        window._tab_system = _StubLabel()
        window._dpi_title = _StubLabel()
        window._dpi_add_btn = _StubButton()
        window._perf_title = _StubLabel()
        window._rf_title = _StubLabel()
        window._rate_title = _StubLabel()
        window._rate_radio = []
        window._perf_radio = []
        window._rf_radio = [_StubButton(), _StubButton()]
        window._rf_lowpow = _StubButton()
        window._param_title = _StubLabel()
        window._buttons_title = _StubLabel()
        window._system_button = _StubButton()
        window._system_hint = _StubLabel()
        window._name_title = _StubLabel()
        window._name_entry = _StubEntry()
        window._name_button = _StubButton()
        window._versions_title = _StubLabel()
        window._fw_mouse_label = _StubLabel()
        window._fw_receiver_label = _StubLabel()
        window._sw_label = _StubLabel()
        window._fw_mouse = None
        window._fw_receiver = None
        window._pair_title = _StubLabel()
        window._pair_hint = _StubLabel()
        window._pair_button = _StubButton()
        window._pair_cancel = _StubButton()
        window._pair_steps = [_StubLabel() for _ in range(3)]
        window._pair_status = _StubLabel()
        window._pair_last_status = None
        window._pair_last_message = None
        window._pair_current_step = 0
        window._pair_busy = False
        window._param_check = {}
        window._param_state = {}
        window._param_readonly = set()
        for _name, _offset, editable in parameters.PARAMS:
            if editable:
                window._param_check[_name] = _StubButton()
            elif parameters.is_selectable(_name):
                window._param_state[_name] = (_StubLabel(), _StubScale())
            else:
                window._param_state[_name] = (_StubLabel(), _StubLabel())
                window._param_readonly.add(_name)
        window._on_lang_change = None
        window._known = False
        window._status_label = _StubLabel()
        window._detail_label = _StubLabel()
        window._dpi = None
        window._dpi_error = None
        window._dpi_status = _StubLabel()
        window._dpi_grid = _StubContainer()
        window._buttons = None
        window._buttons_error = None
        window._buttons_status = _StubLabel()
        window._buttons_grid = _StubContainer()
        window._button_combos = {}
        window._perf = None
        window._perf_error = None
        window._perf_status = _StubLabel()
        window._rf_status = _StubLabel()
        window._params = None
        window._params_error = None
        window._param_status = _StubLabel()
        window._perf_box = _StubContainer()
        window._param_box = _StubContainer()
        return window

    def test_retranslate_updates_the_name_row_to_english(self):
        window = self._window()
        window._on_lang_changed(_StubCombo("en"))
        self.assertEqual(window._lang, "en")
        self.assertIn(
            i18n.LANGS["en"]["device_name_section"], window._name_title.markup
        )
        self.assertEqual(
            window._name_entry.placeholder,
            i18n.LANGS["en"]["device_name_placeholder"],
        )
        self.assertEqual(
            window._name_button.label, i18n.LANGS["en"]["rename_button"]
        )

    def test_versions_rows_retranslate_with_stored_values(self):
        window = self._window()
        window.update_versions("v0.145", None)
        window._on_lang_changed(_StubCombo("en"))
        self.assertIn(
            i18n.LANGS["en"]["versions_section"], window._versions_title.markup
        )
        self.assertIn("v0.145", window._fw_mouse_label._text)
        self.assertIn(i18n.LANGS["en"]["fw_mouse"], window._fw_mouse_label._text)
        self.assertIn(
            i18n.LANGS["en"]["fw_receiver"], window._fw_receiver_label._text
        )
        self.assertIn("--", window._fw_receiver_label._text)

    def test_retranslate_updates_the_pairing_block_to_english(self):
        window = self._window()
        window._on_lang_changed(_StubCombo("en"))
        self.assertIn(
            i18n.LANGS["en"]["pairing_section"], window._pair_title.markup
        )
        self.assertEqual(
            window._pair_hint.label, i18n.LANGS["en"]["pairing_hint"]
        )
        self.assertEqual(
            window._pair_button.label, i18n.LANGS["en"]["pairing_start"]
        )
        self.assertEqual(
            window._pair_cancel.label, i18n.LANGS["en"]["pairing_stop"]
        )
        for i, step in enumerate(window._pair_steps):
            self.assertEqual(
                step._text,
                i18n.LANGS["en"]["pairing_step%d" % (i + 1)],
            )
        self.assertEqual(
            window._pair_status._text,
            i18n.LANGS["en"]["pairing_matching"],
        )

    def test_retranslate_terminal_status_renders_stored_message(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window._pair_last_status = gui.STATUS_ERROR
        window._pair_last_message = i18n.LANGS["pt_BR"][
            "pairing_receiver_not_found"
        ]
        window._pair_current_step = 0
        window._on_lang_changed(_StubCombo("en"))
        # The stored (already-localized) message wins over the raw STATUS_ERROR
        # placeholder, and an early error highlights step 1, not the L+M+R one.
        self.assertIn("red", window._pair_status.markup)
        self.assertIn(
            i18n.LANGS["pt_BR"]["pairing_receiver_not_found"],
            window._pair_status.markup,
        )
        self.assertNotIn(
            i18n.LANGS["en"]["pairing_error"], window._pair_status.markup
        )
        self.assertEqual(
            window._pair_steps[0].markup,
            "<b>%s</b>" % i18n.LANGS["en"]["pairing_step1"],
        )

    def test_retranslate_rehighlights_current_step_while_busy(self):
        window = self._window()
        window._pair_busy = True
        window._pair_current_step = 1
        window._on_lang_changed(_StubCombo("en"))
        self.assertEqual(
            window._pair_steps[1].markup,
            "<b>%s</b>" % i18n.LANGS["en"]["pairing_step2"],
        )
        self.assertEqual(
            window._pair_status._text,
            i18n.LANGS["en"]["pairing_matching"],
        )


class MainRenameTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = FakeWindow()
        return app

    def test_on_rename_submits_with_wake_and_writes_verified(self):
        app = self._app()
        app._on_rename("CFG1")
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        self.assertTrue(callable(on_error))
        dev = FakeDev()
        result = fn(dev)
        self.assertEqual(result, "CFG1")
        self.assertEqual(dev.writes, [(0x09EC, b"CFG1" + b"\x00" * 12)])

    def test_on_rename_refuses_invalid_without_submitting(self):
        app = self._app()
        with _sync_idle():
            app._on_rename("   ")
        with _sync_idle():
            app._on_rename("X" * 17)
        self.assertEqual(len(app._monitor.jobs), 0)
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["name_too_long"], True, "name"),
        )

    def test_empty_error_is_localized(self):
        app = self._app()
        with _sync_idle():
            app._rename_error(system.NameEmptyError("empty"))
        self.assertEqual(
            app._window.messages[-1], (i18n.LANGS["en"]["name_empty"], True, "name")
        )

    def test_too_long_error_is_localized(self):
        app = self._app()
        with _sync_idle():
            app._rename_error(system.NameTooLongError("long"))
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["name_too_long"], True, "name"),
        )

    def test_verify_error_is_localized_and_refreshes_the_name(self):
        app = self._app()
        with _sync_idle():
            app._rename_error(system.NameVerifyError("verify"))
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["name_verify_error"], True, "name"),
        )
        # The unverified typed text is replaced by a re-read of what the mouse
        # actually stored.
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, _on_done, _on_error, wake = app._monitor.jobs[0]
        self.assertIs(fn, system.read_device_name)
        self.assertFalse(wake)

    def test_timeout_surfaces_raw_message(self):
        app = self._app()
        with _sync_idle():
            app._rename_error(CommandTimeout("no response"))
        self.assertEqual(app._window.messages[-1], ("no response", True, "name"))

    def test_done_shows_readback_and_success_status(self):
        app = self._app()
        updated = []
        app._window.update_device_name = lambda name: updated.append(name)
        with _sync_idle():
            app._rename_done("CFG1")
        self.assertEqual(updated, ["CFG1"])
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["name_success"].format(name="CFG1"), False, "name"),
        )

    def test_refresh_name_submits_passive_read(self):
        app = self._app()
        app._refresh_name()
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertFalse(wake)  # background read must not wake the mouse
        dev = FakeDev(data={0x09EC: b"CFG1" + b"\x00" * 12})
        self.assertEqual(fn(dev), "CFG1")

    def test_refresh_name_read_error_is_localized_with_no_op(self):
        app = self._app()
        app._refresh_name()
        _fn, _on_done, on_error, _wake = app._monitor.jobs[0]
        with _sync_idle():
            on_error(CommandTimeout("no response"))
        self.assertEqual(
            app._window.messages[-1],
            (
                i18n.LANGS["en"]["name_read_error"].format(error="no response"),
                True,
                None,
            ),
        )


class DeviceNameI18nTest(unittest.TestCase):
    def test_name_keys_present_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            for key in (
                "device_name_section",
                "device_name_placeholder",
                "rename_button",
                "name_read_error",
                "name_empty",
                "name_too_long",
                "name_success",
                "name_verify_error",
            ):
                self.assertIn(
                    key, lang, "locale %s missing key %r" % (code, key)
                )

    def test_name_format_strings_render_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            with self.subTest(locale=code):
                lang["name_read_error"].format(error="timeout")
                lang["name_success"].format(name="CFG1")


class PairingDialogTest(unittest.TestCase):
    """Headless coverage of the pairing confirmation dialog in gui.py: dialog
    content (title/message/buttons), Cancel closes without starting a session,
    OK triggers the session callback and arms the busy guard."""

    def _window_and_dialog(self, result):
        from src.rapoo_vt7 import gui

        calls = []
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._win = object()
        window._pair_busy = False
        window._pair_last_status = None
        window._pair_last_message = None
        window._pair_current_step = 0
        window._pair_button = _StubButton()
        window._pair_cancel = _StubButton()
        window._pair_steps = [_StubLabel() for _ in range(3)]
        window._pair_status = _StubLabel()
        window._on_start_pairing = lambda: calls.append("pair")
        window._on_cancel_pairing = lambda: calls.append("cancel")
        _FakeDialog.result = result
        _FakeDialog.created[:] = []
        original = gui.Gtk.MessageDialog
        gui.Gtk.MessageDialog = _FakeDialog
        self.addCleanup(setattr, gui.Gtk, "MessageDialog", original)
        return window, calls

    def test_dialog_has_localized_warning_and_cancel_ok(self):
        from src.rapoo_vt7 import gui

        window, _calls = self._window_and_dialog(gui.Gtk.ResponseType.CANCEL)
        window._on_pairing_clicked(None)
        dialog = _FakeDialog.created[0]
        self.assertEqual(
            dialog.kwargs["text"], i18n.LANGS["en"]["pairing_dialog_title"]
        )
        self.assertEqual(
            dialog.secondary, i18n.LANGS["en"]["pairing_dialog_message"]
        )
        self.assertIn("wireless address", dialog.secondary.lower())
        self.assertIn(
            (i18n.LANGS["en"]["pairing_cancel"], gui.Gtk.ResponseType.CANCEL),
            dialog.buttons,
        )
        self.assertIn(
            (i18n.LANGS["en"]["pairing_ok"], gui.Gtk.ResponseType.OK),
            dialog.buttons,
        )
        self.assertEqual(dialog.default, gui.Gtk.ResponseType.CANCEL)
        self.assertTrue(dialog.destroyed)

    def test_cancel_closes_without_starting_session(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.CANCEL)
        window._on_pairing_clicked(None)
        self.assertEqual(calls, [])
        self.assertFalse(window._pair_busy)
        self.assertTrue(_FakeDialog.created[0].destroyed)

    def test_ok_triggers_callback_and_marks_busy(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._on_pairing_clicked(None)
        self.assertEqual(calls, ["pair"])
        self.assertTrue(window._pair_busy)
        self.assertFalse(window._pair_button.sensitive)
        self.assertTrue(window._pair_cancel.sensitive)

    def test_busy_ignores_second_click(self):
        from src.rapoo_vt7 import gui

        window, calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._on_pairing_clicked(None)
        self.assertEqual(calls, ["pair"])
        window._on_pairing_clicked(None)
        self.assertEqual(calls, ["pair"])

    def test_ok_resets_stale_terminal_state(self):
        from src.rapoo_vt7 import gui

        window, _calls = self._window_and_dialog(gui.Gtk.ResponseType.OK)
        window._pair_last_status = gui.STATUS_ERROR
        window._pair_last_message = "stale"
        window._pair_current_step = 2
        window._on_pairing_clicked(None)
        self.assertIsNone(window._pair_last_status)
        self.assertIsNone(window._pair_last_message)
        self.assertEqual(window._pair_current_step, 0)

    def test_retranslate_reads_current_language(self):
        window, _calls = self._window_and_dialog(42)
        window._lang = "pt_BR"
        window._on_pairing_clicked(None)
        dialog = _FakeDialog.created[0]
        self.assertEqual(
            dialog.kwargs["text"], i18n.LANGS["pt_BR"]["pairing_dialog_title"]
        )
        self.assertEqual(
            dialog.secondary, i18n.LANGS["pt_BR"]["pairing_dialog_message"]
        )


class PairingWindowBehaviorTest(unittest.TestCase):
    def _window(self):
        from src.rapoo_vt7 import gui

        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._lang = "en"
        window._pair_busy = True
        window._pair_last_status = None
        window._pair_last_message = None
        window._pair_current_step = 0
        window._pair_button = _StubButton()
        window._pair_cancel = _StubButton()
        window._pair_steps = [_StubLabel() for _ in range(3)]
        window._pair_status = _StubLabel()
        return window

    def test_update_non_terminal_highlights_step_and_shows_matching(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(1, None, None)
        self.assertTrue(window._pair_busy)
        self.assertEqual(
            window._pair_steps[1].markup,
            "<b>%s</b>" % i18n.LANGS["en"]["pairing_step2"],
        )
        self.assertEqual(
            window._pair_status._text, i18n.LANGS["en"]["pairing_matching"]
        )

    def test_update_terminal_success_releases_busy_and_reenables_start(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(0, gui.STATUS_SUCCESS, None)
        self.assertFalse(window._pair_busy)
        self.assertTrue(window._pair_button.sensitive)
        self.assertFalse(window._pair_cancel.sensitive)
        self.assertEqual(window._pair_last_status, gui.STATUS_SUCCESS)
        self.assertEqual(
            window._pair_status._text, i18n.LANGS["en"]["pairing_success"]
        )

    def test_update_terminal_error_renders_red_with_message_override(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(0, gui.STATUS_ERROR, "boom")
        self.assertFalse(window._pair_busy)
        self.assertTrue(window._pair_button.sensitive)
        self.assertFalse(window._pair_cancel.sensitive)
        self.assertIn("red", window._pair_status.markup)
        self.assertIn("boom", window._pair_status.markup)

    def test_update_cancelled_keeps_busy_until_terminal_callback(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(0, gui.STATUS_CANCELLED, None)
        self.assertFalse(window._pair_busy)
        self.assertEqual(window._pair_last_status, gui.STATUS_CANCELLED)
        self.assertEqual(
            window._pair_status._text, i18n.LANGS["en"]["pairing_cancelled"]
        )

    def test_update_terminal_stores_message_and_step(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(1, gui.STATUS_ERROR, "boom")
        self.assertEqual(window._pair_last_message, "boom")
        self.assertEqual(window._pair_current_step, 1)

    def test_terminal_without_message_clears_stale(self):
        # F7: a terminal result without a message must clear any stale error
        # text from a previous run, or a language change would re-render the
        # old error instead of the correct status key.
        from src.rapoo_vt7 import gui

        window = self._window()
        window._pair_last_message = "stale"
        window.update_pairing_state(0, gui.STATUS_SUCCESS, None)
        self.assertIsNone(window._pair_last_message)

    def test_update_non_terminal_records_step(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        window.update_pairing_state(2, None, None)
        self.assertEqual(window._pair_current_step, 2)

    def test_cancel_clicked_requests_cancel_when_busy(self):
        from src.rapoo_vt7 import gui

        window = self._window()
        calls = []
        window._on_cancel_pairing = lambda: calls.append("cancel")
        window._on_cancel_clicked(None)
        self.assertEqual(calls, ["cancel"])
        window._pair_busy = False
        window._on_cancel_clicked(None)
        self.assertEqual(calls, ["cancel"], "stop outside a run is a no-op")


class MainPairingTest(unittest.TestCase):
    def _app(self):
        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = FakeWindow()
        app._pair_session = None
        app._pair_step = 0
        app._quitting = False
        return app

    def test_on_start_pairing_launches_a_session_with_callbacks(self):
        app = self._app()
        original = main.PairingSession
        created = []

        def factory(**kwargs):
            session = _FakePairingSession(**kwargs)
            created.append(session)
            return session

        main.PairingSession = factory
        try:
            app._on_start_pairing()
        finally:
            main.PairingSession = original
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].started)
        self.assertIs(app._pair_session, created[0])
        self.assertEqual(app._pair_step, 0)
        self.assertTrue(callable(created[0].on_step))
        self.assertTrue(callable(created[0].on_result))

    def test_on_start_pairing_ignores_second_run_while_running(self):
        app = self._app()
        original = main.PairingSession
        created = []

        def factory(**kwargs):
            session = _FakePairingSession(**kwargs)
            created.append(session)
            return session

        main.PairingSession = factory
        try:
            app._on_start_pairing()
            # A run is in flight now: a second start must not spawn again.
            created[0].running = True
            app._on_start_pairing()
        finally:
            main.PairingSession = original
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].started)

    def test_on_cancel_pairing_cancels_the_session(self):
        app = self._app()
        cancelled = []
        app._pair_session = type(
            "S", (), {"cancel": lambda self: cancelled.append(1)}
        )()
        app._on_cancel_pairing()
        self.assertEqual(cancelled, [1])
        app._pair_session = None
        app._on_cancel_pairing()  # no session -> no-op

    def test_on_pair_step_forwards_to_the_window(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        with _sync_idle():
            app._on_pair_step(2)
        self.assertEqual(app._pair_step, 2)
        self.assertEqual(updated, [(2, None, None)])

    def test_apply_result_success_localizes_and_notifies(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        shown = []
        originals = {
            "new": main.Notify.Notification.new,
            "idle_add": main.GLib.idle_add,
        }

        def fake_new(_app, body, _icon):
            shown.append(body)
            return FakeNotification()

        main.Notify.Notification.new = fake_new
        try:
            app._apply_pair_result(STATUS_SUCCESS, None)
        finally:
            main.Notify.Notification.new = originals["new"]
        self.assertEqual(
            updated[-1],
            (app._pair_step, STATUS_SUCCESS, i18n.LANGS["en"]["pairing_success"]),
        )
        self.assertEqual(shown, [i18n.LANGS["en"]["pairing_success"]])

    def test_apply_result_failed_warns_without_success_icon(self):
        app = self._app()
        app._window.update_pairing_state = lambda *a: None
        shown = []
        originals = {}
        originals["new"] = main.Notify.Notification.new

        def fake_new(_app, body, _icon):
            shown.append((body, _icon))
            return FakeNotification()

        main.Notify.Notification.new = fake_new
        try:
            app._apply_pair_result(STATUS_FAILED, None)
        finally:
            main.Notify.Notification.new = originals["new"]
        self.assertEqual(
            shown,
            [(i18n.LANGS["en"]["pairing_failed"], "dialog-warning")],
        )

    def test_apply_result_receiver_not_found_is_localized(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        shown = []
        originals = {"new": main.Notify.Notification.new}

        def fake_new(_app, body, _icon):
            shown.append(body)
            return FakeNotification()

        main.Notify.Notification.new = fake_new
        try:
            app._apply_pair_result(
                STATUS_ERROR, main.ReceiverNotFound("receiver")
            )
        finally:
            main.Notify.Notification.new = originals["new"]
        self.assertEqual(
            updated[-1],
            (
                app._pair_step,
                STATUS_ERROR,
                i18n.LANGS["en"]["pairing_receiver_not_found"],
            ),
        )

    def test_apply_result_generic_error_formats_message(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        shown = []
        originals = {"new": main.Notify.Notification.new}

        def fake_new(_app, body, _icon):
            shown.append(body)
            return FakeNotification()

        main.Notify.Notification.new = fake_new
        try:
            app._apply_pair_result(STATUS_ERROR, OSError("boom"))
        finally:
            main.Notify.Notification.new = originals["new"]
        self.assertEqual(
            updated[-1],
            (
                app._pair_step,
                STATUS_ERROR,
                i18n.LANGS["en"]["pairing_error"].format(error="boom"),
            ),
        )
        self.assertEqual(shown, [i18n.LANGS["en"]["pairing_error"].format(error="boom")])

    def test_apply_result_timeout_and_cancelled_localize(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        shown = []
        originals = {"new": main.Notify.Notification.new}

        def fake_new(_app, body, _icon):
            shown.append(body)
            return FakeNotification()

        main.Notify.Notification.new = fake_new
        try:
            app._apply_pair_result(STATUS_TIMEOUT, None)
            app._apply_pair_result(STATUS_CANCELLED, None)
        finally:
            main.Notify.Notification.new = originals["new"]
        self.assertEqual(
            [u[2] for u in updated],
            [i18n.LANGS["en"]["pairing_timeout"],
             i18n.LANGS["en"]["pairing_cancelled"]],
        )
        # CANCELLED is quiet (no popup).
        self.assertEqual(shown, [i18n.LANGS["en"]["pairing_timeout"]])

    def test_quit_cancels_a_running_session(self):
        app = self._app()
        cancelled = []
        app._pair_session = type(
            "S", (), {"cancel": lambda self: cancelled.append(1)}
        )()
        app._monitor.stop = lambda: None
        app.quit = lambda: None
        originals = {"uninit": main.Notify.uninit}
        main.Notify.uninit = lambda: None
        try:
            app._quit()
        finally:
            main.Notify.uninit = originals["uninit"]
        self.assertEqual(cancelled, [1])
        self.assertTrue(app._quitting)

    def test_pair_callbacks_are_dropped_while_quitting(self):
        app = self._app()
        updated = []
        app._window.update_pairing_state = lambda *a: updated.append(a)
        app._quitting = True
        with _sync_idle():
            app._on_pair_step(2)
            app._on_pair_result(STATUS_SUCCESS, None)
            app._apply_pair_result(STATUS_SUCCESS, None)
        self.assertEqual(app._pair_step, 0, "step must not advance while quitting")
        self.assertEqual(
            updated, [], "no idle_add may touch the window while quitting"
        )

    def test_quit_sets_quitting_before_cancelling(self):
        app = self._app()
        seen = []

        class Session:
            def cancel(self):
                seen.append(app._quitting)

        app._pair_session = Session()
        app._monitor.stop = lambda: None
        app.quit = lambda: None
        originals = {"uninit": main.Notify.uninit}
        main.Notify.uninit = lambda: None
        try:
            app._quit()
        finally:
            main.Notify.uninit = originals["uninit"]
        self.assertEqual(seen, [True], "_quitting must be set before cancel()")


class PairingI18nTest(unittest.TestCase):
    def test_pairing_keys_present_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            for key in (
                "pairing_section",
                "pairing_start",
                "pairing_stop",
                "pairing_hint",
                "pairing_dialog_title",
                "pairing_dialog_message",
                "pairing_cancel",
                "pairing_ok",
                "pairing_step1",
                "pairing_step2",
                "pairing_step3",
                "pairing_matching",
                "pairing_success",
                "pairing_failed",
                "pairing_timeout",
                "pairing_cancelled",
                "pairing_error",
                "pairing_receiver_not_found",
            ):
                self.assertIn(
                    key, lang, "locale %s missing key %r" % (code, key)
                )

    def test_pairing_format_strings_render_in_every_locale(self):
        for code, lang in i18n.LANGS.items():
            with self.subTest(locale=code):
                lang["pairing_error"].format(error="boom")


# --- firmware versions (System tab "Versions" section) --------------------


def fw_reply(minor, major, pid=protocol.PID_USB):
    """Raw hidraw get_firmware reply: 06 01 <minor> <major> .. <pid LE>."""
    resp = bytearray(32)
    resp[0] = protocol.REPORT_CMD
    resp[1] = protocol.RESP_ACK
    resp[protocol.FIRMWARE_OFFSET_MINOR] = minor & 0xFF
    resp[protocol.FIRMWARE_OFFSET_MAJOR] = major & 0xFF
    resp[6] = pid & 0xFF
    resp[7] = (pid >> 8) & 0xFF
    return bytes(resp)


class FirmwareDev:
    """RapooDevice stand-in for the version reads.

    `replies` maps fw_type -> raw reply bytes (or an exception instance/class
    to raise). `prefix` mirrors RapooDevice.prefix so read_receiver_firmware
    can decide to reuse the device or open its own.
    """

    def __init__(self, replies, prefix=protocol.PREFIX_WIRELESS):
        self.replies = dict(replies)
        self.prefix = prefix
        self.queries = []
        self.closed = False

    def close(self):
        self.closed = True

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append((cmd_id, tuple(args)))
        assert cmd_id == protocol.GET_FIRMWARE
        result = self.replies[args[0]]
        if isinstance(result, Exception):
            raise result
        return result

    def get_firmware(self, fw_type=0):
        return self.query(protocol.GET_FIRMWARE, [fw_type])


class FormatVersionTest(unittest.TestCase):
    def test_mouse_version_major_minor(self):
        # On-device reply 2026-08-22: 06 01 91 00 ... -> v0.145.
        self.assertEqual(system.format_mouse_version(fw_reply(0x91, 0x00)), "v0.145")

    def test_mouse_version_two_digit_major(self):
        self.assertEqual(system.format_mouse_version(fw_reply(0x03, 0x01)), "v1.3")

    def test_base_version_a_hub_formula(self):
        # A Hub h(): floor(145/100).(145%100) -> V1.45.
        self.assertEqual(system.format_base_version(fw_reply(0x91, 0x00)), "V1.45")

    def test_base_version_small_byte_not_padded(self):
        self.assertEqual(system.format_base_version(fw_reply(0x08, 0x00)), "V0.8")

    def test_short_replies_raise_value_error(self):
        # format_mouse_version needs data[3] (len > 3); format_base_version
        # only needs data[2] (len > 2) — a 3-byte reply is valid for it.
        for bad in (None, b"", b"\x06\x01\x91"):
            with self.subTest(bad=bad):
                self.assertRaises(ValueError, system.format_mouse_version, bad)
        for bad in (None, b"", b"\x06"):
            with self.subTest(bad=bad):
                self.assertRaises(ValueError, system.format_base_version, bad)


class ReadMouseFirmwareTest(unittest.TestCase):
    def test_reads_type_0_on_active_connection(self):
        dev = FirmwareDev({0: fw_reply(0x91, 0x00)})
        self.assertEqual(system.read_mouse_firmware(dev), "v0.145")
        self.assertEqual(dev.queries, [(protocol.GET_FIRMWARE, (0,))])


class ReadReceiverFirmwareTest(unittest.TestCase):
    def test_reuses_device_already_on_receiver(self):
        dev = FirmwareDev(
            {0: fw_reply(0x91, 0x00), 1: fw_reply(0x92, 0x00)},
            prefix=protocol.PREFIX_WIRELESS,
        )
        self.assertEqual(system.read_receiver_firmware(dev), "V1.45-V1.46")
        self.assertEqual(
            dev.queries,
            [
                (protocol.GET_FIRMWARE, (0,)),
                (protocol.GET_FIRMWARE, (1,)),
            ],
        )

    def test_opens_receiver_only_fd_when_on_cable(self):
        cable_dev = FirmwareDev({}, prefix=protocol.PREFIX_USB)
        rx_dev = FirmwareDev(
            {0: fw_reply(0x91, 0x00), 1: fw_reply(0x91, 0x00)},
            prefix=protocol.PREFIX_WIRELESS,
        )
        with mock.patch.object(
            system, "RapooDevice", create=True
        ) as ctor:
            ctor.return_value.open.return_value = rx_dev
            self.assertEqual(
                system.read_receiver_firmware(cable_dev), "V1.45-V1.45"
            )
            ctor.return_value.open.assert_called_once_with(
                prefix=protocol.PREFIX_WIRELESS
            )

    def test_none_dev_opens_receiver_only_fd(self):
        rx_dev = FirmwareDev(
            {0: fw_reply(0x2A, 0x00), 1: fw_reply(0x63, 0x00)},
            prefix=protocol.PREFIX_WIRELESS,
        )
        with mock.patch.object(system, "RapooDevice", create=True) as ctor:
            ctor.return_value.open.return_value = rx_dev
            self.assertEqual(
                system.read_receiver_firmware(None), "V0.42-V0.99"
            )


class ReadVersionsTest(unittest.TestCase):
    def test_both_rows_ok(self):
        rx = FirmwareDev(
            {0: fw_reply(0x91, 0x00), 1: fw_reply(0x92, 0x00)},
            prefix=protocol.PREFIX_WIRELESS,
        )
        mouse, receiver = system.read_versions(rx)
        self.assertEqual(mouse, "v0.145")
        self.assertEqual(receiver, "V1.45-V1.46")

    def test_mouse_asleep_on_cable_receiver_still_answers(self):
        # The app sits on the USB cable (mouse asleep -> mouse row times out);
        # the receiver row runs on its own short-lived fd and still answers.
        cable = FirmwareDev({0: CommandTimeout("asleep")}, prefix=protocol.PREFIX_USB)
        rx = FirmwareDev(
            {0: fw_reply(0x91, 0x00), 1: fw_reply(0x91, 0x00)},
            prefix=protocol.PREFIX_WIRELESS,
        )
        with mock.patch.object(system, "RapooDevice", create=True) as ctor:
            ctor.return_value.open.return_value = rx
            self.assertEqual(system.read_versions(cable), (None, "V1.45-V1.45"))
            self.assertTrue(rx.closed)

    def test_mouse_asleep_shared_wireless_dev_fails_both(self):
        # On the wireless interface both rows share the receiver fd: an
        # asleep mouse times out every get_firmware.
        dev = FirmwareDev(
            {0: CommandTimeout("asleep"), 1: CommandTimeout("asleep")}
        )
        self.assertEqual(system.read_versions(dev), (None, None))

    def test_receiver_missing_degrades_to_none(self):
        from src.rapoo_vt7.device import DeviceNotFound

        dev = FirmwareDev(
            {
                0: fw_reply(0x91, 0x00),
                1: DeviceNotFound("no receiver"),
            },
            prefix=protocol.PREFIX_WIRELESS,
        )
        self.assertEqual(system.read_versions(dev), ("v0.145", None))

    def test_total_failure_returns_none_none(self):
        dev = FirmwareDev(
            {0: CommandTimeout("asleep"), 1: CommandTimeout("down")}
        )
        self.assertEqual(system.read_versions(dev), (None, None))


class VersionsI18nTest(unittest.TestCase):
    def test_version_keys_exist_in_every_locale(self):
        keys = ("versions_section", "fw_mouse", "fw_receiver", "fw_software")
        for code, lang in i18n.LANGS.items():
            for key in keys:
                self.assertIn(key, lang, "locale %s missing key %r" % (code, key))


if __name__ == "__main__":
    unittest.main()
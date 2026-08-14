import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import i18n, main, protocol, system
from src.rapoo_vt7.device import CommandTimeout

# --- fakes ---------------------------------------------------------------


def factory_state():
    return {
        protocol.EEPROM_BANK0_BASE + protocol.MOUSE_DPI_CUR: b"\x00",
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
    query for RETURN_FACTORY_SETTINGS swaps `data` for the factory state (the
    reset) and returns a plain ACK. The `before` reads happen before the query,
    the `after` reads see the factory state.
    """

    def __init__(self, data=None, factory=None):
        self.path = "/dev/hidraw2"
        self.data = dict(data or {})
        self.factory = dict(factory or {})
        self.queries = []
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

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append(cmd_id)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.data = dict(self.factory)
            return ack_reply()
        raise AssertionError("unexpected query cmd 0x%02X" % cmd_id)

    def write_eeprom(self, addr, data):
        self.writes.append(((addr[1] << 8) | addr[0], bytes(data)))
        self.data[(addr[1] << 8) | addr[0]] = bytes(data)
        return ack_reply()


class ShortDev:
    def read_eeprom(self, addr, length=1):
        return b"\x00" * 4


class NoAckDev(FakeDev):
    """query answers the 0xAD with a non-ACK (empty) reply."""

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append(cmd_id)
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_EMPTY
        return bytes(resp)


class TimeoutDev(FakeDev):
    """query raises CommandTimeout (mouse asleep / no response)."""

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append(cmd_id)
        raise CommandTimeout("no response")


class RebootDev(FakeDev):
    """The first post-reset reads raise CommandTimeout (mouse rebooting), then
    the reads succeed and reflect the factory state."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.resets = 0
        self.fail_after_reset = 1

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append(cmd_id)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.data = dict(self.factory)
            self.resets += 1
            return ack_reply()
        raise AssertionError("unexpected query cmd 0x%02X" % cmd_id)

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

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        self.queries.append(cmd_id)
        if cmd_id == protocol.RETURN_FACTORY_SETTINGS:
            self.data = dict(self.factory)
            self.resets += 1
            return ack_reply()
        raise AssertionError("unexpected query cmd 0x%02X" % cmd_id)

    def read_eeprom(self, addr, length=1):
        if self.resets:
            raise CommandTimeout("rebooting")
        return super().read_eeprom(addr, length)


class FakeMonitor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        self.jobs.append((fn, on_done, on_error, wake))


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

    def set_system_message(self, message, is_error=False):
        self.messages.append((message, is_error))


class FakeNotification:
    def show(self):
        pass


# --- system module tests -------------------------------------------------


class FactoryDefaultsTest(unittest.TestCase):
    def test_factory_sensor_mode_is_the_validated_table(self):
        self.assertEqual(list(system.FACTORY_SENSOR_MODE), [0, 0, 1, 1, 3, 3, 3])
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
    def test_sends_0xad_ack_and_verifies_factory_defaults(self):
        dev = FakeDev(data=user_state(), factory=factory_state())
        result = system.factory_reset(dev)
        self.assertEqual(dev.queries, [protocol.RETURN_FACTORY_SETTINGS])
        self.assertEqual(dev.writes, [])
        self.assertTrue(result["acked"])
        self.assertEqual(result["before"], system.read_verify_state(FakeDev(data=user_state())))
        self.assertEqual(
            result["after"],
            {"dpi_cur": 0, "rf_byte": 0, "sensor_mode": list(system.FACTORY_SENSOR_MODE)},
        )

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
        self.assertEqual(result["after"]["dpi_cur"], 0)

    def test_all_post_reset_reads_fail_raises_verify_error(self):
        # The reset was ACKed but the mouse never answered the post-reset
        # reads: the failure must surface as a verification error (localized),
        # not as a raw CommandTimeout ("no response / mouse asleep").
        dev = BoomDev(data=user_state(), factory=factory_state())
        with self.assertRaises(system.FactoryResetVerifyError):
            system.factory_reset(dev, attempts=2, delay=0)


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
            (i18n.LANGS["en"]["factory_reset_ack_error"], True),
        )

    def test_verify_error_is_localized(self):
        app = self._app()
        with _sync_idle():
            app._factory_reset_error(system.FactoryResetVerifyError("verify"))
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["factory_reset_verify_error"], True),
        )

    def test_timeout_surfaces_raw_message(self):
        app = self._app()
        with _sync_idle():
            app._factory_reset_error(CommandTimeout("no response"))
        self.assertEqual(app._window.messages[-1], ("no response", True))

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
        self.assertEqual(len(shown), 1)
        self.assertEqual(
            app._window.messages[-1],
            (i18n.LANGS["en"]["factory_reset_success"], False),
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
        window.set_system_message("done", False)
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

    def set_halign(self, halign):
        self.halign = halign

    def set_line_wrap(self, _wrap):
        pass

    def set_margin_top(self, _m):
        pass

    def connect(self, _signal, _handler):
        pass

    def set_label(self, _label):
        pass

    def set_markup(self, _markup):
        pass

    def set_sensitive(self, sensitive):
        self.sensitive = sensitive

    def set_text(self, _text):
        pass


class _StubButton(_StubWidget):
    pass


class _StubLabel(_StubWidget):
    pass


class _StubVBox:
    def __init__(self):
        self.children = []

    def pack_start(self, child, *args):
        self.children.append(child)


class FactoryResetTabTest(unittest.TestCase):
    """Headless coverage of the System tab construction: a reset button labeled
    with the localized string is created, plus the hint (matrix row 1)."""

    def _build(self):
        from src.rapoo_vt7 import gui

        original_button = gui.Gtk.Button
        original_label = gui.Gtk.Label
        gui.Gtk.Button = _StubButton
        gui.Gtk.Label = _StubLabel
        self.addCleanup(setattr, gui.Gtk, "Button", original_button)
        self.addCleanup(setattr, gui.Gtk, "Label", original_label)

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
        self.assertEqual(
            [w.kwargs["label"] for w in labels],
            [i18n.LANGS["en"]["factory_reset_hint"]],
        )
        buttons = [w for w in vbox.children if isinstance(w, _StubButton)]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(
            buttons[0].kwargs["label"], i18n.LANGS["en"]["factory_reset_button"]
        )


if __name__ == "__main__":
    unittest.main()
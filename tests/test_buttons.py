import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import buttons, protocol
from src.rapoo_vt7.device import CommandTimeout

# --- fakes ---------------------------------------------------------------


class _sync_idle:
    """Context manager: make GLib.idle_add invoke callbacks synchronously so
    handler tests can assert surfaced errors/notifications."""

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


class BoomDev(FakeDev):
    """FakeDev whose read_eeprom returns a short reply for one button among
    healthy ones (simulates one broken field)."""

    def __init__(self, data=None, broken="mouse_left"):
        super().__init__(data)
        self.broken = broken

    def read_eeprom(self, addr, length=1):
        if self.broken == "mouse_left" and (addr[1] << 8) | addr[0] == 0x0600:
            return b"\x00" * protocol.EEPROM_DATA_OFFSET
        return super().read_eeprom(addr, length)


class NoVerifyDev(FakeDev):
    def write_eeprom_verify(self, addr, data):
        return b"\xff" * len(data)


class FakeMonitor:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        self.jobs.append((fn, on_done, on_error, wake))


# --- tests ---------------------------------------------------------------


class ButtonsTableTest(unittest.TestCase):
    def test_all_buttons_registered(self):
        expected = {
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
        }
        self.assertEqual({name for name, _o in buttons.BUTTONS}, expected)
        self.assertEqual(len(buttons.BUTTONS), 13)

    def test_button_offsets_match_protocol(self):
        cases = {
            "mouse_left": protocol.MOUSE_LEFT,
            "mouse_middle": protocol.MOUSE_MID,
            "mouse_right": protocol.MOUSE_RIGHT,
            "mouse_dpi_add": protocol.MOUSE_CPIADD,
            "mouse_dpi_reduce": protocol.MOUSE_CPIREDUCE,
            "mouse_forward": protocol.MOUSE_FORWARD,
            "mouse_back": protocol.MOUSE_BACK,
            "mouse_scroll_forward": protocol.MOUSE_ROLLFORWARD,
            "mouse_scroll_back": protocol.MOUSE_ROLLBACK,
            "mouse_scroll_right": protocol.MOUSE_ROLLRIGHT,
            "mouse_scroll_left": protocol.MOUSE_ROLLLEFT,
            "mouse_bottom": protocol.MOUSE_BOTTOM,
            "mouse_ble": protocol.MOUSE_BLE,
        }
        for name, offset in cases.items():
            with self.subTest(button=name):
                self.assertEqual(buttons._BUTTON_BY_NAME[name], offset)

    def test_every_method_is_four_bytes(self):
        for fid, method in buttons.METHODS.items():
            with self.subTest(fn=fid):
                self.assertEqual(len(method), 4)
        for fid, method in buttons._DECODE_ONLY.items():
            with self.subTest(fn=fid):
                self.assertEqual(len(method), 4)

    def test_every_offered_method_decodes(self):
        for fid, method in buttons.METHODS.items():
            with self.subTest(fn=fid):
                self.assertIsNotNone(buttons.method_name(method))

    def test_decode_only_not_offered_in_picker(self):
        # Combo/keyboard/macro and BLE-left codes label read-backs but are
        # never offered as remap targets (gated until device-validated).
        for fid in buttons._DECODE_ONLY:
            self.assertNotIn(fid, buttons.METHODS)

    def test_methods_unique_except_scroll_pair(self):
        seen = {}
        for fid, method in buttons.METHODS.items():
            prev = seen.get(method)
            if prev is not None:
                # scroll_forward/scroll_backward share one code by design.
                self.assertEqual(
                    {prev, fid},
                    {"scroll_forward", "scroll_backward"},
                    "method %s duplicated (already %r)" % (method.hex(), prev),
                )
            else:
                seen[method] = fid


class DecodeTest(unittest.TestCase):
    def test_known_method_decodes(self):
        self.assertEqual(
            buttons.method_name(bytes.fromhex("03000100")), "mouse_left"
        )
        self.assertEqual(
            buttons.method_name(bytes.fromhex("08000500")), "dpi_plus"
        )
        self.assertEqual(
            buttons.method_name(bytes.fromhex("0bff00ff")), "scroll_forward"
        )
        self.assertEqual(buttons.method_name(bytes.fromhex("0a000000")), "diy_button")
        self.assertEqual(buttons.method_name(bytes.fromhex("07000000")), "button_disable")

    def test_unknown_method_returns_none(self):
        self.assertIsNone(buttons.method_name(bytes.fromhex("00010203")))

    def test_scroll_direction_is_contextual_per_button(self):
        shared = bytes.fromhex("0bff00ff")
        self.assertEqual(
            buttons.method_name(shared, "mouse_scroll_back"), "scroll_backward"
        )
        self.assertEqual(
            buttons.method_name(shared, "mouse_scroll_forward"), "scroll_forward"
        )
        # Without a button name the first id wins (back-compat).
        self.assertEqual(buttons.method_name(shared), "scroll_forward")

    def test_left_click_detection(self):
        self.assertTrue(buttons.is_left_click(bytes.fromhex("03000100")))
        self.assertTrue(buttons.is_left_click(bytes.fromhex("03000101")))
        self.assertFalse(buttons.is_left_click(bytes.fromhex("03000400")))
        self.assertFalse(buttons.is_left_click(bytes.fromhex("08000500")))

    def test_left_click_no_overmatch_on_non_left_mouse_button(self):
        # Type 0x03 with a different button index in byte 2 must not count as
        # left-click (would silently bend the ≥1-left rule).
        self.assertFalse(buttons.is_left_click(bytes.fromhex("03000200")))
        self.assertFalse(buttons.is_left_click(bytes.fromhex("03001000")))
        self.assertFalse(buttons.is_left_click(bytes.fromhex("03000000")))

    def test_left_click_no_undermatch_on_left_variant(self):
        # A left button with a non-zero flag byte is still left-click.
        self.assertTrue(buttons.is_left_click(bytes.fromhex("030001ff")))
        self.assertTrue(buttons.is_left_click(bytes.fromhex("0300010a")))
        self.assertTrue(buttons.is_left_click(bytes.fromhex("03000101")))

    def test_button_addr_format(self):
        self.assertEqual(buttons.button_addr("mouse_left"), "0x0600")
        self.assertEqual(buttons.button_addr("mouse_ble"), "0x0638")


class ReadButtonTest(unittest.TestCase):
    def test_read_known_button(self):
        dev = FakeDev(data={0x0600: bytes.fromhex("03000100")})
        state = buttons.read_button(dev, "mouse_left")
        self.assertEqual(state["name"], "mouse_left")
        self.assertEqual(state["addr"], "0x0600")
        self.assertEqual(state["method"], bytes.fromhex("03000100"))
        self.assertEqual(state["fn"], "mouse_left")
        self.assertEqual(state["raw_hex"], "03000100")

    def test_read_ble_left_click(self):
        dev = FakeDev(data={0x0638: bytes.fromhex("03000101")})
        state = buttons.read_button(dev, "mouse_ble")
        self.assertEqual(state["fn"], "mouse_left_ble")  # decode-only label
        self.assertTrue(buttons.is_left_click(state["method"]))

    def test_read_unknown_method(self):
        dev = FakeDev(data={0x0600: bytes.fromhex("00010203")})
        state = buttons.read_button(dev, "mouse_left")
        self.assertIsNone(state["fn"])
        self.assertEqual(state["raw_hex"], "00010203")

    def test_short_reply_raises(self):
        with self.assertRaises(ValueError):
            buttons.read_button(ShortDev(), "mouse_left")


class ReadSectionTest(unittest.TestCase):
    def test_reads_all_buttons(self):
        dev = FakeDev()
        info = buttons.read_section(dev)
        self.assertEqual(len(info["buttons"]), 13)
        self.assertEqual(info["errors"], {})
        for name in buttons._BUTTON_BY_NAME:
            self.assertIn(name, info["buttons"])

    def test_isolated_broken_button(self):
        dev = BoomDev()
        info = buttons.read_section(dev)
        self.assertEqual(len(info["buttons"]), 12)
        self.assertEqual(list(info["errors"]), ["mouse_left"])
        self.assertNotIn("mouse_left", info["buttons"])

    def test_device_error_propagates(self):
        class Boom2(ShortDev):
            pass

        dev = Boom2()
        dev.read_eeprom = lambda addr, length=1: (_ for _ in ()).throw(
            CommandTimeout("asleep")
        )
        with self.assertRaises(CommandTimeout):
            buttons.read_section(dev)


class SetFunctionTest(unittest.TestCase):
    def test_set_known_function_verified(self):
        dev = FakeDev()
        result = buttons.set_function(dev, "mouse_right", "fire_button")
        self.assertEqual(result["fn"], "fire_button")
        self.assertEqual(dev.writes[-1], (0x0608, bytes.fromhex("09000200")))
        self.assertEqual(result["raw_hex"], "09000200")

    def test_unknown_function_raises(self):
        dev = FakeDev()
        with self.assertRaises(ValueError):
            buttons.set_function(dev, "mouse_right", "not_a_function")

    def test_unverified_write_raises(self):
        dev = NoVerifyDev()
        with self.assertRaises(ValueError):
            buttons.set_function(dev, "mouse_right", "fire_button")

    def test_keeps_last_left_click(self):
        # Only mouse_left is left-click: remapping it away must be refused.
        dev = FakeDev(
            data={
                0x0600: bytes.fromhex("03000100"),  # left (only left-click)
                0x0638: bytes.fromhex("03000400"),  # BLE not left
            }
        )
        with self.assertRaises(ValueError):
            buttons.set_function(dev, "mouse_left", "fire_button")

    def test_allows_left_remap_when_another_is_left(self):
        # mouse_left is left-click AND BLE is left-click capable: the in-module
        # allow branch (is_left_click(current) -> others_left scan) must run
        # and permit the remap.
        dev = FakeDev(
            data={
                0x0600: bytes.fromhex("03000100"),  # left is left-click
                0x0638: bytes.fromhex("03000101"),  # BLE also left-click
            }
        )
        result = buttons.set_function(dev, "mouse_left", "fire_button")
        self.assertEqual(result["fn"], "fire_button")
        self.assertEqual(dev.writes[-1], (0x0600, bytes.fromhex("09000200")))

    def test_setting_left_on_a_button_is_allowed(self):
        dev = FakeDev()
        result = buttons.set_function(dev, "mouse_right", "mouse_left")
        self.assertEqual(result["fn"], "mouse_left")
        self.assertEqual(dev.writes[-1], (0x0608, bytes.fromhex("03000100")))


class SettingsRegistryTest(unittest.TestCase):
    def test_button_fields_are_four_bytes(self):
        from src.rapoo_vt7 import settings

        for name, _offset in buttons.BUTTONS:
            with self.subTest(button=name):
                self.assertEqual(settings.FIELDS[name].size, 4)

    def test_button_offsets_match_settings_addresses(self):
        # buttons.BUTTONS (the app writes these addresses) must never drift
        # from settings.FIELDS (what probe/status decode) — a drift would make
        # the app write one address and probe read another.
        from src.rapoo_vt7 import protocol, settings

        for name, offset in buttons.BUTTONS:
            with self.subTest(button=name):
                field_addr = (settings.FIELDS[name].addr[1] << 8) | settings.FIELDS[name].addr[0]
                bank_addr = protocol.EEPROM_BANK0_BASE + offset
                self.assertEqual(field_addr, bank_addr)


class MainButtonTest(unittest.TestCase):
    def _app(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._monitor = FakeMonitor()
        app._window = FakeWindow()
        return app

    def test_on_set_button_submits_write_with_wake(self):
        from src.rapoo_vt7 import main

        app = self._app()
        app._on_set_button("mouse_right", "fire_button")
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, on_done, on_error, wake = app._monitor.jobs[0]
        self.assertTrue(wake)
        self.assertTrue(callable(on_done))
        self.assertTrue(callable(on_error))
        state = fn(FakeDev(data={0x0608: bytes.fromhex("03000200")}))
        self.assertEqual(state["fn"], "fire_button")
        self.assertEqual(state["raw_hex"], "09000200")

    def test_unknown_function_refused_before_submit(self):
        from src.rapoo_vt7 import main

        app = self._app()
        with _sync_idle():
            app._on_set_button("mouse_right", "not_a_function")
        self.assertEqual(len(app._monitor.jobs), 0)
        self.assertEqual(app._window.errors[-1], "Unknown function: not_a_function")

    def test_last_left_refused_before_submit(self):
        from src.rapoo_vt7 import main

        app = self._app()
        # Only mouse_left is left-click (last left-click-capable button).
        app._window.buttons = {
            n: {
                "fn": "mouse_left" if n == "mouse_left" else None,
                "method": (
                    bytes.fromhex("03000100")
                    if n == "mouse_left"
                    else bytes.fromhex("08000500")
                ),
                "raw_hex": "03000100" if n == "mouse_left" else "08000500",
            }
            for n, _o in buttons.BUTTONS
        }
        with _sync_idle():
            app._on_set_button("mouse_left", "fire_button")
        self.assertEqual(len(app._monitor.jobs), 0)
        self.assertIn("left", app._window.errors[-1].lower())

    def test_left_remap_allowed_when_another_left_exists(self):
        from src.rapoo_vt7 import main

        app = self._app()
        # BLE is left-click capable -> mouse_left may be remapped away.
        app._window.buttons = {
            n: {
                "fn": "mouse_left" if n == "mouse_left" else None,
                "method": (
                    bytes.fromhex("03000100")
                    if n in ("mouse_left", "mouse_ble")
                    else bytes.fromhex("08000500")
                ),
                "raw_hex": "03000100" if n in ("mouse_left", "mouse_ble") else "08000500",
            }
            for n, _o in buttons.BUTTONS
        }
        app._on_set_button("mouse_left", "fire_button")
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, _on_done, _on_error, _wake = app._monitor.jobs[0]
        state = fn(FakeDev())
        self.assertEqual(state["fn"], "fire_button")

    def test_button_changed_notifies_and_refreshes(self):
        from src.rapoo_vt7 import main

        app = self._app()
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
            app._button_changed({"name": "mouse_right", "fn": "fire_button"})
        finally:
            main.Notify.Notification.new = originals["new"]
            main.GLib.idle_add = originals["idle_add"]
        self.assertEqual(len(shown), 1)
        self.assertIn("Right button", shown[0])
        self.assertIn("Fire button", shown[0])

    def test_maybe_refresh_refuses_when_tab_missing(self):
        from src.rapoo_vt7 import main

        app = self._app()
        app._maybe_refresh_buttons()
        self.assertEqual(len(app._monitor.jobs), 1)
        self.assertFalse(app._monitor.jobs[0][3])  # background read, not wake

    def test_maybe_refresh_skips_when_healthy(self):
        from src.rapoo_vt7 import main

        app = self._app()
        app._window.update_buttons({"buttons": {}, "errors": {}})
        app._maybe_refresh_buttons()
        self.assertEqual(len(app._monitor.jobs), 0)

    def test_maybe_refresh_recovers_from_section_error(self):
        from src.rapoo_vt7 import main

        app = self._app()
        # A failed remap while asleep left the section in error with the
        # last-known payload retained: on the next connected event the tab
        # must be re-read (not stay disabled forever).
        app._window.update_buttons({"buttons": {}, "errors": {}})
        app._window.set_buttons_error("boom")
        app._maybe_refresh_buttons()
        self.assertEqual(len(app._monitor.jobs), 1)
        self.assertEqual(app._window.errors[-1], "boom")

    def test_update_buttons_clears_section_error(self):
        app = self._app()
        app._window.set_buttons_error("boom")
        self.assertFalse(app._window.has_buttons())
        app._window.update_buttons({"buttons": {}, "errors": {}})
        self.assertTrue(app._window.has_buttons())

    def test_no_left_click_error_from_live_scan_is_localized(self):
        # The authoritative in-module refusal path: the window's last-known
        # state passes the pre-check, but set_function's live scan finds no
        # other left-click button -> NoLeftClickError must surface as the
        # localized button_no_left message (not a raw exception string).
        from src.rapoo_vt7 import main

        app = self._app()
        # Window cache claims BLE is left-click (pre-check would pass)...
        app._window.buttons = {
            n: {
                "fn": "mouse_left" if n in ("mouse_left", "mouse_ble") else None,
                "method": (
                    bytes.fromhex("03000100")
                    if n in ("mouse_left", "mouse_ble")
                    else bytes.fromhex("08000500")
                ),
                "raw_hex": "03000100" if n in ("mouse_left", "mouse_ble") else "08000500",
            }
            for n, _o in buttons.BUTTONS
        }
        app._on_set_button("mouse_left", "fire_button")
        self.assertEqual(len(app._monitor.jobs), 1)
        fn, _on_done, on_error, _wake = app._monitor.jobs[0]
        # ...but live reads show NO other left (only mouse_left itself).
        dev = FakeDev(data={0x0600: bytes.fromhex("03000100")})
        with self.assertRaises(buttons.NoLeftClickError):
            fn(dev)
        with _sync_idle():
            on_error(buttons.NoLeftClickError())
        self.assertIn("left", app._window.errors[-1].lower())

    def test_on_button_changed_raw_selection_is_noop(self):
        from src.rapoo_vt7 import gui

        calls = []
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._buttons_loading = False
        window._buttons = {"buttons": {"mouse_right": {"fn": "fire_button"}}}
        window._on_set_button = lambda name, fid: calls.append((name, fid))
        combo = _StubCombo()
        combo.active = "__raw__"
        window._on_button_changed(combo, "mouse_right")
        self.assertEqual(calls, [])

    def test_on_button_changed_decode_only_selection_is_noop(self):
        # Decode-only ids (BLE left-click variant, gated combos) are shown as a
        # labelled row but are not writable — re-selecting one must not submit.
        from src.rapoo_vt7 import gui

        calls = []
        window = gui.BatteryWindow.__new__(gui.BatteryWindow)
        window._buttons_loading = False
        window._buttons = {
            "buttons": {"mouse_ble": {"fn": "mouse_left_ble"}}
        }
        window._on_set_button = lambda name, fid: calls.append((name, fid))
        combo = _StubCombo()
        combo.active = "mouse_left_ble"
        window._on_button_changed(combo, "mouse_ble")
        self.assertEqual(calls, [])


class FakeWindow:
    """Stands in for BatteryWindow in main.py handler tests (error-aware
    `has_buttons` / `update_buttons` mirror gui.BatteryWindow)."""

    def __init__(self):
        self.buttons = None
        self.errors = []
        self._error = None
        self._lang = "en"

    def get_buttons_info(self):
        if self.buttons is None:
            return None
        return {"buttons": self.buttons, "errors": {}}

    def set_buttons_error(self, message):
        self.errors.append(message)
        self._error = message

    def update_buttons(self, info):
        self.buttons = info["buttons"]
        self._error = None

    def has_buttons(self):
        return self.buttons is not None and self._error is None


class FakeNotification:
    def show(self):
        pass


class _StubCombo:
    """Minimal ComboBoxText stand-in for gui._on_button_changed."""

    def __init__(self):
        self.active = None

    def get_active(self):
        return True

    def get_active_id(self):
        return self.active


class I18nLabelBindingTest(unittest.TestCase):
    def test_every_function_label_exists_in_every_locale(self):
        from src.rapoo_vt7 import i18n

        for fid in buttons.METHODS:
            for code, lang in i18n.LANGS.items():
                self.assertIn(
                    "fn_" + fid,
                    lang,
                    "locale %s missing fn_%s" % (code, fid),
                )

    def test_every_decode_only_function_label_exists(self):
        # Decode-only fns (BLE left variant, gated combos) still label the
        # shown current function, so every one needs an i18n label too.
        from src.rapoo_vt7 import i18n

        for fid in buttons._DECODE_ONLY:
            for code, lang in i18n.LANGS.items():
                self.assertIn(
                    "fn_" + fid,
                    lang,
                    "locale %s missing fn_%s" % (code, fid),
                )

    def test_every_button_label_exists_in_every_locale(self):
        from src.rapoo_vt7 import i18n

        for name, _offset in buttons.BUTTONS:
            for code, lang in i18n.LANGS.items():
                self.assertIn(
                    "btn_" + name,
                    lang,
                    "locale %s missing btn_%s" % (code, name),
                )


if __name__ == "__main__":
    unittest.main()

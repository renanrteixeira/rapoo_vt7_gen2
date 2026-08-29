"""Headless coverage of the UI theme system + config theme persistence and the
window header render path.

These are new in the UI-redesign spec (spec-ui-redesign.md): a GTK CSS theme
with light/dark/system resolution, a persisted ``theme`` preference in
config.json, and the persistent device header (battery/mode/DPI/rate) in
``BatteryWindow``. They follow the existing headless style: ``__new__``-based
window builds with stub widgets, and temp files for config — no display.
"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# nopyflakes
assert sys.path  # keep import arg reachable for lint

from src.rapoo_vt7 import config, gui, i18n, theme, tray  # noqa: F401


class _StubLabel:
    """Widget stub recording `set_text` (bound methods) + no-op style ctx."""

    def __init__(self):
        self.text = ""

    def set_text(self, text):
        self.text = text

    def get_style_context(self):
        return NS(add_class=lambda c: None)


def _stub_label():
    return _StubLabel()


class _Hover:
    """set_label-only menu-item stub (duck-typed) used for assertions."""

    def set_label(self, text):
        self.text = text


class ThemeResolutionTest(unittest.TestCase):
    """sanitize_theme / effective_theme (I/O THEME_LOAD / THEME_SET)."""

    def test_invalid_defaults_to_system(self):
        from src.rapoo_vt7 import theme

        self.assertEqual(theme.sanitize_theme("banana"), "system")
        self.assertEqual(theme.sanitize_theme(None), "system")
        self.assertEqual(theme.sanitize_theme(""), "system")

    def test_valid_themes_kept(self):
        from src.rapoo_vt7 import theme

        for code in ("light", "dark", "system"):
            self.assertEqual(theme.sanitize_theme(code), code)

    def _gio(self, scheme=None, gtk_theme=None):
        """A fake Gio.Settings with a fixed color-scheme + gtk-theme."""
        return NS(
            get_string=lambda name: {
                "color-scheme": scheme if scheme is not None else "",
                "gtk-theme": gtk_theme or "",
            }[name]
        )

    def test_system_resolves_dark_via_color_scheme(self):
        from src.rapoo_vt7 import theme

        gio = self._gio(scheme="prefer-dark")
        with (
            mock.patch.object(theme, "Gio"),
            mock.patch.object(theme, "Gtk"),
        ):
            theme.Gio.Settings.new.return_value = gio
            self.assertEqual(theme.effective_theme("system"), "dark")

    def test_system_resolves_light_via_color_scheme(self):
        from src.rapoo_vt7 import theme

        gio = self._gio(scheme="prefer-light")
        with (
            mock.patch.object(theme, "Gio"),
            mock.patch.object(theme, "Gtk"),
        ):
            theme.Gio.Settings.new.return_value = gio
            self.assertEqual(theme.effective_theme("system"), "light")

    def test_system_resolves_dark_via_theme_name_fallback(self):
        """Ubuntu builds without a color-scheme key still ship a `-dark`
        theme (e.g. Yaru-red-dark); color-scheme empty -> theme-name wins."""
        from src.rapoo_vt7 import theme

        gio = self._gio(scheme="", gtk_theme="Yaru-red-dark")
        with mock.patch.object(theme, "Gio") as gio_mock:
            gio_mock.Settings.new.return_value = gio
            self.assertEqual(theme.effective_theme("system"), "dark")

    def test_system_resolves_light_when_default_theme(self):
        from src.rapoo_vt7 import theme

        gio = self._gio(scheme="", gtk_theme="Yaru")
        with mock.patch.object(theme, "Gio") as gio_mock:
            gio_mock.Settings.new.return_value = gio
            gio_mock.Settings.new.side_effect = None
            self.assertEqual(theme.effective_theme("system"), "light")

    def test_system_gtk_fallback_when_no_gio(self):
        """Gio unavailable/raising: falls back to the GTK dark property."""
        from src.rapoo_vt7 import theme

        with mock.patch.object(theme, "Gio") as gio:
            gio.Settings.new.side_effect = Exception("no gio")
            with mock.patch.object(theme, "Gtk") as gtk:
                gtk.Settings.get_default.return_value = NS(
                    get_property=lambda name: True
                )
                self.assertEqual(theme.effective_theme("system"), "dark")

    def test_system_resolves_light_when_no_gtk(self):
        from src.rapoo_vt7 import theme

        # Gio empty + no GTK settings object (headless): falls back to "light".
        gio = self._gio(scheme="", gtk_theme="")
        with mock.patch.object(theme, "Gio") as gio_mock:
            gio_mock.Settings.new.return_value = gio
            with mock.patch.object(theme, "Gtk") as gtk:
                gtk.Settings.get_default.return_value = None
                self.assertEqual(theme.effective_theme("system"), "light")

    def test_explicit_overrides_system(self):
        from src.rapoo_vt7 import theme

        with mock.patch.object(theme, "Gtk") as gtk:
            gtk.Settings.get_default.return_value = NS(
                get_property=lambda name: True
            )
            self.assertEqual(theme.effective_theme("dark"), "dark")
            self.assertEqual(theme.effective_theme("light"), "light")


class ConfigThemePersistenceTest(unittest.TestCase):
    """load_theme / save_theme round-trip + invalid fallback (I/O THEME_SET)."""

    def test_save_then_load_roundtrip(self):
        from src.rapoo_vt7 import config

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with mock.patch.object(config, "CONFIG_PATH", path):
                config.save_theme("dark")
                self.assertEqual(config.load_theme(), "dark")
                config.save_theme("light")
                self.assertEqual(config.load_theme(), "light")

    def test_load_missing_defaults_to_system(self):
        from src.rapoo_vt7 import config

        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.json")
            with mock.patch.object(config, "CONFIG_PATH", missing):
                self.assertEqual(config.load_theme(), "system")

    def test_save_invalid_coerced_to_system(self):
        from src.rapoo_vt7 import config

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with mock.patch.object(config, "CONFIG_PATH", path):
                config.save_theme("purple")
                self.assertEqual(config.load_theme(), "system")

    def test_theme_does_not_clobber_language(self):
        from src.rapoo_vt7 import config

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with mock.patch.object(config, "CONFIG_PATH", path):
                config.save_language("en")
                config.save_theme("dark")
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.assertEqual(data["language"], "en")
                self.assertEqual(data["theme"], "dark")
                self.assertEqual(config.load_language(), "en")


class HeaderRenderTest(unittest.TestCase):
    """The persistent device header in BatteryWindow (I/O TRAY_STATE/HAPPY).

    Regression: `update_header` feeds DPI/rate VALUES while `_render_header`
    writes the label WIDGETS — these must be distinct attributes. The original
    bug stored the value into the same attribute as the label, so a single
    `update_header` left a non-widget behind and the next render crashed on
    `set_text`. This test pins the fixed separation.
    """

    def _window(self):
        w = gui.BatteryWindow.__new__(gui.BatteryWindow)
        w._lang = "en"
        w._known = True
        w._last = (82, False, 0)  # (percent, charging, mode)
        w._header_dpi = None
        w._header_rate = None
        w._header_batt = _stub_label()
        w._header_mode = _stub_label()
        w._header_dpi_label = _stub_label()
        w._header_rate_label = _stub_label()
        return w

    def test_update_header_render_values_on_labels(self):
        from src.rapoo_vt7 import gui

        w = self._window()
        w.update_header(dpi=5000, rate=8000)
        # Values stay as ints (separate from labels)...
        self.assertIsInstance(w._header_dpi, int)
        self.assertIsInstance(w._header_rate, int)
        # ...and the render writes to the labels without crashing.
        self.assertEqual(w._header_dpi_label.text, "DPI 5000")
        self.assertEqual(w._header_rate_label.text, "8000 Hz")

    def test_update_header_none_keeps_dash(self):
        from src.rapoo_vt7 import gui

        w = self._window()
        w.update_header(dpi=None, rate=None)
        self.assertEqual(w._header_dpi_label.text, "--")
        self.assertEqual(w._header_rate_label.text, "--")

    def test_render_header_degraded_when_unknown(self):
        from src.rapoo_vt7 import gui
        from src.rapoo_vt7 import i18n

        w = self._window()
        w._known = False
        w._last = None
        gui.BatteryWindow._render_header(w)
        # Unknown battery renders the localized unknown label; mode "--".
        self.assertEqual(
            w._header_batt.text, i18n.LANGS["en"]["battery_unknown"]
        )
        self.assertEqual(w._header_mode.text, "--")
        self.assertEqual(w._header_dpi_label.text, "--")
        self.assertEqual(w._header_rate_label.text, "--")

    def test_render_header_is_noop_on_partial_new_window(self):
        """`__new__`-based windows without a header don't crash in `_render`."""
        from src.rapoo_vt7 import gui

        w = gui.BatteryWindow.__new__(gui.BatteryWindow)
        w._lang = "en"
        w._known = True
        w._last = (50, False, 1)
        # No header widgets built -> _render_header must no-op.
        gui.BatteryWindow._render_header(w)  # must not raise


class TrayDpiRowTest(unittest.TestCase):
    """Tray informational DPI/rate row (I/O TRAY_STATE)."""

    def _tray(self):
        from src.rapoo_vt7 import tray

        t = tray.Tray.__new__(tray.Tray)
        t._lang = "en"
        t._dpi = None
        t._rate = None
        t.dpi_item = _Hover()
        t.status_item = _Hover()
        t.detail_item = _Hover()
        return t

    def test_set_dpi_renders_dpi_only(self):
        from src.rapoo_vt7 import tray

        t = self._tray()
        t.set_dpi(5000, None)
        self.assertIn("5000", t.dpi_item.text)

    def test_set_dpi_rate_renders_both(self):
        from src.rapoo_vt7 import tray

        t = self._tray()
        t.set_dpi(5000, 8000)
        self.assertIn("5000", t.dpi_item.text)
        self.assertIn("8000", t.dpi_item.text)


class _StyleCtx:
    def __init__(self):
        self.classes = set()

    def add_class(self, c):
        self.classes.add(c)

    def remove_class(self, c):
        self.classes.discard(c)

    def has_class(self, c):
        return c in self.classes


class BuildCssTest(unittest.TestCase):
    """theme.build_css token injection (I/O THEME_SET render contract)."""

    def test_build_css_injects_light_tokens(self):
        css = theme.build_css("light")
        self.assertIn("@define-color theme_bg #f4f5f7;", css)
        self.assertIn("@define-color theme_card_bg #ffffff;", css)
        self.assertIn("@define-color theme_accent #2c8e3a;", css)
        # base stylesheet references the injected token names.
        self.assertIn("@theme_bg", css)

    def test_build_css_injects_dark_tokens(self):
        css = theme.build_css("dark")
        self.assertIn("@define-color theme_bg #1b1c1f;", css)
        self.assertIn("#4cc25a", css)  # dark accent
        self.assertIn("@theme_bg", css)

    def test_build_css_themes_differ(self):
        self.assertNotEqual(theme.build_css("light"), theme.build_css("dark"))


class ApplyThemeTest(unittest.TestCase):
    """theme.apply_theme class toggling + idempotence (I/O THEME_SET)."""

    def _root(self):
        self.ctx = _StyleCtx()
        return NS(get_style_context=lambda: self.ctx)

    def test_apply_theme_dark_toggles_class(self):
        root = self._root()
        theme.apply_theme(root, "dark")
        self.assertTrue(self.ctx.has_class("theme-dark"))
        self.assertFalse(self.ctx.has_class("theme-light"))

    def test_apply_theme_light_switches_and_is_idempotent(self):
        root = self._root()
        self.ctx.add_class("theme-dark")
        theme.apply_theme(root, "light")
        self.assertTrue(self.ctx.has_class("theme-light"))
        self.assertFalse(self.ctx.has_class("theme-dark"))
        # Re-applying light leaves exactly one class (no stray accumulation).
        theme.apply_theme(root, "light")
        self.assertEqual(self.ctx.classes, {"theme-light"})


class ThemeChangedHandlerTest(unittest.TestCase):
    """BatteryWindow._on_theme_changed: applies the theme class + fires the
    callback, and the P1 guard (same-code rebuild) must NOT re-apply/re-save."""

    def _combo(self, code):
        return NS(get_active_id=lambda: code)

    def _window(self):
        w = gui.BatteryWindow.__new__(gui.BatteryWindow)
        self.ctx = _StyleCtx()
        w._theme = "system"
        w.calls = []
        w._on_theme_change = lambda c: w.calls.append(c)
        w._win = NS(get_style_context=lambda: self.ctx)
        return w

    def test_selecting_new_theme_applies_and_notifies(self):
        w = self._window()
        gui.BatteryWindow._on_theme_changed(w, self._combo("dark"))
        self.assertTrue(self.ctx.has_class("theme-dark"))
        self.assertEqual(w._theme, "dark")
        self.assertEqual(w.calls, ["dark"])

    def test_same_theme_is_noop(self):
        # P1: language-switch combo rebuild fires "changed" with the current
        # code; the handler must short-circuit (no apply, no save, no notify).
        w = self._window()
        w._theme = "light"
        gui.BatteryWindow._on_theme_changed(w, self._combo("light"))
        self.assertFalse(self.ctx.has_class("theme-dark"))
        self.assertFalse(self.ctx.has_class("theme-light"))
        self.assertEqual(w.calls, [])


class SystemThemeWatchTest(unittest.TestCase):
    """Live OS light/dark tracking for the "system" theme (I/O THEME_SET).

    `RapooApp._start_system_theme_watch` sets up a Gio.Settings watch and
    `_on_system_scheme_change` re-renders only when the user theme is "system".
    Because the methods may be exercised on `__new__`-based app stubs, every
    attribute access is guarded — the tests pin that the guard never raises.
    """

    def _app(self, theme_code="system"):
        from src.rapoo_vt7 import main as main_mod

        app = main_mod.RapooApp.__new__(main_mod.RapooApp)
        app._scheme_settings = None
        app._window = NS(_theme=theme_code)
        app._retheme_calls = []
        app._retheme = lambda code: app._retheme_calls.append(code)
        return app

    def test_start_watch_connects_color_scheme(self):
        from src.rapoo_vt7 import main as main_mod

        app = self._app()
        settings = NS(connect=lambda *a: None, list_keys=lambda: ["color-scheme"])
        with mock.patch.object(main_mod.Gio, "Settings") as gs:
            gs.new.return_value = settings
            main_mod.RapooApp._start_system_theme_watch(app)
        self.assertIs(app._scheme_settings, settings)

    def test_start_watch_no_schema_is_noop(self):
        from src.rapoo_vt7 import main as main_mod

        app = self._app()
        with mock.patch.object(main_mod.Gio, "Settings") as gs:
            gs.new.side_effect = Exception("no schema")
            main_mod.RapooApp._start_system_theme_watch(app)
        self.assertIsNone(app._scheme_settings)

    def test_scheme_change_rethemes_when_system(self):
        from src.rapoo_vt7 import main as main_mod

        app = self._app("system")
        main_mod.RapooApp._on_system_scheme_change(app)
        self.assertEqual(app._retheme_calls, ["system"])

    def test_scheme_change_noop_when_not_system(self):
        from src.rapoo_vt7 import main as main_mod

        for code in ("light", "dark"):
            app = self._app(code)
            main_mod.RapooApp._on_system_scheme_change(app)
            self.assertEqual(app._retheme_calls, [])

    def test_scheme_change_noop_when_no_window(self):
        from src.rapoo_vt7 import main as main_mod

        app = self._app()
        app._window = None
        main_mod.RapooApp._on_system_scheme_change(app)  # must not raise
        self.assertEqual(app._retheme_calls, [])


class StyleWindowTest(unittest.TestCase):
    """theme.style_window: adds window-root + the theme branch (I/O THEME_SET).

    `style_window` is the single entry point used by both the main window and
    secondary dialogs, so they all render from the same token sheet.
    """

    def _root(self):
        self.ctx = _StyleCtx()
        return NS(get_style_context=lambda: self.ctx)

    def test_style_window_adds_window_root_and_theme_class(self):
        root = self._root()
        theme.style_window(root, "dark")
        self.assertIn("window-root", self.ctx.classes)
        self.assertIn("theme-dark", self.ctx.classes)

    def test_style_window_light_switches(self):
        root = self._root()
        self.ctx.add_class("theme-dark")
        theme.style_window(root, "light")
        self.assertIn("window-root", self.ctx.classes)
        self.assertIn("theme-light", self.ctx.classes)
        self.assertNotIn("theme-dark", self.ctx.classes)

    def test_style_window_is_idempotent(self):
        root = self._root()
        theme.style_window(root, "dark")
        theme.style_window(root, "dark")
        self.assertEqual(self.ctx.classes, {"window-root", "theme-dark"})


class CardWrapLayoutTest(unittest.TestCase):
    """Structural regression for the card wrapper rebinding bug.

    `_card_wrap` returns a ``Gtk.Frame`` (which has no ``pack_start``). If a
    page vbox is rebound to the frame BEFORE the section builder keeps packing
    into it, ``BatteryWindow.__init__`` crashes with ``AttributeError:
    'Frame' object has no attribute 'pack_start'`` — the window never opens,
    and ``do_startup`` leaves ``_window``/``_monitor`` unset, so "Sair" also
    fails. This reads the source to pin the fix: cards are applied inline in
    ``append_page``/scroll-add, never by rebinding the ``pageN`` vbox.
    """

    def _init_src(self):
        path = os.path.join(os.path.dirname(__file__), "..", "src",
                            "rapoo_vt7", "gui.py")
        with open(path) as fh:
            return fh.read()

    def test_pages_not_rebound_to_card(self):
        src = self._init_src()
        for var in ("page1", "page2", "page3", "page4", "page5", "page6"):
            self.assertNotIn(
                f"{var} = self._card_wrap({var})", src,
                f"{var} must stay the inner vbox; wrap inline instead",
            )

    def test_cards_applied_inline_when_attached(self):
        src = self._init_src()
        # The fix wraps inline at attach time for the direct pages (notebook)
        # and the scrollable pages (scroll.add).
        self.assertIn("append_page(self._card_wrap(page1)", src)
        self.assertIn("append_page(self._card_wrap(page2)", src)
        self.assertIn("add(self._card_wrap(page3))", src)
        self.assertIn("add(self._card_wrap(page4))", src)
        self.assertIn("add(self._card_wrap(page5))", src)
        self.assertIn("add(self._card_wrap(page6))", src)


if __name__ == "__main__":
    unittest.main()

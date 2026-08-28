import os
import time

import gi

gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Gtk", "3.0")
from gi.repository import AyatanaAppIndicator3, Gtk

from .icons import ICON_PREFIX, UNKNOWN_NAME
from . import i18n


class Tray:
    def __init__(
        self,
        icon_dir,
        on_quit=None,
        on_refresh=None,
        on_open_window=None,
    ):
        self._icon_dir = icon_dir
        self._on_quit = on_quit
        self._on_refresh = on_refresh
        self._on_open_window = on_open_window
        self._lang = "pt_BR"
        self._known = False
        self._asleep = False
        self._last = None
        self._dpi = None
        self._rate = None

        self.indicator = AyatanaAppIndicator3.Indicator.new(
            "rapoo-vt7-battery",
            self._unknown_path(),
            AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_icon_full(self._unknown_path(), "Rapoo VT7")

        self.menu = Gtk.Menu()

        self.item_open = Gtk.MenuItem(label=self._t("open_window"))
        self.item_open.connect("activate", lambda *_: self._open_window())
        self.menu.append(self.item_open)
        self.menu.append(Gtk.SeparatorMenuItem())

        self.status_item = Gtk.MenuItem(label=self._t("battery_unknown"))
        self.status_item.set_sensitive(False)
        self.status_item.get_style_context().add_class("tray-muted")
        self.menu.append(self.status_item)

        self.detail_item = Gtk.MenuItem(label="")
        self.detail_item.set_sensitive(False)
        self.detail_item.get_style_context().add_class("tray-muted")
        self.menu.append(self.detail_item)

        self.dpi_item = Gtk.MenuItem(label="")
        self.dpi_item.set_sensitive(False)
        self.dpi_item.get_style_context().add_class("tray-muted")
        self.menu.append(self.dpi_item)
        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_refresh = Gtk.MenuItem(label=self._t("refresh_now"))
        self.item_refresh.connect("activate", lambda *_: self._refresh())
        self.menu.append(self.item_refresh)
        self.menu.append(Gtk.SeparatorMenuItem())

        self.item_quit = Gtk.MenuItem(label=self._t("quit"))
        self.item_quit.connect("activate", lambda *_: self._quit())
        self.menu.append(self.item_quit)
        self.menu.show_all()

        self.indicator.set_menu(self.menu)

    def _icon_path(self, percent, charging=False):
        return os.path.join(
            self._icon_dir, f"{ICON_PREFIX}{int(percent):03d}{'_chg' if charging else ''}.png"
        )

    def _unknown_path(self):
        return os.path.join(self._icon_dir, f"{UNKNOWN_NAME}.png")

    def _t(self, key):
        return i18n.LANGS[self._lang][key]

    def set_language(self, lang):
        if lang in i18n.LANGS and lang != self._lang:
            self._lang = lang
            self._render()

    def update(self, percent, charging=False, mode=None):
        self._known = True
        self._asleep = False
        self._last = (percent, charging, mode)
        self.indicator.set_icon_full(
            self._icon_path(percent, charging), f"{percent}%"
        )
        self._render()

    def _render(self):
        t = i18n.LANGS[self._lang]
        self.item_open.set_label(t["open_window"])
        self.item_refresh.set_label(t["refresh_now"])
        self.item_quit.set_label(t["quit"])
        if not self._known:
            self.status_item.set_label(t["battery_unknown"])
            self.detail_item.set_label(t["connect_device"])
            return
        percent, charging, mode = self._last
        label = t["battery"].format(pct=percent)
        if self._asleep:
            label = t["asleep"].format(pct=percent)
        elif charging:
            label += " " + t["charging"]
        self.status_item.set_label(label)
        parts = []
        if mode in (0, 1, 2):
            parts.append({0: "2.4G", 1: "Bluetooth", 2: "USB"}[mode])
        parts.append(t["last_read"].format(time=time.strftime("%H:%M")))
        self.detail_item.set_label(" · ".join(parts))
        self._render_dpi()

    def _render_dpi(self):
        dpi, rate = self._dpi, self._rate
        if dpi is not None and rate is not None:
            self.dpi_item.set_label(
                self._t("tray_dpi").format(x=dpi, rate=rate)
            )
        elif dpi is not None:
            self.dpi_item.set_label(self._t("header_dpi").format(x=dpi))
        else:
            self.dpi_item.set_label("--")

    def set_dpi(self, dpi, rate=None):
        """Additive (non-frozen) setter feeding the current DPI value + polling
        rate (Hz) into the tray's informational DPI row. `rate=None` keeps the
        row as DPI-only."""
        self._dpi = dpi
        self._rate = rate
        self._render_dpi()

    def set_unknown(self):
        self._known = False
        self.indicator.set_icon_full(
            self._unknown_path(), self._t("unknown_tooltip")
        )
        self._render()

    def set_asleep(self):
        if self._asleep or not self._known:
            return
        self._asleep = True
        self._render()

    def _open_window(self):
        if self._on_open_window:
            self._on_open_window()

    def _refresh(self):
        if self._on_refresh:
            self._on_refresh()

    def _quit(self):
        if self._on_quit:
            self._on_quit()

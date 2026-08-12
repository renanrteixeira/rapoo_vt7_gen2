import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import GLib, Gio, Gtk, Notify

from .battery import BatteryMonitor
from .config import load_language, save_language
from . import dpi, parameters, performance as perf
from .gui import BatteryWindow
from .i18n import LANGS
from .icons import DEFAULT_ICON_DIR, render_all
from .tray import Tray

ICON_DIR = DEFAULT_ICON_DIR

LOW_BATTERY_THRESHOLDS = (20, 10)

APP_ID = "io.rapoo.vt7"


def _perf_slot_from_monitor(monitor):
    """Return the active performance slot from the monitor.

    The active polling-rate slot is derived from report 7's `rpt_usb` byte.
    If `rpt_usb` is unavailable, fall back directly to the default slot.
    The rate code mapping is already validated in `perf.rate_index_from_code()`.
    """
    rpt = getattr(monitor, "_rpt_usb", None)
    if rpt is None:
        return perf.SLOT_DEFAULT
    return perf.rate_index_from_code(rpt)


class LowBatteryAlerts:
    def __init__(self):
        self._notified = set()

    def threshold(self, percent):
        """Returns the threshold just reached (None if nothing new)."""
        for th in LOW_BATTERY_THRESHOLDS:
            if percent <= th:
                if th not in self._notified:
                    self._notified.add(th)
                    return th
            else:
                self._notified.discard(th)
        return None


class RapooApp(Gtk.Application):
    def __init__(self, application_id=APP_ID, hidden=False):
        super().__init__(application_id=application_id)
        self._hidden_launch = hidden
        self._alerts = LowBatteryAlerts()
        self._dpi_loaded = False
        self._dpi_reading = False
        self._perf_loaded = False
        self._params_loaded = False
        self._last_report_dpi = None
        self._app_report = None  # last (gear, x) written by the app — report
        # echo of an app write is not re-notified
        # --hidden starts only in the systray (used by autostart). The short
        # name is 0 so it doesn't conflict with GLib's help.
        self.add_main_option(
            "hidden",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Start hidden (tray only)",
            None,
        )

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Notify.init("rapoo-vt7-battery")
        icon_dir = render_all(ICON_DIR)
        lang = load_language()

        def on_lang_change(code):
            self._tray.set_language(code)
            save_language(code)

        self._tray = Tray(
            icon_dir,
            on_quit=self._quit,
            on_refresh=self._refresh_now,
            on_open_window=self._show_window,
        )
        self._tray.set_unknown()
        self._tray.set_language(lang)
        self._window = BatteryWindow(
            lang=lang,
            on_lang_change=on_lang_change,
            application=self,
            on_switch_gear=self._on_switch_gear,
            on_add_gear=self._on_add_gear,
            on_delete_gear=self._on_delete_gear,
            on_set_value=self._on_set_value,
            on_set_perf=self._on_set_perf,
            on_set_rf=self._on_set_rf,
            on_set_param=self._on_set_param,
            on_set_rate=self._on_set_rate,
            on_set_param_choice=self._on_set_param_choice,
        )

        self._monitor = BatteryMonitor(
            on_update=self._on_update,
            on_state=self._on_state,
            on_report=self._on_report,
        )
        self._monitor.start()

    # --- monitor callbacks (battery thread -> idle_add on GTK) ---

    def _on_report(self, gear, x, y):
        """Called from the monitor thread on every passive report 7. When the
        reported DPI changed (physical button press or app write echo) the
        config is re-read; a physical change is notified to the user."""
        current = (gear, x, y)
        if current != self._last_report_dpi:
            self._last_report_dpi = current
            print("[dpi] report7 gear=%d x=%d y=%d" % current)
            if (gear, x) == self._app_report:
                # Echo of an app write (switch/edit): the app already
                # notified, so just clear the marker.
                self._app_report = None
            else:
                GLib.idle_add(self._notify_report_dpi, gear, x)
            GLib.idle_add(self._refresh_dpi)

    def _notify_report_dpi(self, gear, x):
        lang = LANGS[self._window._lang]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["dpi_changed"].format(x=x, n=gear + 1),
            "dialog-information",
        ).show()

    def _on_update(self, percent, charging=False, mode=None):
        GLib.idle_add(self._apply_update, percent, charging, mode)

    def _apply_update(self, percent, charging, mode):
        self._tray.update(percent, charging=charging, mode=mode)
        self._window.update(percent, charging=charging, mode=mode)
        if not self._dpi_loaded:
            self._dpi_loaded = True
            self._refresh_dpi()
        if not self._perf_loaded:
            self._perf_loaded = True
            self._refresh_perf()
        if not self._params_loaded:
            self._params_loaded = True
            self._refresh_params()
        th = self._alerts.threshold(percent)
        if th is not None:
            lang = LANGS[self._window._lang]
            Notify.Notification.new(
                "Rapoo VT7",
                lang["low_battery"].format(pct=percent),
                "dialog-warning",
            ).show()

    def _on_state(self, name, **kwargs):
        print(f"[battery] state: {name}", kwargs.get("reason", ""))
        if name == "asleep":
            GLib.idle_add(self._tray.set_asleep)
            GLib.idle_add(self._window.set_asleep)
        elif name in ("connected", "open", "disconnected"):
            # Recovers the DPI tab when it was never loaded (mouse asleep at
            # startup): wakes with the mouse and loads the config.
            GLib.idle_add(self._maybe_refresh_dpi)
            GLib.idle_add(self._maybe_refresh_perf)
            GLib.idle_add(self._maybe_refresh_params)

    # --- menu actions (GTK thread) -> device tasks (monitor thread) ---

    def _refresh_now(self):
        self._monitor.request_refresh()

    def _on_switch_gear(self, gear):
        self._monitor.submit(
            lambda dev: dpi.set_gear(dev, gear),
            on_done=lambda _: GLib.idle_add(self._dpi_switched, gear),
            on_error=self._dpi_error,
            wake=True,
        )

    def _on_add_gear(self):
        """Add button: appends a gear (default 800) to the button cycle."""
        info = self._window.get_dpi_info()
        if info is None:
            return
        self._monitor.submit(
            lambda dev: dpi.add_gear(dev, info),
            on_done=lambda res: GLib.idle_add(self._dpi_list_updated, res, True),
            on_error=self._dpi_error,
            wake=True,
        )

    def _on_delete_gear(self, slot):
        """Trash button: removes a gear from the button cycle, compacting the
        list like the A Hub does."""
        info = self._window.get_dpi_info()
        if info is None:
            return
        self._monitor.submit(
            lambda dev: dpi.delete_gear(dev, info, slot),
            on_done=lambda res: GLib.idle_add(self._dpi_list_updated, res, False),
            on_error=self._dpi_error,
            wake=True,
        )

    def _on_set_value(self, gear, value):
        """Spin change: DPI value only — writes X (and Y = X) for the gear.
        The list is re-sorted on the device and the tab rebuilds in the new
        order; the current DPI keeps its value."""
        info = self._window.get_dpi_info()
        if info is None:
            return
        self._monitor.submit(
            lambda dev: dpi.set_value(dev, info, gear, value),
            on_done=lambda res: GLib.idle_add(self._dpi_edited, res),
            on_error=self._dpi_error,
            wake=True,
        )

    def _dpi_switched(self, gear):
        """Runs on the GTK thread after a gear switch. Notifies the user."""
        info = self._window.get_dpi_info()
        if info is not None:
            self._app_report = (gear, info["x"][gear])
            lang = LANGS[self._window._lang]
            Notify.Notification.new(
                "Rapoo VT7",
                lang["dpi_changed"].format(x=info["x"][gear], n=gear + 1),
                "dialog-information",
            ).show()
        self._refresh_dpi()

    def _dpi_edited(self, result):
        """Runs on the GTK thread after a gear value edit. Only the current
        gear (its radio is marked) is applied — other edits just store the
        value, so the notification differs. Marks the report-7 echo (current
        gear + its value) so it is not re-notified."""
        self._app_report = (result["current"], result["cur_x"])
        lang = LANGS[self._window._lang]
        key = "dpi_edited" if result["applied"] else "dpi_stored"
        Notify.Notification.new(
            "Rapoo VT7",
            lang[key].format(n=result["gear"] + 1, x=result["x"]),
            "dialog-information",
        ).show()
        self._refresh_dpi()

    def _dpi_list_updated(self, result, added):
        """Runs on the GTK thread after a gear add/delete. The list may have
        been re-sorted (add): the notification uses the added value and the
        report-7 echo is marked with the current gear + its value."""
        lang = LANGS[self._window._lang]
        cur = result.get("current")
        if added:
            message = lang["dpi_added"].format(x=result["x"])
            self._app_report = (
                (cur, result["cur_x"]) if isinstance(cur, int) else None
            )
        else:
            message = lang["dpi_deleted"]
            if isinstance(cur, int) and 0 <= cur < len(result["list"]):
                self._app_report = (cur, result["list"][cur])
            else:
                self._app_report = None
        Notify.Notification.new(
            "Rapoo VT7",
            message,
            "dialog-information",
        ).show()
        self._refresh_dpi()

    def _current_perf_slot(self):
        """Slot index (0..6) of the active polling rate."""
        return _perf_slot_from_monitor(self._monitor)

    def _on_set_perf(self, mode):
        """Performance radio toggled: set the mode for the active rate slot."""
        self._monitor.submit(
            lambda dev: perf.set_mode(dev, self._current_perf_slot(), mode),
            on_done=lambda res: GLib.idle_add(self._perf_changed, res),
            on_error=self._perf_error,
            wake=True,
        )

    def _on_set_rf(self, field, enabled):
        """RF checkbox toggled: masked write to the shared 0x08D8 byte.

        `field` is "rf" (RF strengthen) or "lowpow" (low-battery warning). The
        write preserves the unrelated bits of the shared byte and is confirmed
        by re-reading; a mismatch surfaces an error instead of accepting the
        change. User-initiated: attempted even while the mouse is asleep.
        """
        if field == "lowpow":
            fn = lambda dev: perf.write_low_power_warn(dev, enabled)
        else:
            fn = lambda dev: perf.write_rf_strengthen(dev, enabled)
        self._monitor.submit(
            fn,
            on_done=lambda res: GLib.idle_add(self._rf_changed, res, field),
            on_error=self._perf_error,
            wake=True,
        )

    def _on_set_rate(self, hz):
        """Polling-rate radio toggled: writes the rateCode of `hz` to
        0x0880 (verified by re-reading). The active slot changes with it,
        so the perf/RF read is re-run for the new slot."""
        self._monitor.submit(
            lambda dev: perf.set_rate(dev, hz),
            on_done=lambda res: GLib.idle_add(self._rate_changed, res),
            on_error=self._perf_error,
            wake=True,
        )

    def _rate_changed(self, result):
        """Runs on the GTK thread after a rate write; notifies and re-reads
        the Desempenho state for the new active slot."""
        lang = LANGS[self._window._lang]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["perf_rate_changed"].format(hz=result["hz"]),
            "dialog-information",
        ).show()
        self._refresh_perf(slot=result["slot"])

    def _rf_changed(self, state, field):
        """Runs on the GTK thread after an RF write; refreshes the perf/RF tab."""
        lang = LANGS[self._window._lang]
        if field == "lowpow":
            key = (
                "rf_low_on"
                if state["low_power_warn_switch"]
                else "rf_low_off"
            )
        else:
            key = "rf_full" if state["rf_strengthen_switch"] else "rf_adaptive"
        Notify.Notification.new(
            "Rapoo VT7",
            lang["rf_changed"].format(rf=lang[key]),
            "dialog-information",
        ).show()
        self._refresh_perf()

    def _perf_error(self, exc):
        GLib.idle_add(self._window.set_perf_error, str(exc))

    def _on_set_param(self, name, enabled):
        """§C toggle changed: write the confirmed bool byte, verified by
        re-reading (a mismatch rejects the change). User-initiated: attempted
        even while the mouse is asleep."""
        self._monitor.submit(
            lambda dev: parameters.set_param(dev, name, enabled),
            on_done=lambda res: GLib.idle_add(self._param_changed, res),
            on_error=self._param_error,
            wake=True,
        )

    def _on_set_param_choice(self, name, value):
        """§C selectable parameter changed: write one of its confirmed choice
        values, verified by re-reading (guesswork values are refused inside
        `set_param_choice`). User-initiated: attempted even while asleep."""
        self._monitor.submit(
            lambda dev: parameters.set_param_choice(dev, name, value),
            on_done=lambda res: GLib.idle_add(self._param_changed, res),
            on_error=self._param_error,
            wake=True,
        )

    def _param_changed(self, state):
        """Runs on the GTK thread after a §C write; notifies + re-reads."""
        lang = LANGS[self._window._lang]
        if state.get("option"):
            shown = parameters.choice_label(state["name"], state["value"])
        else:
            shown = lang["param_on" if state["value"] else "param_off"]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["param_changed"].format(
                name=lang["param_" + state["name"]],
                state=shown,
            ),
            "dialog-information",
        ).show()
        self._refresh_params()

    def _param_error(self, exc):
        GLib.idle_add(self._window.set_params_error, str(exc))

    def _refresh_params(self):
        """Re-reads every §C parameter into the window (per-field errors are
        isolated inside `parameters.read_section`)."""

        def done(info):
            GLib.idle_add(self._window.update_params, info)

        def err(exc):
            GLib.idle_add(self._window.set_params_error, str(exc))

        self._monitor.submit(parameters.read_section, on_done=done, on_error=err)

    def _maybe_refresh_params(self):
        """GTK thread. Re-read the §C section when it is still empty (mouse
        asleep at startup) or still carries per-field errors — the mouse is
        awake now."""
        info = self._window.get_params_info()
        if info is None or info.get("errors"):
            self._refresh_params()

    def _perf_changed(self, result):
        """Runs on the GTK thread after a mode write."""
        lang = LANGS[self._window._lang]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["perf_changed"].format(
                name=lang["perf_mode_%d" % result["mode"]]
            ),
            "dialog-information",
        ).show()
        self._refresh_perf()

    def _refresh_perf(self, slot=None):
        """Re-reads the mode of the active rate slot into the window.

        `slot` is None normally (derived from report 7 `rpt_usb`); after a
        rate change the new slot is passed explicitly so the tab updates
        right away instead of waiting for the next passive report.
        """

        if slot is None:
            slot = self._current_perf_slot()

        def done(info):
            GLib.idle_add(self._window.update_perf, info)

        def err(exc):
            GLib.idle_add(self._window.set_perf_error, str(exc))

        self._monitor.submit(
            lambda dev: perf.read_perf_state(dev, slot),
            on_done=done,
            on_error=err,
        )

    def _maybe_refresh_perf(self):
        """GTK thread. When the perf tab is still empty (mouse asleep at
        startup) re-read the mode — the mouse is awake now."""
        if self._window.get_perf_info() is None:
            self._refresh_perf()

    def _refresh_dpi(self):
        if self._dpi_reading:
            return
        self._dpi_reading = True

        def done(info):
            self._dpi_reading = False
            print(
                "[dpi] refresh gear=%d enable=%d x=%s"
                % (info["gear"], info["enable"], info["x"])
            )
            GLib.idle_add(self._window.update_dpi, info)

        def err(exc):
            self._dpi_reading = False
            GLib.idle_add(self._window.set_dpi_error, str(exc))

        self._monitor.submit(dpi.read_dpi, on_done=done, on_error=err)

    def _dpi_error(self, exc):
        GLib.idle_add(self._window.set_dpi_error, str(exc))

    def _maybe_refresh_dpi(self):
        """GTK thread. When the DPI tab is still empty/erroring (e.g. the
        mouse was asleep at startup) re-read the config — the mouse is awake
        now because this runs on a connected/open/disconnected event."""
        if not self._window.has_dpi():
            self._refresh_dpi()

    # --- Gtk.Application: single instance + relaunch ---

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        if options.contains("hidden"):
            self._hidden_launch = True
        self.activate()
        return 0

    def do_activate(self):
        if self._hidden_launch:
            self._hidden_launch = False
            return
        self._show_window()

    def _show_window(self):
        self._window.show()

    def _quit(self):
        self._monitor.stop()
        Notify.uninit()
        self.quit()


def main():
    hidden = "--hidden" in sys.argv
    app = RapooApp(hidden=hidden)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

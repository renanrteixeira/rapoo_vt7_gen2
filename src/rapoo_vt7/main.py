import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import GLib, Gio, Gtk, Notify

from .battery import BatteryMonitor
from .config import load_language, save_language
from . import buttons, dpi, parameters, performance as perf, system
from .gui import BatteryWindow
from .i18n import LANGS
from .icons import DEFAULT_ICON_DIR, render_all
from .pairing_session import (
    PairingSession,
    ReceiverNotFound,
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
)
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
        self._buttons_loaded = False
        self._last_report_dpi = None
        self._pair_session = None
        self._pair_step = 0
        self._quitting = False
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
            on_set_button=self._on_set_button,
            on_factory_reset=self._on_factory_reset,
            on_read_name=self._refresh_name,
            on_rename=self._on_rename,
            on_start_pairing=self._on_start_pairing,
            on_cancel_pairing=self._on_cancel_pairing,
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
        if not self._buttons_loaded:
            self._buttons_loaded = True
            self._refresh_buttons()
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
            GLib.idle_add(self._maybe_refresh_buttons)

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
        """Performance radio toggled: set the mode for the DISPLAYED slot.

        The slot the window is showing (from the last perf read) is the target
        — not the live monitor `_rpt_usb`, which lags the reported rate after a
        rate change. Only modes available in that slot are accepted.
        """
        info = self._window.get_perf_info()
        if info is not None and isinstance(info.get("slot"), int):
            slot = info["slot"]
        else:
            slot = self._current_perf_slot()
        if not isinstance(mode, int) or mode not in perf.selectable_modes(slot):
            self._perf_error(
                ValueError("mode %r not available at %d Hz" % (mode, perf.RATE_HZ[slot]))
            )
            return
        self._monitor.submit(
            lambda dev: perf.set_mode(dev, slot, mode),
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
        if field not in ("rf", "lowpow"):
            self._perf_error(ValueError("unknown RF field %r" % field))
            return
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
                param=lang["param_" + state["name"]],
                state=shown,
            ),
            "dialog-information",
        ).show()
        self._refresh_params()

    def _param_error(self, exc):
        GLib.idle_add(self._window.set_params_error, str(exc))

    def _on_set_button(self, name, fid):
        """Button-combo changed: assign a confirmed function method to the
        button, verified by re-reading (a mismatch rejects the change).
        User-initiated: attempted even while the mouse is asleep. The ≥1
        left-click rule is enforced twice: before submitting (last-known
        state, fast refusal) and inside `buttons.set_function` (live reads,
        authoritative)."""
        if fid not in buttons.METHODS:
            self._button_error(buttons.UnknownFunctionError(fid))
            return
        info = self._window.get_buttons_info()
        if info is not None and not info.get("errors"):
            state = info["buttons"].get(name)
            if state is not None and buttons.is_left_click(state["method"]):
                method = buttons.METHODS[fid]
                if not buttons.is_left_click(method):
                    others_left = any(
                        other != name
                        and other in info["buttons"]
                        and buttons.is_left_click(info["buttons"][other]["method"])
                        for other, _offset in buttons.BUTTONS
                    )
                    if not others_left:
                        self._button_error(
                            ValueError(
                                LANGS[self._window._lang]["button_no_left"]
                            )
                        )
                        return
        self._monitor.submit(
            lambda dev: buttons.set_function(dev, name, fid),
            on_done=lambda res: GLib.idle_add(self._button_changed, res),
            on_error=self._button_error,
            wake=True,
        )

    def _button_changed(self, state):
        """Runs on the GTK thread after a button write; notifies + re-reads."""
        lang = LANGS[self._window._lang]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["button_changed"].format(
                button=lang["btn_" + state["name"]],
                fn=lang["fn_" + state["fn"]],
            ),
            "dialog-information",
        ).show()
        self._refresh_buttons()

    def _button_error(self, exc):
        lang = LANGS[self._window._lang]
        if isinstance(exc, buttons.NoLeftClickError):
            msg = lang["button_no_left"]
        elif isinstance(exc, buttons.UnknownFunctionError):
            msg = lang["button_unknown_fn"].format(fn=exc.args[0])
        else:
            msg = str(exc)
        GLib.idle_add(self._window.set_buttons_error, msg)

    # --- System: factory reset (Phase 5, destructive + user-confirmed) ---

    def _on_factory_reset(self):
        """Factory-reset button confirmed: sends 0xAD via submit(wake=True).

        The confirmation dialog lives in the window (blocking, localized);
        this handler only runs after the user clicked OK. The command is
        attempted even if the mouse just fell asleep — a device timeout flips
        the monitor back to asleep and surfaces the localized error.
        """
        self._monitor.submit(
            system.factory_reset,
            on_done=lambda res: GLib.idle_add(self._factory_reset_done, res),
            on_error=self._factory_reset_error,
            wake=True,
        )

    def _factory_reset_done(self, result):
        """Runs on the GTK thread after a verified reset. The device returned
        to factory defaults, so every config tab is stale: re-read them all —
        including the device name (the reset restores "CFG1", which the entry
        no longer shows)."""
        lang = LANGS[self._window._lang]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["factory_reset_success"],
            "dialog-information",
        ).show()
        self._window.set_system_message(
            lang["factory_reset_success"], False, op="system"
        )
        self._refresh_dpi()
        self._refresh_perf()
        self._refresh_params()
        self._refresh_buttons()
        self._refresh_name()

    def _factory_reset_error(self, exc):
        """Runs on the monitor thread; hops to GTK to surface the error."""
        lang = LANGS[self._window._lang]
        if isinstance(exc, system.FactoryResetAckError):
            msg = lang["factory_reset_ack_error"]
        elif isinstance(exc, system.FactoryResetVerifyError):
            msg = lang["factory_reset_verify_error"]
        else:
            msg = str(exc)
        GLib.idle_add(self._window.set_system_message, msg, True, "system")

    # --- System: device name (read on tab open, rename with verified write) ---

    def _refresh_name(self):
        """Reads the device name into the System tab (passive read, no wake).

        Runs on the System tab open (window switch-page). A sleeping mouse is
        surfaced as a localized read error in the tab status — the app never
        wakes the mouse for a background read, and a passive error never lifts
        an in-flight rename/reset busy flag (op=None).
        """

        def done(name):
            GLib.idle_add(self._window.update_device_name, name)

        def err(exc):
            lang = LANGS[self._window._lang]
            msg = lang["name_read_error"].format(error=str(exc))
            GLib.idle_add(self._window.set_system_message, msg, True, None)

        self._monitor.submit(system.read_device_name, on_done=done, on_error=err)

    def _on_rename(self, text):
        """Rename button: writes the device name via submit(wake=True).

        `system.encode_name` refuses blank / >16-byte / embedded-NUL input
        BEFORE the submit (fast, localized refusal — no device access), matching
        the A Hub `renameConfig` byte rule. The write itself is attempted even
        if the mouse just fell asleep; a device timeout flips the monitor back
        to asleep and surfaces the error.
        """
        try:
            system.encode_name(text)
        except system.DeviceNameError as exc:
            self._rename_error(exc)
            return
        self._monitor.submit(
            lambda dev: system.write_device_name(dev, text),
            on_done=lambda res: GLib.idle_add(self._rename_done, res),
            on_error=self._rename_error,
            wake=True,
        )

    def _rename_done(self, name):
        """Runs on the GTK thread after a verified rename; shows the readback."""
        lang = LANGS[self._window._lang]
        self._window.update_device_name(name)
        self._window.set_system_message(
            lang["name_success"].format(name=name), False, op="name"
        )

    def _rename_error(self, exc):
        """Runs on the monitor thread; hops to GTK to surface the error.

        A verify mismatch additionally re-reads the name so the entry shows
        what the mouse actually stored (not the unverified typed text).
        """
        lang = LANGS[self._window._lang]
        if isinstance(exc, system.NameTooLongError):
            msg = lang["name_too_long"]
        elif isinstance(exc, system.NameEmptyError):
            msg = lang["name_empty"]
        elif isinstance(exc, system.NameVerifyError):
            msg = lang["name_verify_error"]
            GLib.idle_add(self._refresh_name)
        else:
            msg = str(exc)
        GLib.idle_add(self._window.set_system_message, msg, True, "name")

    # --- System: receiver pairing (story 5-4, own thread + own fd) ---

    def _on_start_pairing(self):
        """Start button confirmed: launches the pairing session on its own
        daemon thread. The session opens its OWN receiver fd (prefix 0xA5),
        so the monitor is never touched; callbacks hop to the GTK thread via
        idle_add. The window already holds the busy guard. The monitor is put
        in quiet mode for the session duration (F3): it must not send 0xAA
        whose ACK the session's 0xA7 poll could misread as a match result."""
        if self._pair_session is not None and self._pair_session.is_running:
            return
        self._pair_step = 0
        self._monitor.set_quiet(True)
        session = PairingSession(
            on_step=self._on_pair_step,
            on_result=self._on_pair_result,
        )
        self._pair_session = session
        session.start()

    def _on_cancel_pairing(self):
        """Stop button clicked: requests an early end of the matching loop.
        The session emits a cancelled result that releases the window busy."""
        if self._pair_session is not None:
            self._pair_session.cancel()

    def _on_pair_step(self, n):
        if self._quitting:
            return
        self._pair_step = n
        GLib.idle_add(self._window.update_pairing_state, n, None, None)

    def _on_pair_result(self, status, message):
        if self._quitting:
            return
        GLib.idle_add(self._apply_pair_result, status, message)

    def _apply_pair_result(self, status, message):
        """GTK thread. Terminal session result: localizes it, updates the
        window (releases the busy guard), lifts the monitor's quiet mode (F3)
        and shows a notification. Dropped silently while the app is quitting
        (widgets may be gone)."""
        if self._quitting:
            return
        self._monitor.set_quiet(False)
        lang = LANGS[self._window._lang]
        icon = None
        if status == STATUS_SUCCESS:
            msg = lang["pairing_success"]
            icon = "dialog-information"
        elif status == STATUS_FAILED:
            msg = lang["pairing_failed"]
            icon = "dialog-warning"
        elif status == STATUS_TIMEOUT:
            msg = lang["pairing_timeout"]
            icon = "dialog-warning"
        elif status == STATUS_CANCELLED:
            msg = lang["pairing_cancelled"]
        else:
            if isinstance(message, ReceiverNotFound):
                msg = lang["pairing_receiver_not_found"]
            else:
                msg = lang["pairing_error"].format(error=str(message))
            icon = "dialog-error"
        self._window.update_pairing_state(self._pair_step, status, msg)
        if icon is not None:
            Notify.Notification.new("Rapoo VT7", msg, icon).show()

    def _refresh_buttons(self):
        def done(info):
            GLib.idle_add(self._window.update_buttons, info)

        def err(exc):
            GLib.idle_add(self._window.set_buttons_error, str(exc))

        self._monitor.submit(buttons.read_section, on_done=done, on_error=err)

    def _maybe_refresh_buttons(self):
        """GTK thread. Re-read the buttons section when it is not in a healthy
        loaded state: empty (mouse asleep at startup), in a section-level
        error (`has_buttons` covers both), or carrying per-field errors. Runs
        on connected/open events, so by then the mouse is awake."""
        if not self._window.has_buttons():
            self._refresh_buttons()
            return
        info = self._window.get_buttons_info()
        if info is not None and info.get("errors"):
            self._refresh_buttons()

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
        mode = result["mode"]
        if isinstance(mode, int) and 0 <= mode < perf.PERF_MODE_COUNT:
            mode_name = lang["perf_mode_%d" % mode]
        else:
            mode_name = lang["perf_mode_unknown"]
        Notify.Notification.new(
            "Rapoo VT7",
            lang["perf_changed"].format(name=mode_name),
            "dialog-information",
        ).show()
        # Re-read using the slot that was actually written (not the live
        # monitor `_rpt_usb`, which lags) so the tab stays in sync.
        self._refresh_perf(slot=result["slot"])

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
        startup) or an isolated RF read failed, re-read — the mouse is awake
        now and the RF state was never shown."""
        info = self._window.get_perf_info()
        if info is None or info.get("rf_error"):
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
        self._quitting = True
        if self._pair_session is not None:
            self._pair_session.cancel()
        self._monitor.set_quiet(False)
        self._monitor.stop()
        Notify.uninit()
        self.quit()


def main():
    hidden = "--hidden" in sys.argv
    app = RapooApp(hidden=hidden)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

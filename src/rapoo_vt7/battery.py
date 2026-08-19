import queue
import threading
import time

from .device import RapooDevice, DeviceNotFound, DeviceOpenError, CommandTimeout
from . import i18n, protocol
from .protocol import (
    BATTERY_STATUS_CHARGING,
    BATTERY_STATUS_INVALID,
    REPORT_PASSIVE,
)

# Loop granularity (select). Low CPU cost; does not affect the mouse battery.
TICK = 1.0


class BatteryMonitor:
    def __init__(
        self,
        on_update=None,
        on_state=None,
        on_report=None,
        fallback=300.0,
        recheck=60.0,
        retry=5.0,
    ):
        self._on_update = on_update
        self._on_state = on_state
        # Called on every passive report 7 with (gear, dpi_x, dpi_y) — the
        # mouse's own DPI mirror (physical button). The caller decides whether
        # a refresh is needed (runs on the monitor thread).
        self._on_report = on_report
        # Maximum time without a report 7 before sending ONE query (0xAA) — but
        # only while the mouse is NOT asleep. With report 7 active, no commands
        # are sent (extra battery drain ~zero).
        self._fallback = fallback
        # While the mouse sleeps, reopens the device every `recheck` only
        # to re-detect the interface (e.g. USB cable plugged in) — NO commands.
        self._recheck = recheck
        self._retry = retry
        self._stop = threading.Event()
        self._refresh = threading.Event()
        self._tasks = queue.Queue()
        self._thread = None
        self._asleep = False
        self._quiet = False
        self._mode = None
        self._rpt_24g = None
        self._rpt_usb = None
        self._dev_path = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def request_refresh(self):
        self._refresh.set()

    def set_quiet(self, quiet):
        """Suppresses ALL device queries while a pairing session runs on its
        own receiver fd (story 5-4).

        The monitor must not send commands during the session: its 0xAA ACK
        could be misread by the session's 0xA7 poll as a match result (and the
        session's ACK misread by the monitor). In quiet mode the monitor keeps
        listening to passive reports (the tray stays live) but never queries,
        never runs tasks (they are deferred to the end of the session) and
        never sends the fallback 0xAA. The session owns the exclusive command
        channel for its duration.
        """
        self._quiet = bool(quiet)

    def submit(self, fn, on_done=None, on_error=None, wake=False):
        """Runs `fn(dev)` on the monitor thread with exclusive device access
        (the only reader/writer of the hidraw). `on_done(result)` /
        `on_error(exception)` are called from the monitor thread — the caller
        must hop back to the main thread (GLib.idle_add) before touching GTK.
        While the mouse is asleep a task is rejected with a CommandTimeout,
        unless `wake=True` (explicit user action: gear switch/edit): then the
        task is attempted immediately — if the device still times out, the
        monitor flips back to sleep mode. Does NOT set the refresh event: that
        one means "user wants a battery query" (wake); a background task must
        not wake an asleep mouse."""
        self._tasks.put((fn, on_done, on_error, wake))

    def _state(self, name, **kwargs):
        if self._on_state:
            self._on_state(name, **kwargs)

    def _notify(self, percent, charging=False, mode=None):
        if self._on_update:
            self._on_update(percent, charging=charging, mode=mode)

    def _run(self):
        while not self._stop.is_set():
            dev = None
            try:
                dev = RapooDevice().open()
                if dev.path != self._dev_path:
                    # Interface changed (receiver <-> USB cable): the mouse may be
                    # awake on the new interface — leave sleep mode.
                    self._asleep = False
                self._dev_path = dev.path
                if not self._asleep:
                    self._state("connected")
                self._poll(dev)
            except DeviceNotFound as exc:
                self._state("disconnected", reason=str(exc))
            except (DeviceOpenError, OSError) as exc:
                self._state("error", reason=str(exc))
            except CommandTimeout:
                self._state("asleep")
            except Exception as exc:
                self._state("error", reason=str(exc))
            finally:
                if dev is not None:
                    dev.close()
            self._stop.wait(self._retry)

    def _poll(self, dev):
        last_report = time.monotonic()
        # First read: 1 query only if we are not already asleep (and not in
        # quiet mode — a pairing session owns the command channel).
        if not self._asleep and not self._quiet:
            try:
                self._query_battery(dev)
            except CommandTimeout:
                self._asleep = True
                self._state("asleep")

        while not self._stop.is_set():
            # Pending device task (e.g. DPI read/gear switch): run it with
            # exclusive access. Consuming a task also consumes the wake-up
            # event so it does not trigger a redundant battery query.
            if not self._tasks.empty():
                self._refresh.clear()
                fn, on_done, on_error, wake = self._tasks.get_nowait()
                if self._quiet:
                    # Defer every task until the pairing session ends — the
                    # monitor must not write while the session's commands are
                    # in flight (its ACK could be misread as a 0xA7 result).
                    # Re-queue and fall through to the report listen (no hot
                    # spin, the tray keeps parsing report 7 during the run).
                    self._tasks.put((fn, on_done, on_error, wake))
                elif self._asleep and not wake:
                    if on_error:
                        on_error(CommandTimeout(i18n.tr("mouse_asleep")))
                else:
                    self._asleep = False
                    if not self._run_task(dev, fn, on_done, on_error) and wake:
                        # The mouse did not respond even though the user asked:
                        # it really is asleep.
                        self._asleep = True
                        self._state("asleep")
                continue
            # Manual refresh (user requested) -> explicit query.
            if self._refresh.is_set() and not self._quiet:
                self._refresh.clear()
                self._asleep = False
                last_report = time.monotonic()
                try:
                    self._query_battery(dev)
                except CommandTimeout:
                    self._asleep = True
                    self._state("asleep")
                continue
            data = dev.read_report(TICK)
            if data:
                self._handle_report(data)
                if data[0] == REPORT_PASSIVE:
                    self._asleep = False
                    last_report = time.monotonic()
                continue

            # No report for a long time AND mouse not asleep: 1 query to
            # revalidate (it may be awake but silent).
            if not self._asleep and not self._quiet and time.monotonic() - last_report >= self._fallback:
                last_report = time.monotonic()
                try:
                    self._query_battery(dev)
                except CommandTimeout:
                    self._asleep = True
                    self._state("asleep")
                continue

            # Silent for `recheck` (60s) and mouse awake: reopen to re-detect
            # the interface (USB cable plugged/unplugged) without staying
            # stuck on the same hidraw. The rescan is local (no RF commands).
            if not self._asleep and time.monotonic() - last_report >= self._recheck:
                return

            # Asleep: NO queries. Listen until report 7 comes back; reopen
            # every `recheck` to re-detect the interface, without commands.
            if self._asleep:
                if self._listen_quiet(dev):
                    self._asleep = False
                    last_report = time.monotonic()
                else:
                    return  # reopen (rescan) in _run

    def _listen_quiet(self, dev):
        """Listens only (no commands). True if a report 7/refresh arrived."""
        end = time.monotonic() + self._recheck
        while not self._stop.is_set() and time.monotonic() < end:
            if not self._tasks.empty():
                # Mouse asleep: reject background tasks with a timeout instead
                # of sending commands (the mouse must wake up first). An
                # explicit user task (wake=True) exits quiet mode and is left
                # queued, so the poll loop processes it right away.
                self._refresh.clear()
                fn, on_done, on_error, wake = self._tasks.get_nowait()
                if wake:
                    self._tasks.put((fn, on_done, on_error, wake))
                    return True
                if on_error:
                    on_error(CommandTimeout(i18n.tr("mouse_asleep")))
                return False
            if self._refresh.is_set():
                return True
            try:
                data = dev.read_report(TICK)
            except OSError:
                raise
            if data:
                self._handle_report(data)
                if data[0] == REPORT_PASSIVE:
                    return True
        return False

    def _run_task(self, dev, fn, on_done, on_error):
        try:
            result = fn(dev)
        except CommandTimeout as exc:
            if on_error:
                on_error(exc)
            return False
        except Exception as exc:
            if on_error:
                on_error(exc)
            return False
        else:
            if on_done:
                on_done(result)
            return True

    def _query_battery(self, dev):
        status, percent = dev.get_battery()
        # Mode from the active interface: USB cable = 2 (USB), otherwise 2.4G.
        # Report 7 fixes it later (e.g. BT), but without a report the mode is
        # already correct.
        self._mode = (
            protocol.MODE_USB
            if getattr(dev, "prefix", None) == protocol.PREFIX_USB
            else protocol.MODE_WIRELESS
        )
        self._state("connected", status=status)
        if status != BATTERY_STATUS_INVALID:
            self._notify(percent, charging=status == BATTERY_STATUS_CHARGING, mode=self._mode)

    def _handle_report(self, data):
        # Raw passive report (rid 7, 18 B): data[0]=rid, data[1] low nibble
        # = mode (0 2.4G, 1 BT, 2 USB), data[2]=gear, data[3..4]=dpiX LE,
        # data[5..6]=dpiY LE, data[7]=status, data[8]=battery%.
        if len(data) <= 8 or data[0] != REPORT_PASSIVE:
            return
        if data[1] in (protocol.PAIR_REPORT_PREFIX, protocol.PAIR_SUCCESS_REPORT):
            # Receiver pairing sub-command report (0xB0/0xB1), NOT a battery
            # report — parsing it would flip the tray to Bluetooth mode and
            # show a bogus battery from the pairing bytes.
            return
        self._mode = data[1] & 0x0F
        self._rpt_24g = data[10]
        self._rpt_usb = data[11]
        status = data[7]
        percent = data[8]
        if self._on_report:
            self._on_report(
                data[2], data[3] | (data[4] << 8), data[5] | (data[6] << 8)
            )
        self._state("connected", status=status)
        if status != BATTERY_STATUS_INVALID:
            self._notify(percent, charging=status == BATTERY_STATUS_CHARGING, mode=self._mode)

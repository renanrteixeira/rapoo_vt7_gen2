"""Guided receiver-pairing session worker (story 5-4).

Orchestrates the A Hub `MatcherDialog` flow on its own daemon thread and its
own `RapooDevice` restricted to the 2.4G receiver (prefix 0xA5). Sequence:
`start_match` (`[0xA5, 0xA0, 0x81]`) + `write_rf` (`[0xA5, 0xA1, 0x8F,
rf0..rf3]`, RF bytes random via `pairing_commands()`) — never waiting for
their reply (feature-report-only, unreadable on hidraw input 6) — then a
bounded matching loop that polls 0xA7, listens the raw report 7 for the 0xB1
pairing-success sub-command and polls the connected VID/PID until a result or
the window (60 s, A Hub default) expires.

The session owns a separate hidraw fd (same pattern as probe.py): hidraw
supports multiple open fds in one process, each receiving its own copy of
every report — the monitor keeps parsing its own reports and the session sees
the same reports (incl. any 0xB1) without contention. `battery.py` is
untouched.

Detection: 0xA7 reply `data[2]==0` is the VALIDATED failure signal
(2026-08-17). Success candidates (pinned by the on-device `--pair-run`
validation): report-7 `data[1]==0xB1`, then persistent non-zero 0xA7 (two
consecutive bytes — a single glitchy reply is not trusted), then a non-zero
connected VID/PID. Until the validation, all three are candidates; the window
treats them as success and FEATURES.md keeps them marked accordingly.

Cancellation is cooperative: `cancel()` sets a stop event checked after every
blocking operation; it never leaves the receiver mid-write (the destructive
commands are sent before the loop; inside it only the read-only 0xA7 poll and
`read_eeprom` run). Errors surface via the typed `PairingSessionError`/
`ReceiverNotFound` and the `on_result(status, message)` callback.
"""

import threading
import time

from . import pairing, protocol
from .device import CommandTimeout, DeviceNotFound, RapooDevice

STATUS_MATCHING = "matching"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_CANCELLED = "cancelled"
STATUS_ERROR = "error"

# Consecutive non-zero 0xA7 result bytes that count as a success candidate,
# and consecutive 0 bytes that count as a confirmed failure. A single reply
# (0 or non-zero) is not trusted: during the guided flow a live receiver may
# answer 0 before the user presses L+M+R.
_PERSISTENT_NONZERO = 2
_PERSISTENT_ZERO = 2

# The 0xA7 readiness probe is repeated this many times before giving up on a
# sleeping/unresponsive receiver (destructive frames must never be fired into
# one).
_READINESS_ATTEMPTS = 3


class PairingSessionError(Exception):
    """Base typed error of a pairing session (mirrors system.py/buttons.py)."""


class ReceiverNotFound(PairingSessionError):
    """No 0xA5 (2.4G receiver) configuration interface could be opened."""


class PairingSession:
    def __init__(
        self,
        factory=RapooDevice,
        window=60.0,
        poll=1.0,
        on_step=None,
        on_result=None,
    ):
        self._factory = factory
        self._window = float(window)
        self._poll = float(poll)
        self._on_step = on_step
        self._on_result = on_result
        self._stop = threading.Event()
        self._thread = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Starts the session on a daemon thread. Returns False when a run is
        already in flight (never queues a second one)."""
        if self.is_running:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="pairing-session", daemon=True
        )
        self._thread.start()
        return True

    def cancel(self):
        """Requests an early stop. The matching loop exits at the next
        iteration and no further pairing command is written after it."""
        self._stop.set()

    def _step(self, n):
        if self._on_step is not None:
            self._on_step(n)

    def _emit(self, status, message=None):
        if self._on_result is not None:
            self._on_result(status, message)

    def _run(self):
        dev = None
        try:
            dev = self._open_receiver()
        except ReceiverNotFound as exc:
            self._emit(STATUS_ERROR, exc)
            return
        except Exception as exc:
            self._emit(STATUS_ERROR, exc)
            return
        try:
            frames = pairing.pairing_commands()
            self._step(0)
            # Readiness gate: never fire the destructive start_match/write_rf
            # into a sleeping receiver. Probe 0xA7 up to 3 attempts (~1 s
            # apart); any reply (even data[2]==0) proves the receiver is awake.
            gate = frames["get_result"]
            for attempt in range(_READINESS_ATTEMPTS):
                try:
                    dev.query(gate[1], gate[2:], timeout=1.0, prefix=gate[0])
                    break
                except CommandTimeout:
                    if attempt == _READINESS_ATTEMPTS - 1:
                        self._emit(
                            STATUS_ERROR,
                            "receiver not responding — power on the wireless "
                            "mouse / bring it in range, then try again",
                        )
                        return
                    time.sleep(1.0)
                except OSError as exc:
                    self._emit(STATUS_ERROR, exc)
                    return
            try:
                start = frames["start_match"]
                dev.send_command(
                    start[1], start[2:], prefix=start[0]
                )
                rf = frames["write_rf"]
                dev.send_command(rf[1], rf[2:], prefix=rf[0])
            except OSError as exc:
                self._emit(STATUS_ERROR, exc)
                return
            # Baseline: if a mouse is already attached, the connected VID/PID
            # poll is useless as a success signal during this run.
            try:
                attached = pairing.decode_connected_vid_pid(dev)
            except (CommandTimeout, OSError):
                attached = None
            baseline_attached = bool(
                attached is not None
                and attached["vid"] != "none attached"
                and attached["pid"] != "none attached"
            )
            self._step(1)
            self._matching(dev, frames, baseline_attached)
        except Exception as exc:
            # Never let the thread die silently: any unexpected error must
            # surface through on_result or the GUI busy guard stays stuck.
            self._emit(STATUS_ERROR, exc)
        finally:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass

    def _open_receiver(self):
        dev = self._factory()
        try:
            dev.open(prefix=protocol.PREFIX_WIRELESS)
        except DeviceNotFound as exc:
            raise ReceiverNotFound(str(exc)) from exc
        return dev

    def _matching(self, dev, frames, baseline_attached):
        self._step(2)
        get_result = frames["get_result"]
        deadline = time.monotonic() + self._window
        nonzero_streak = 0
        zero_streak = 0
        while not self._stop.is_set() and time.monotonic() < deadline:
            # 1) Report-7 raw listen: 0xB1 = pairing success (bundle).
            try:
                data = dev.read_report(0.3)
            except OSError as exc:
                self._emit(STATUS_ERROR, exc)
                return
            if (
                data is not None
                and len(data) > 1
                and data[0] == protocol.REPORT_PASSIVE
                and data[1] == protocol.PAIR_SUCCESS_REPORT
            ):
                self._emit(STATUS_SUCCESS)
                return
            if self._stop.is_set():
                break
            # 2) 0xA7 poll: two consecutive data[2]==0 = failed (validated);
            #    persistent non-zero = success candidate. Timeout = non-fatal
            #    (the receiver may be busy / the mouse power-cycled).
            try:
                resp = dev.query(
                    get_result[1],
                    get_result[2:],
                    timeout=1.0,
                    prefix=get_result[0],
                )
            except CommandTimeout:
                nonzero_streak = 0
                zero_streak = 0
            except OSError as exc:
                self._emit(STATUS_ERROR, exc)
                return
            else:
                result = pairing.match_result_byte(resp)
                if result == 0:
                    zero_streak += 1
                    nonzero_streak = 0
                    if zero_streak >= _PERSISTENT_ZERO:
                        self._emit(STATUS_FAILED)
                        return
                elif result is not None:
                    zero_streak = 0
                    nonzero_streak += 1
                    if nonzero_streak >= _PERSISTENT_NONZERO:
                        self._emit(STATUS_SUCCESS)
                        return
                else:
                    zero_streak = 0
                    nonzero_streak = 0
            if self._stop.is_set():
                break
            # 3) Connected VID/PID poll (read-only; timeouts non-fatal). Only a
            #    mouse appearing DURING this run (not attached at baseline) and
            #    reporting both VID and PID counts as success.
            connected = None
            try:
                connected = pairing.decode_connected_vid_pid(dev)
            except (CommandTimeout, OSError):
                connected = None
            if (
                not baseline_attached
                and connected is not None
                and connected["vid"] != "none attached"
                and connected["pid"] != "none attached"
            ):
                self._emit(STATUS_SUCCESS)
                return
            time.sleep(min(self._poll, max(deadline - time.monotonic(), 0)))
        if self._stop.is_set():
            self._emit(STATUS_CANCELLED)
        else:
            self._emit(STATUS_TIMEOUT)
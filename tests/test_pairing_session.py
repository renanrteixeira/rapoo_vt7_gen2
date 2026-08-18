import os
import sys
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import pairing, pairing_session, protocol
from src.rapoo_vt7.device import CommandTimeout, DeviceNotFound
from src.rapoo_vt7.pairing_session import (
    PairingSession,
    PairingSessionError,
    ReceiverNotFound,
    STATUS_CANCELLED,
    STATUS_ERROR,
    STATUS_FAILED,
    STATUS_SUCCESS,
    STATUS_TIMEOUT,
)


class Result:
    """Collects the session callbacks and signals completion."""

    def __init__(self):
        self.status = None
        self.message = None
        self.steps = []
        self.done = threading.Event()

    def on_step(self, n):
        self.steps.append(n)

    def on_result(self, status, message=None):
        self.status = status
        self.message = message
        self.done.set()


class FakeDev:
    """RapooDevice stand-in for the session worker.

    `a7` is the 0xA7 match-result byte (hidraw data[2]); `report` the bytes of
    read_report (None = nothing arrives); `connected` the VID/PID the receiver
    reports via read_eeprom; `gate` (when set) blocks query until released so
    a test can cancel mid-loop. `sent` records the destructive commands.
    """

    def __init__(
        self,
        a7=0,
        report=None,
        connected=None,
        open_error=None,
        report_error=None,
        query_error=None,
        connected_error=None,
        gate=None,
        a7_seq=None,
    ):
        self.path = "/dev/hidraw2"
        self.sent = []
        self.a7 = a7
        self.report = report
        self.connected = connected or {
            "vid": "none attached",
            "pid": "none attached",
        }
        self.open_error = open_error
        self.report_error = report_error
        self.query_error = query_error
        self.connected_error = connected_error
        self.gate = gate
        self.a7_seq = list(a7_seq) if a7_seq is not None else None
        self._a7_tail = None
        self.opened = False
        self.closed = False

    def open(self, prefix=None):
        if self.open_error is not None:
            raise self.open_error
        self.opened = True
        return self

    def close(self):
        self.closed = True

    def send_command(self, cmd_id, args=(), prefix=None):
        self.sent.append((cmd_id, tuple(args), prefix))
        return bytes([prefix, cmd_id]) + bytes(args)

    def read_report(self, timeout=0.5):
        if self.report_error is not None:
            raise self.report_error
        return self.report

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        if self.query_error is not None:
            raise self.query_error
        if self.gate is not None:
            self.gate.wait()
        value = self.a7
        if self.a7_seq is not None:
            if self.a7_seq:
                value = self.a7_seq.pop(0)
            elif self._a7_tail is not None:
                value = self._a7_tail
            self._a7_tail = value
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.MATCH_RESULT_OFFSET] = value
        return bytes(resp)

    def read_eeprom(self, addr, length=1):
        if self.connected_error is not None:
            raise self.connected_error
        base = (addr[1] << 8) | addr[0]
        val = self.connected.get("vid" if base == 0x0000 else "pid", 0)
        if val in ("none attached", 0, "0"):
            data = b"\x00\x00"
        else:
            data = bytes([int(val[2:], 16), int(val[:2], 16)])
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + 2] = data
        return bytes(resp)


def run(dev, **kw):
    """Runs a session to completion on its own thread and returns (Result,
    PairingSession)."""
    result = Result()
    session = PairingSession(factory=lambda: dev, on_step=result.on_step,
                             on_result=result.on_result, **kw)
    session.start()
    result.done.wait(5.0)
    return result, session


class PairingSessionTest(unittest.TestCase):
    def _wait(self, result):
        self.assertTrue(result.done.wait(5.0), "session never completed")

    def test_sends_exactly_start_match_then_write_rf(self):
        dev = FakeDev(a7=0)
        with mock.patch.object(pairing.os, "urandom",
                               return_value=b"\xAA\xBB\xCC\xDD"):
            result, _s = run(dev)
        self._wait(result)
        self.assertEqual(
            dev.sent,
            [
                (protocol.PAIR_START_MATCH, (protocol.PAIR_MATCH_SUB,),
                 protocol.PREFIX_WIRELESS),
                (protocol.PAIR_WRITE_RF,
                 (protocol.PAIR_WRITE_RF_SUB, 0xAA, 0xBB, 0xCC, 0xDD),
                 protocol.PREFIX_WIRELESS),
            ],
        )
        self.assertEqual(result.status, STATUS_FAILED)

    def test_failed_when_a7_zero(self):
        dev = FakeDev(a7=0)
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_FAILED)

    def test_success_on_b1_report(self):
        dev = FakeDev(a7=0, report=bytes([0x07, 0xB1, 0x01]))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_success_on_persistent_nonzero_a7(self):
        dev = FakeDev(a7=0x03)
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_success_on_connected_vid_pid(self):
        # The VID/PID is already attached at baseline, so that signal is
        # intentionally disabled during this run (patch 4) — success comes from
        # the persistent non-zero 0xA7 streak instead.
        dev = FakeDev(a7=0x01, connected={"vid": "24AE", "pid": "4613"})
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_timeout_when_nothing_arrives(self):
        class GateThenTimeoutDev(FakeDev):
            """Answers the readiness gate (first query) with an ACK, then the
            matching-loop queries all time out (receiver busy / mouse asleep)."""

            def __init__(self):
                super().__init__(a7=0, connected_error=CommandTimeout("asleep"))
                self.calls = 0

            def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
                self.calls += 1
                if self.calls == 1:
                    return super().query(cmd_id, args, timeout, prefix)
                raise CommandTimeout("asleep")

        dev = GateThenTimeoutDev()
        result, _s = run(dev, window=0.1, poll=0.01)
        self._wait(result)
        self.assertEqual(result.status, STATUS_TIMEOUT)

    def test_receiver_not_found_is_error(self):
        dev = FakeDev(open_error=DeviceNotFound("no receiver"))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIsInstance(result.message, ReceiverNotFound)
        self.assertIsInstance(result.message, PairingSessionError)

    def test_report_oserror_ends_session(self):
        dev = FakeDev(report_error=OSError("unplugged"))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIsInstance(result.message, OSError)

    def test_query_oserror_ends_session(self):
        dev = FakeDev(query_error=OSError("busy"))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIsInstance(result.message, OSError)

    def test_steps_emitted_in_order(self):
        dev = FakeDev(a7=0)
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.steps, [0, 1, 2])

    def test_receiver_closed_after_run(self):
        dev = FakeDev(a7=0)
        result, _s = run(dev)
        self._wait(result)
        self.assertTrue(dev.closed)
        self.assertTrue(dev.opened)

    def test_open_other_error_is_error(self):
        dev = FakeDev(open_error=OSError("boom"))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIsInstance(result.message, OSError)

    def test_readiness_gate_aborts_before_destructive_frames(self):
        # The receiver never answers the readiness 0xA7 probe: the run must
        # end with an error and MUST NOT send the destructive frames.
        dev = FakeDev(query_error=CommandTimeout("asleep"))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_ERROR)
        self.assertIn("not responding", str(result.message))
        self.assertEqual(
            dev.sent,
            [],
            "destructive frames must not be sent into a sleeping receiver",
        )

    def test_baseline_attached_disables_vid_pid_success(self):
        # The receiver already has a mouse attached before the run: the VID/PID
        # poll is useless as a success signal, so the run must time out (no
        # 0xB1, 0xA7 replies are non-ACK -> None).
        class NonAckDev(FakeDev):
            def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
                resp = bytearray(32)
                resp[0] = protocol.REPORT_CMD
                resp[1] = protocol.RESP_EMPTY
                return bytes(resp)

        dev = NonAckDev(connected={"vid": "24AE", "pid": "4613"})
        result, _s = run(dev, window=0.1, poll=0.01)
        self._wait(result)
        self.assertEqual(result.status, STATUS_TIMEOUT)

    def test_single_zero_then_nonzero_is_success(self):
        # One 0xA7==0 while the user is still pressing L+M+R must not abort;
        # two consecutive non-zero bytes then win the streak. The first entry
        # is consumed by the readiness gate and its value is irrelevant.
        dev = FakeDev(a7_seq=[0x05, 0, 0x01, 0x01])
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_two_consecutive_zeros_is_failed(self):
        dev = FakeDev(a7_seq=[0x05, 0, 0, 0])
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_FAILED)

    def test_short_two_byte_b1_report_is_success(self):
        dev = FakeDev(a7=0, report=bytes([0x07, 0xB1]))
        result, _s = run(dev)
        self._wait(result)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_cancel_stops_matching_and_writes_nothing_more(self):
        class GatedDev(FakeDev):
            def __init__(self, entered):
                super().__init__(a7=0x01, gate=threading.Event())
                self.entered = entered

            def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
                self.entered.set()
                return super().query(cmd_id, args, timeout, prefix)

        entered = threading.Event()
        dev = GatedDev(entered)
        result = Result()
        session = PairingSession(factory=lambda: dev, on_step=result.on_step,
                                 on_result=result.on_result, window=10.0)
        session.start()
        # Wait until the loop is blocked inside the 0xA7 query, then cancel.
        self.assertTrue(entered.wait(5.0), "session never reached the query")
        session.cancel()
        dev.gate.set()
        self.assertTrue(result.done.wait(5.0), "cancel never produced a result")
        self.assertEqual(result.status, STATUS_CANCELLED)
        self.assertEqual(
            [c[0] for c in dev.sent],
            [protocol.PAIR_START_MATCH, protocol.PAIR_WRITE_RF],
            "no further pairing command may be written after cancel",
        )

    def test_start_refuses_when_already_running(self):
        gate = threading.Event()
        dev = FakeDev(a7=0x01, gate=gate)
        session = PairingSession(factory=lambda: dev, window=10.0)
        session.start()
        self.assertTrue(session.is_running)
        self.assertFalse(session.start())
        gate.set()
        session.cancel()
        session._thread.join(timeout=5.0)
        self.assertFalse(session.is_running)


class PairingSessionUnitTest(unittest.TestCase):
    def test_status_constants(self):
        self.assertEqual(STATUS_SUCCESS, "success")
        self.assertEqual(STATUS_FAILED, "failed")
        self.assertEqual(STATUS_TIMEOUT, "timeout")
        self.assertEqual(STATUS_CANCELLED, "cancelled")
        self.assertEqual(STATUS_ERROR, "error")


if __name__ == "__main__":
    unittest.main()
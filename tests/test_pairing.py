import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import probe
from src.rapoo_vt7 import pairing, protocol
from src.rapoo_vt7.device import CommandTimeout, DeviceNotFound


class FakeDev:
    """RapooDevice stand-in for the pairing probes: `data` overrides the value
    at a given absolute address (like test_probe.py), `sent` records the
    destructive commands, `read_response` returns an ACK reply and `report` is
    the bytes returned by read_report (None = nothing arrives)."""

    def __init__(self, data=None, report=None):
        self.path = "/dev/hidraw2"
        self.calls = []
        self.sent = []
        self.data = data or {}
        self.report = report

    def open(self, prefix=None):
        return self

    def close(self):
        pass

    def read_eeprom(self, addr, length):
        self.calls.append((addr, length))
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

    def read_report(self, timeout=0.5):
        return self.report

    def send_command(self, cmd_id, args=(), prefix=None):
        self.sent.append((cmd_id, tuple(args), prefix))
        return bytes([prefix, cmd_id]) + bytes(args)

    def read_response(self, cmd_id=None, timeout=1.0):
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        return bytes(resp)


class PairingConstantsTest(unittest.TestCase):
    def test_pair_constants_in_free_range(self):
        self.assertEqual(protocol.PAIR_START_MATCH, 0xA0)
        self.assertEqual(protocol.PAIR_WRITE_RF, 0xA1)
        self.assertEqual(protocol.PAIR_GET_RESULT, 0xA7)
        self.assertEqual(protocol.PAIR_MATCH_SUB, 0x81)
        self.assertEqual(protocol.PAIR_WRITE_RF_SUB, 0x8F)
        self.assertEqual(protocol.CONNECTED_MOUSE_VID_ADDR, (0x00, 0x00))
        self.assertEqual(protocol.CONNECTED_MOUSE_PID_ADDR, (0x04, 0x00))

    def test_pair_cmds_do_not_collide_with_existing_cmds(self):
        used = {
            protocol.GET_WORK_MODE,
            protocol.GET_FIRMWARE,
            protocol.READ_EEPROM,
            protocol.WRITE_EEPROM,
            protocol.FACTORY_UPDATE,
            protocol.GET_BATTERY_LEVEL,
            protocol.RETURN_FACTORY_SETTINGS,
        }
        self.assertFalse(
            {protocol.PAIR_START_MATCH, protocol.PAIR_WRITE_RF, protocol.PAIR_GET_RESULT}
            & used
        )


class PairingCommandsTest(unittest.TestCase):
    def test_start_match_full_frame(self):
        cmds = pairing.pairing_commands(rf_bytes=b"\x01\x02\x03\x04")
        self.assertEqual(cmds["start_match"], [0xA5, 0xA0, 0x81])

    def test_write_rf_full_frame(self):
        cmds = pairing.pairing_commands(rf_bytes=b"\x01\x02\x03\x04")
        self.assertEqual(cmds["write_rf"], [0xA5, 0xA1, 0x8F, 0x01, 0x02, 0x03, 0x04])

    def test_get_result_full_frame(self):
        cmds = pairing.pairing_commands(rf_bytes=b"\x01\x02\x03\x04")
        self.assertEqual(cmds["get_result"], [0xA5, 0xA7])

    def test_rf_bytes_default_os_urandom_4(self):
        with mock.patch.object(pairing.os, "urandom", return_value=b"\xAA\xBB\xCC\xDD"):
            cmds = pairing.pairing_commands()
        self.assertEqual(cmds["write_rf"][3:], [0xAA, 0xBB, 0xCC, 0xDD])

    def test_rf_bytes_wrong_length_rejected(self):
        for bad in (b"\x01\x02\x03", b"\x01\x02\x03\x04\x05"):
            with self.subTest(rf=bad):
                with self.assertRaises(pairing.PairingDiscoveryError):
                    pairing.pairing_commands(rf_bytes=bad)


class DecodeConnectedVidPidTest(unittest.TestCase):
    def test_decodes_hex_from_ack_replies(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        result = pairing.decode_connected_vid_pid(dev)
        self.assertEqual(result["vid"], "24AE")
        self.assertEqual(result["pid"], "4613")
        self.assertEqual(dev.calls[0], (protocol.CONNECTED_MOUSE_VID_ADDR, 2))
        self.assertEqual(dev.calls[1], (protocol.CONNECTED_MOUSE_PID_ADDR, 2))

    def test_non_ack_reply_is_none_attached(self):
        dev = FakeDev()

        def noack(addr, length):
            resp = bytearray(32)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_EMPTY
            return bytes(resp)

        dev.read_eeprom = noack
        result = pairing.decode_connected_vid_pid(dev)
        self.assertEqual(result["vid"], "none attached")
        self.assertEqual(result["pid"], "none attached")

    def test_short_reply_is_none_attached_without_raising(self):
        dev = FakeDev()

        def short(addr, length):
            return bytes([protocol.REPORT_CMD, protocol.RESP_ACK])

        dev.read_eeprom = short
        result = pairing.decode_connected_vid_pid(dev)
        self.assertEqual(result["vid"], "none attached")
        self.assertEqual(result["pid"], "none attached")

    def test_zero_value_is_none_attached(self):
        dev = FakeDev()

        def zero(addr, length):
            resp = bytearray(32)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = zero
        result = pairing.decode_connected_vid_pid(dev)
        self.assertEqual(result["vid"], "none attached")
        self.assertEqual(result["pid"], "none attached")

    def test_partial_failure_one_field_none_attached(self):
        dev = FakeDev()

        def mixed(addr, length):
            base = (addr[1] << 8) | addr[0]
            if base == 0x0000:
                resp = bytearray(32)
                resp[0] = protocol.REPORT_CMD
                resp[1] = protocol.RESP_ACK
                resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + 2] = b"\xAE\x24"
                return bytes(resp)
            return bytes([protocol.REPORT_CMD, protocol.RESP_ACK])

        dev.read_eeprom = mixed
        result = pairing.decode_connected_vid_pid(dev)
        self.assertEqual(result["vid"], "24AE")
        self.assertEqual(result["pid"], "none attached")

    def test_command_timeout_propagates(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with self.assertRaises(CommandTimeout):
            pairing.decode_connected_vid_pid(dev)


class PairDiscoverMainTest(unittest.TestCase):
    def test_happy_reads_vid_pid_and_prints_flow(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("VID: 24AE", text)
        self.assertIn("PID: 4613", text)
        self.assertIn("3-step pairing flow", text)
        self.assertEqual(dev.sent, [], "no destructive command fired in read-only mode")

    def test_no_device_reports_receiver_not_found(self):
        class OpenFails:
            def open(self, prefix=None):
                raise DeviceNotFound("not found")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenFails()), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("receiver", err.getvalue())
        self.assertIn("not found", err.getvalue())

    def test_wrong_iface_usb_mouse_only_reports_receiver_not_found(self):
        # A USB-cable mouse (prefix 0xFF) must never be opened: open(prefix=0xA5)
        # raises DeviceNotFound before any read of the mouse.
        class OpenFails:
            def open(self, prefix=None):
                raise DeviceNotFound("receiver absent")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenFails()), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("receiver", err.getvalue())

    def test_partial_timeout_marks_partial_and_exits_nonzero(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("VID/PID: no response", out.getvalue())
        self.assertIn("partial", err.getvalue())

    def test_vid_pid_oserror_marks_partial_and_exits_nonzero(self):
        dev = FakeDev()

        def boom(addr, length):
            raise OSError("read failed")

        dev.read_eeprom = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("VID/PID: read failed", err.getvalue())
        self.assertIn("partial", err.getvalue())

    def test_asleep_empty_reports_non_fatal(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        empty = bytes([protocol.REPORT_CMD, protocol.RESP_EMPTY]) + b"\x00" * 30
        seen = {"n": 0}

        def rr(timeout=0.5):
            seen["n"] += 1
            return empty if seen["n"] == 1 else None

        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(dev, "read_report", side_effect=rr), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 0)
        self.assertIn("(empty — receiver/mouse asleep)", out.getvalue())

    def test_destructive_confirmed_fires_commands_and_dumps_reply(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_discover_main(
                window=0.01,
                destructive=["start_match", "write_rf"],
                rf_bytes=b"\x01\x02\x03\x04",
            )
        self.assertEqual(rc, 0)
        self.assertEqual(
            dev.sent,
            [
                (protocol.PAIR_START_MATCH, (protocol.PAIR_MATCH_SUB,), protocol.PREFIX_WIRELESS),
                (protocol.PAIR_WRITE_RF, (protocol.PAIR_WRITE_RF_SUB, 1, 2, 3, 4), protocol.PREFIX_WIRELESS),
            ],
        )
        self.assertIn("start_match ->", out.getvalue())
        self.assertIn("write_rf ->", out.getvalue())

    def test_destructive_no_reply_is_expected_not_partial(self):
        # 0xA0/0xA1 reply only on the feature report (unreadable on hidraw
        # input 6), so no input-6 reply is the EXPECTED outcome — the run must
        # NOT be marked partial or exit non-zero.
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})

        def noack(cmd_id=None, timeout=1.0):
            return None

        dev.read_response = noack
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(
                window=0.01,
                destructive=["start_match"],
                rf_bytes=b"\x01\x02\x03\x04",
            )
        self.assertEqual(rc, 0)
        self.assertIn("no input-6 reply (expected", out.getvalue())
        self.assertIn("watch report 7 / 0xA7", out.getvalue())
        self.assertEqual(err.getvalue(), "")

    def test_want_result_prints_raw_and_reply_byte(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})

        def query(cmd_id, args=(), timeout=1.0, prefix=None):
            resp = bytearray(32)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            resp[2] = 0x03
            return bytes(resp)

        dev.query = query
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_discover_main(window=0.01, want_result=True)
        self.assertEqual(rc, 0)
        self.assertIn("match result (0xA7) raw:", out.getvalue())
        self.assertIn("reply byte: 3", out.getvalue())

    def test_want_result_short_reply_prints_none(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})

        def query(cmd_id, args=(), timeout=1.0, prefix=None):
            return bytes([protocol.REPORT_CMD, protocol.RESP_ACK])

        dev.query = query
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_discover_main(window=0.01, want_result=True)
        self.assertEqual(rc, 0)
        self.assertIn("reply byte: None", out.getvalue())

    def test_want_result_timeout_marks_partial(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})

        def boom(cmd_id, args=(), timeout=1.0, prefix=None):
            raise CommandTimeout("asleep")

        dev.query = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01, want_result=True)
        self.assertEqual(rc, 1)
        self.assertIn("match result (0xA7): no response", out.getvalue())

    def test_open_other_error_prints_probe_error_and_exits_nonzero(self):
        class OpenErrors:
            def open(self, prefix=None):
                raise OSError("boom")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenErrors()), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertTrue(err.getvalue().strip())

    def test_listen_read_oserror_marks_partial(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})

        def boom(timeout=0.5):
            raise OSError("unplugged")

        dev.read_report = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_discover_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("listen read failed", err.getvalue())


class PairGateTest(unittest.TestCase):
    class NonTtyStdin:
        def isatty(self):
            return False

    class TtyStdin:
        def isatty(self):
            return True

    class Args:
        def __init__(self, start=False, write=None, risks=False):
            self.start_match = start
            self.write_rf = write
            self.i_understand_risks = risks

    def test_no_destructive_flag_returns_empty_plan(self):
        args = self.Args()
        self.assertEqual(probe._pair_destructive(args), ([], None))

    def test_start_match_refused_without_risks_flag(self):
        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(self.Args(start=True), stdin=self.NonTtyStdin())
        self.assertIn("--i-understand-risks", str(ctx.exception))

    def test_non_tty_auto_refuses_even_with_risks_flag(self):
        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(
                self.Args(start=True, risks=True), stdin=self.NonTtyStdin()
            )
        self.assertIn("TTY", str(ctx.exception))

    def test_tty_wrong_answer_refuses(self):
        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(
                self.Args(start=True, risks=True),
                stdin=self.TtyStdin(),
                prompt=lambda m: "no",
            )
        self.assertIn("confirmation", str(ctx.exception))

    def test_tty_confirmation_allows_plan(self):
        destructive, rf = probe._pair_destructive(
            self.Args(start=True, write="01020304", risks=True),
            stdin=self.TtyStdin(),
            prompt=lambda m: "yes",
        )
        self.assertEqual(destructive, ["start_match", "write_rf"])
        self.assertEqual(rf, b"\x01\x02\x03\x04")

    def test_write_rf_alone_allowed_plan(self):
        destructive, rf = probe._pair_destructive(
            self.Args(write="01020304", risks=True),
            stdin=self.TtyStdin(),
            prompt=lambda m: "yes",
        )
        self.assertEqual(destructive, ["write_rf"])
        self.assertEqual(rf, b"\x01\x02\x03\x04")

    def test_tty_eof_refuses_cleanly(self):
        def eof(m):
            raise EOFError()

        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(
                self.Args(start=True, risks=True),
                stdin=self.TtyStdin(),
                prompt=eof,
            )
        self.assertIn("confirmation", str(ctx.exception))

    def test_write_rf_invalid_hex_refused(self):
        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(
                self.Args(write="zz", risks=True), stdin=self.TtyStdin()
            )
        self.assertIn("hex", str(ctx.exception))

    def test_write_rf_wrong_length_refused(self):
        with self.assertRaises(ValueError) as ctx:
            probe._pair_destructive(
                self.Args(write="010203", risks=True), stdin=self.TtyStdin()
            )
        self.assertIn("4 bytes", str(ctx.exception))


class PairDiscoverMainDispatchTest(unittest.TestCase):
    def test_main_pair_discover_non_tty_auto_refuses(self):
        with mock.patch.object(probe, "RapooDevice") as mdev, \
                mock.patch.object(sys, "stdin", PairGateTest.NonTtyStdin()), \
                mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--pair-discover", "--start-match", "--i-understand-risks"],
                ), mock.patch("sys.stderr", new=io.StringIO()):
            rc = probe.main()
        self.assertEqual(rc, 2)
        mdev.assert_not_called()

    def test_main_pair_discover_confirmed_runs_destructive(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(sys, "stdin", PairGateTest.TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0.01"}, clear=False
                ), mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--pair-discover", "--start-match", "--i-understand-risks"],
                ), mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertEqual(dev.sent[0][0], protocol.PAIR_START_MATCH)
        self.assertIn("start_match ->", out.getvalue())

    def test_main_pair_modifiers_require_pair_discover(self):
        with mock.patch.object(sys, "argv", ["probe", "--pair-result"]), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("only apply with --pair-discover", err.getvalue())

    def test_main_write_rf_alone_requires_pair_discover(self):
        with mock.patch.object(
            sys, "argv", ["probe", "--write-rf", "01020304"]
        ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("only apply with --pair-discover", err.getvalue())


class MatchResultByteTest(unittest.TestCase):
    def _ack(self, result_byte):
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.MATCH_RESULT_OFFSET] = result_byte
        return bytes(resp)

    def test_valid_ack_returns_the_byte(self):
        self.assertEqual(pairing.match_result_byte(self._ack(0x03)), 0x03)
        self.assertEqual(pairing.match_result_byte(self._ack(0x00)), 0x00)

    def test_non_indexable_returns_none(self):
        self.assertIsNone(pairing.match_result_byte(object()))
        self.assertIsNone(pairing.match_result_byte(None))

    def test_too_short_reply_returns_none(self):
        self.assertIsNone(pairing.match_result_byte(b"\x06\x01"))
        self.assertIsNone(
            pairing.match_result_byte(bytes([0x06] * protocol.MATCH_RESULT_OFFSET))
        )

    def test_non_ack_reply_returns_none(self):
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_EMPTY
        resp[protocol.MATCH_RESULT_OFFSET] = 0x01
        self.assertIsNone(pairing.match_result_byte(bytes(resp)))


if __name__ == "__main__":
    unittest.main()

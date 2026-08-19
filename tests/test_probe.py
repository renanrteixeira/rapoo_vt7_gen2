import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import probe
from src.rapoo_vt7 import parameters, protocol, settings
from src.rapoo_vt7.device import CommandTimeout, DeviceNotFound


class FakeDev:
    """RapooDevice stand-in: read_eeprom returns an ACK reply whose data
    (starting at EEPROM_DATA_OFFSET) is the address bytes themselves, unless
    `data` overrides the value at a given absolute address. `report` is the
    bytes returned by read_report (None = no passive report)."""

    def __init__(self, data=None, report=None):
        self.path = "/dev/hidraw2"
        self.calls = []
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


class RunFakeDev(FakeDev):
    """FakeDev + query/send_command for the --pair-run harness. `a7` is the
    0xA7 match-result byte; `a7_error` makes the poll fail."""

    def __init__(self, data=None, report=None, a7=0, a7_error=None):
        super().__init__(data=data, report=report)
        self.sent = []
        self.a7 = a7
        self.a7_error = a7_error

    def send_command(self, cmd_id, args=(), prefix=None):
        self.sent.append((cmd_id, tuple(args), prefix))
        return bytes([prefix, cmd_id]) + bytes(args)

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None):
        if cmd_id != protocol.PAIR_GET_RESULT:
            raise AssertionError("unexpected query cmd 0x%02X" % cmd_id)
        if self.a7_error is not None:
            raise self.a7_error
        resp = bytearray(32)
        resp[0] = protocol.REPORT_CMD
        resp[1] = protocol.RESP_ACK
        resp[protocol.MATCH_RESULT_OFFSET] = self.a7
        return bytes(resp)


class BuildBaselineTest(unittest.TestCase):
    def test_reads_43_blocks_covering_bank0(self):
        dev = FakeDev()
        baseline = probe.build_baseline(dev)

        self.assertEqual(baseline["device"], "/dev/hidraw2")
        self.assertEqual(baseline["bank"], 0)
        self.assertEqual(baseline["start"], protocol.EEPROM_BANK0_BASE)
        self.assertEqual(baseline["end"], protocol.EEPROM_BANK0_END)
        self.assertIsInstance(baseline["captured_at"], str)

        blocks = baseline["blocks"]
        self.assertEqual(len(blocks), 43)
        keys = list(blocks)
        self.assertEqual(keys[0], "0x0600")
        self.assertEqual(keys[1], "0x0618")
        self.assertEqual(keys[-1], "0x09F0")

        self.assertEqual(len(dev.calls), 43)
        for i in range(42):
            with self.subTest(block=i):
                self.assertEqual(dev.calls[i], (protocol.eeprom_bank0(24 * i), 24))
        self.assertEqual(dev.calls[-1], (protocol.eeprom_bank0(0x03F0), 16))

        first = bytes.fromhex(blocks["0x0600"])
        self.assertEqual(first[0], 0x00)
        self.assertEqual(first[-1], 0x17)
        self.assertEqual(len(first), 24)

        last = bytes.fromhex(blocks["0x09F0"])
        self.assertEqual(len(last), 16)
        self.assertEqual(last[0], 0xF0)
        self.assertEqual(last[-1], 0xFF)

    def test_command_timeout_propagates(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with self.assertRaises(CommandTimeout):
            probe.build_baseline(dev)

    def test_short_reply_raises_value_error(self):
        dev = FakeDev()

        def short(addr, length):
            resp = bytearray(protocol.EEPROM_DATA_OFFSET + 3)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = short
        with self.assertRaises(ValueError):
            probe.build_baseline(dev)


class WriteBaselineTest(unittest.TestCase):
    def test_writes_valid_json_atomically(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")
        data = {
            "device": "/dev/hidraw2",
            "bank": 0,
            "start": 0x0600,
            "end": 0x0A00,
            "blocks": {"0x0600": "000102"},
        }
        probe.write_baseline(path, data)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f), data)
        self.assertEqual(
            [p for p in os.listdir(d) if p.startswith(".")], [],
            "temp file left behind",
        )

    def test_replace_error_preserves_previous_and_cleans_temp(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("previous")
        with mock.patch.object(probe.os, "replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                probe.write_baseline(path, {"bank": 0})
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "previous")
        self.assertEqual(
            [p for p in os.listdir(d) if p.startswith(".")], [],
            "temp file left behind",
        )

    def test_unwritable_dir_raises_oserror(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "sub", "eeprom_baseline.json")
        with mock.patch.object(
            probe.os, "makedirs", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(PermissionError):
                probe.write_baseline(path, {"bank": 0})
        self.assertFalse(os.path.exists(os.path.join(d, "sub")))


class StatusTest(unittest.TestCase):
    def report7(self, gear=1, dpi_x=0x1388, dpi_y=0x1388, rpt24=1, rptusb=1):
        r = bytearray(18)
        r[0] = protocol.REPORT_PASSIVE
        r[protocol.R7_MODE] = 0x10
        r[protocol.R7_DPI_GEAR] = gear
        r[protocol.R7_DPI_X] = dpi_x & 0xFF
        r[protocol.R7_DPI_X + 1] = (dpi_x >> 8) & 0xFF
        r[protocol.R7_DPI_Y] = dpi_y & 0xFF
        r[protocol.R7_DPI_Y + 1] = (dpi_y >> 8) & 0xFF
        r[protocol.R7_RPT_24G] = rpt24
        r[protocol.R7_RPT_USB] = rptusb
        r[protocol.R7_CONFIG] = 1
        return bytes(r)

    def test_status_reads_every_field_and_shared_byte_once(self):
        dev = FakeDev()
        status = probe.build_status(dev, report7_window=0.01)

        self.assertEqual(
            set(status["fields"]), set(settings.FIELDS), "every registry field read"
        )
        for name, field in status["fields"].items():
            with self.subTest(field=name):
                self.assertIn("addr", field)
                self.assertIn("raw", field)
                self.assertIn("value", field)

        shared_calls = [
            a for a, _ in dev.calls if (a[1] << 8) | a[0] == 0x08D8
        ]
        self.assertEqual(
            len(shared_calls), 1, "shared 0x08D8 byte must be read only once"
        )
        self.assertEqual(
            status["fields"]["rf_strengthen_switch"]["raw"],
            status["fields"]["low_power_warn_switch"]["raw"],
        )

    def test_status_decodes_known_value(self):
        dev = FakeDev(data={0x0898: b"\x02"})
        status = probe.build_status(dev, report7_window=0.01)
        self.assertEqual(status["fields"]["dpi_current"]["value"], 2)
        self.assertEqual(status["fields"]["dpi_current"]["raw"], "02")
        self.assertEqual(status["fields"]["dpi_current"]["addr"], "0x0898")

    def test_status_button_hypothesis_4b_method(self):
        # Explicit unknown method (not FakeDev's address-derived default) so
        # the decode path is exercised regardless of the fake's behavior.
        dev = FakeDev(data={0x0600: bytes.fromhex("00ff0102")})
        status = probe.build_status(dev, report7_window=0.01)
        buttons = status["hypothesis"]["buttons"]
        self.assertEqual(len(buttons), 13)
        left = next(b for b in buttons if b["name"] == "mouse_left")
        self.assertEqual(left["addr"], "0x0600")
        self.assertEqual(left["raw"], "00FF0102")
        self.assertIsNone(left["fn"])
        self.assertFalse(left["left_click"])

    def test_status_button_hypothesis_decodes_real_method(self):
        from src.rapoo_vt7 import buttons

        dev = FakeDev(data={0x0600: bytes.fromhex("03000100")})
        status = probe.build_status(dev, report7_window=0.01)
        left = next(
            b for b in status["hypothesis"]["buttons"] if b["name"] == "mouse_left"
        )
        self.assertEqual(left["raw"], "03000100")
        self.assertEqual(left["fn"], "mouse_left")
        self.assertTrue(left["left_click"])

    def test_status_shared_byte_hypothesis(self):
        dev = FakeDev(data={0x08D8: b"\x05"})
        status = probe.build_status(dev, report7_window=0.01)
        shared = status["hypothesis"]["shared_0x08D8"]
        self.assertEqual(shared["raw"], 5)
        self.assertEqual(shared["bits"], "0b00000101")
        self.assertTrue(shared["rf_strengthen_switch"])
        self.assertFalse(shared["low_power_warn_switch"])

    def test_status_params_classified_from_registry(self):
        dev = FakeDev(
            data={
                0x0885: b"\x01",   # motion_sync on (editable)
                0x08C5: b"\x00",   # glass_track off (editable)
                0x08DA: b"\x01",   # dc_switch on (editable)
                0x08C3: b"\x03",   # linear_ripple numeric (read-only)
                0x08C0: b"\x1E",   # press_debounce ms (read-only)
            }
        )
        status = probe.build_status(dev, report7_window=0.01)
        params = {p["name"]: p for p in status["hypothesis"]["params"]}
        self.assertEqual(len(params), len(parameters.PARAMS))
        for name, _o, editable in parameters.PARAMS:
            with self.subTest(param=name):
                self.assertIn(name, params)
                self.assertEqual(params[name]["editable"], editable)
                self.assertEqual(
                    params[name]["state"],
                    "on" if editable and params[name]["raw"]
                    else "off" if editable
                    else "raw",
                )
        self.assertEqual(params["motion_sync"]["state"], "on")
        self.assertEqual(params["glass_track"]["state"], "off")
        self.assertEqual(params["dc_switch"]["state"], "on")
        self.assertEqual(params["linear_ripple"]["state"], "raw")
        self.assertEqual(params["press_debounce"]["addr"], "0x08C0")

    def test_status_section_c_never_in_generic_toggles(self):
        dev = FakeDev()
        status = probe.build_status(dev, report7_window=0.01)
        toggle_names = {t["name"] for t in status["hypothesis"]["toggles"]}
        section_c = {name for name, _o, _e in parameters.PARAMS}
        self.assertEqual(
            toggle_names & section_c,
            set(),
            "§C bytes must be reported once, by the params block",
        )

    def test_status_cross_validation_match(self):
        dev = FakeDev(
            data={
                0x0898: b"\x01",                       # dpi_current = 1
                0x0888 + 2 * 1: b"\x88\x13",           # dpi_x_list[1] = 5000
                0x08C8 + 2 * 1: b"\x88\x13",           # dpi_y_list[1] = 5000
                0x0880: b"\x01",                       # rateCode 1000 Hz
            },
            report=self.report7(gear=1, dpi_x=5000, dpi_y=5000, rptusb=1),
        )
        status = probe.build_status(dev, report7_window=0.01)
        self.assertEqual(
            {c["field"]: c["match"] for c in status["checks"]},
            {
                "dpi_current": "MATCH",
                "dpi_x": "MATCH",
                "dpi_y": "MATCH",
                "rpt_24g": "INFO",
                "rpt_usb": "INFO",
                "rate_mirror": "MATCH",
            },
        )

    def test_status_cross_validation_mismatch(self):
        dev = FakeDev(
            data={
                0x0898: b"\x02",                       # dpi_current = 2
                0x0888 + 2 * 1: b"\x00\x00",           # dpi_x_list[1] != report
                0x08C8 + 2 * 1: b"\x00\x00",
                0x0880: b"\x08",                       # rateCode 125 Hz
            },
            report=self.report7(gear=1, dpi_x=5000, dpi_y=5000, rptusb=1),
        )
        status = probe.build_status(dev, report7_window=0.01)
        self.assertEqual(
            {c["field"]: c["match"] for c in status["checks"]},
            {
                "dpi_current": "MISMATCH",
                "dpi_x": "MISMATCH",
                "dpi_y": "MISMATCH",
                "rpt_24g": "INFO",
                "rpt_usb": "INFO",
                "rate_mirror": "MISMATCH",
            },
        )

    def test_status_rate_mirror_validates_rpt_usb_against_0x0880(self):
        # Story 3-2: rpt_usb IS the rateCode from 0x0880 (validated on the
        # device). The tool must flag a broken mirror, not print it as INFO.
        dev = FakeDev(
            data={0x0880: b"\x01"},                   # rateCode 1000 Hz
            report=self.report7(rptusb=1),
        )
        status = probe.build_status(dev, report7_window=0.01)
        rate = next(c for c in status["checks"] if c["field"] == "rate_mirror")
        self.assertEqual(rate["match"], "MATCH")
        self.assertEqual(rate["eeprom"], 1)
        self.assertEqual(rate["report7"], 1)

    def test_status_gear_out_of_range_is_unverified(self):
        dev = FakeDev(
            data={
                0x0898: b"\x63",               # dpi_current = 99
                0x0880: b"\x01",
            },
            report=self.report7(gear=99, dpi_x=5000, dpi_y=5000, rptusb=1),
        )
        status = probe.build_status(dev, report7_window=0.01)
        self.assertEqual(
            {c["field"]: c["match"] for c in status["checks"]},
            {
                "dpi_current": "MATCH",
                "dpi_x": "UNVERIFIED",
                "dpi_y": "UNVERIFIED",
                "rpt_24g": "INFO",
                "rpt_usb": "INFO",
                "rate_mirror": "MATCH",
            },
        )

    def test_status_no_report_marker(self):
        dev = FakeDev()
        status = probe.build_status(dev, report7_window=0.01)
        self.assertIsNone(status["report7"])
        self.assertEqual(status["checks"], [])
        self.assertIn("fields", status)

    def test_status_short_reply_raises_value_error(self):
        dev = FakeDev()

        def short(addr, length):
            resp = bytearray(protocol.EEPROM_DATA_OFFSET + 3)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = short
        with self.assertRaises(ValueError):
            probe.build_status(dev, report7_window=0.01)

    def test_status_command_timeout_propagates(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with self.assertRaises(CommandTimeout):
            probe.build_status(dev, report7_window=0.01)

    def test_status_main_timeout_returns_1(self):
        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev):
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 1)

    def test_status_main_device_open_error_returns_1(self):
        class OpenFails:
            def open(self):
                raise DeviceNotFound("not found")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenFails()):
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 1)

    def test_status_main_oserror_returns_1(self):
        dev = FakeDev()

        def boom(addr, length):
            raise OSError("busy")

        dev.read_eeprom = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev):
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 1)

    def test_status_main_short_reply_returns_1(self):
        dev = FakeDev()

        def short(addr, length):
            resp = bytearray(protocol.EEPROM_DATA_OFFSET + 3)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = short
        with mock.patch.object(probe, "RapooDevice", return_value=dev):
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 1)

    def test_status_main_happy_prints_fields(self):
        dev = FakeDev(data={0x0898: b"\x01"})
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 0)
        self.assertIn("dpi_current", out.getvalue())
        self.assertIn("0x0898", out.getvalue())

    def test_status_main_renders_report7_crosscheck(self):
        dev = FakeDev(
            data={0x0898: b"\x01"},
            report=self.report7(gear=1, dpi_x=5000, dpi_y=5000),
        )
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.status_main(report7_window=0.01)
        self.assertEqual(rc, 0)
        self.assertIn("report7 raw: 07", out.getvalue())
        self.assertIn("-> MATCH", out.getvalue())

    def test_main_status_and_dump_flags_are_mutually_exclusive(self):
        with mock.patch.object(sys, "argv", ["probe", "--dump", "--status"]):
            with self.assertRaises(SystemExit):
                probe.main()

    def test_main_status_flag_runs_status(self):
        dev = FakeDev(data={0x0898: b"\x01"})
        with mock.patch.object(sys, "argv", ["probe", "--status"]), \
                mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(probe, "capture_report7", return_value=None), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertIn("dpi_current", out.getvalue())


class DumpMainTest(unittest.TestCase):
    def test_dump_timeout_aborts_and_preserves_previous(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("previous")

        dev = FakeDev()

        def boom(addr, length):
            raise CommandTimeout("asleep")

        dev.read_eeprom = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(probe.settings, "EEPROM_BASELINE_PATH", path):
            rc = probe.dump_main()
        self.assertEqual(rc, 1)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "previous")

    def test_dump_oserror_aborts_and_preserves_previous(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("previous")

        dev = FakeDev()
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(
                    probe.os, "makedirs", side_effect=OSError("read-only")
                ), mock.patch.object(probe.settings, "EEPROM_BASELINE_PATH", path):
            rc = probe.dump_main()
        self.assertEqual(rc, 1)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "previous")

    def test_happy_dump_writes_file(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")

        dev = FakeDev()
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(probe.settings, "EEPROM_BASELINE_PATH", path):
            rc = probe.dump_main()
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["blocks"]), 43)

    def test_main_dump_flag_runs_dump(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")

        dev = FakeDev()
        with mock.patch.object(sys, "argv", ["probe", "--dump"]), \
                mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(probe.settings, "EEPROM_BASELINE_PATH", path):
            rc = probe.main()
        self.assertEqual(rc, 0)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["blocks"]), 43)

    def test_dump_device_open_error_returns_1(self):
        class OpenFails:
            def open(self):
                raise DeviceNotFound("not found")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenFails()):
            rc = probe.dump_main()
        self.assertEqual(rc, 1)

    def test_dump_short_reply_returns_1(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "eeprom_baseline.json")

        dev = FakeDev()

        def short(addr, length):
            resp = bytearray(protocol.EEPROM_DATA_OFFSET + 3)
            resp[0] = protocol.REPORT_CMD
            resp[1] = protocol.RESP_ACK
            return bytes(resp)

        dev.read_eeprom = short
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(probe.settings, "EEPROM_BASELINE_PATH", path):
            rc = probe.dump_main()
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(path))


class PairDiscoverMainTest(unittest.TestCase):
    def test_main_pair_discover_flag_runs_discovery(self):
        dev = FakeDev(data={0x0000: b"\xAE\x24", 0x0004: b"\x13\x46"})
        with mock.patch.object(sys, "argv", ["probe", "--pair-discover"]), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0.01"}, clear=False
                ), mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertIn("VID: 24AE", out.getvalue())
        self.assertIn("PID: 4613", out.getvalue())
        self.assertIn("3-step pairing flow", out.getvalue())
        self.assertLess(
            out.getvalue().index("3-step pairing flow"),
            out.getvalue().index("Raw reports"),
            "3-step flow must print before the listen window so the human can act",
        )

    def test_main_pair_discover_refuses_destructive(self):
        with mock.patch.object(probe, "RapooDevice") as mdev, \
                mock.patch.object(
                    sys, "argv", ["probe", "--pair-discover", "--start-match"]
                ), mock.patch("sys.stderr", new=io.StringIO()):
            rc = probe.main()
        self.assertEqual(rc, 2)
        mdev.assert_not_called()

    def test_main_pair_discover_and_dump_mutually_exclusive(self):
        with mock.patch.object(
            sys, "argv", ["probe", "--pair-discover", "--dump"]
        ):
            with self.assertRaises(SystemExit):
                probe.main()

    def test_main_pair_discover_zero_window_refused(self):
        class TtyStdin:
            def isatty(self):
                return True

        with mock.patch.object(sys, "stdin", TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0"}, clear=False
                ), mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--pair-discover", "--start-match",
                     "--i-understand-risks"],
                ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("must be positive", err.getvalue())


class PairRunMainTest(unittest.TestCase):
    class TtyStdin:
        def isatty(self):
            return True

    def test_run_sends_frames_and_prints_result_history(self):
        dev = RunFakeDev(a7=0)
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_run_main(window=0.01, rf_bytes=b"\x01\x02\x03\x04")
        self.assertEqual(rc, 0)
        self.assertEqual(
            dev.sent,
            [
                (protocol.PAIR_START_MATCH, (protocol.PAIR_MATCH_SUB,),
                 protocol.PREFIX_WIRELESS),
                (protocol.PAIR_WRITE_RF,
                 (protocol.PAIR_WRITE_RF_SUB, 1, 2, 3, 4),
                 protocol.PREFIX_WIRELESS),
            ],
        )
        text = out.getvalue()
        self.assertIn("start_match sent", text)
        self.assertIn("write_rf sent", text)
        self.assertIn("reply byte 0", text)
        self.assertIn("failed bytes observed", text)

    def test_run_flags_b1_report(self):
        dev = RunFakeDev(a7=0, report=bytes([0x07, 0xB1, 0x01]))
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_run_main(window=0.01, rf_bytes=b"\x01\x02\x03\x04")
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("0xB1 PAIRING SUCCESS", text)
        self.assertIn("SUCCESS signal observed", text)

    def test_run_no_receiver_returns_1(self):
        class OpenFails:
            def open(self, prefix=None):
                raise DeviceNotFound("not found")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenFails()), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_run_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("receiver", err.getvalue())
        self.assertIn("not found", err.getvalue())

    def test_run_open_other_error_returns_1(self):
        class OpenErrors:
            def open(self, prefix=None):
                raise OSError("boom")

            def close(self):
                pass

        with mock.patch.object(probe, "RapooDevice", return_value=OpenErrors()), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_run_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertTrue(err.getvalue().strip())

    def test_run_listen_oserror_returns_1(self):
        dev = RunFakeDev(a7=0)

        def boom(timeout=0.5):
            raise OSError("unplugged")

        dev.read_report = boom
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_run_main(window=0.01)
        self.assertEqual(rc, 1)
        self.assertIn("listen read failed", err.getvalue())

    def test_run_refuses_when_receiver_never_answers_gate(self):
        # F9: the readiness gate refuses BEFORE any destructive frame when the
        # receiver never answers the 0xA7 probe.
        dev = RunFakeDev(a7=0, a7_error=CommandTimeout("asleep"))
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out, \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.pair_run_main(window=0.01)
        self.assertEqual(rc, 1, "an unresponsive receiver must refuse the run")
        self.assertIn("no response (attempt 1/3)", err.getvalue())
        self.assertIn("REFUSED", err.getvalue())
        self.assertEqual(dev.sent, [], "no destructive frame may be sent")

    def test_run_nonzero_without_b1_is_success(self):
        dev = RunFakeDev(a7=0x03)
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.pair_run_main(window=0.01)
        self.assertEqual(rc, 0)
        self.assertIn("non-zero 0xA7 bytes observed", out.getvalue())

    def test_main_pair_run_zero_window_refused(self):
        with mock.patch.object(sys, "stdin", self.TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0"}, clear=False
                ), mock.patch.object(
                    sys, "argv", ["probe", "--pair-run", "--i-understand-risks"]
                ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("must be positive", err.getvalue())

    def test_main_pair_run_refuses_without_risks(self):
        with mock.patch.object(probe, "RapooDevice") as mdev, \
                mock.patch.object(sys, "argv", ["probe", "--pair-run"]), \
                mock.patch("sys.stderr", new=io.StringIO()):
            rc = probe.main()
        self.assertEqual(rc, 2)
        mdev.assert_not_called()

    def test_main_pair_run_confirmed_runs(self):
        dev = RunFakeDev(a7=0)
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(sys, "stdin", self.TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0.01"}, clear=False
                ), mock.patch.object(
                    sys, "argv", ["probe", "--pair-run", "--i-understand-risks"]
                ), mock.patch("sys.stdout", new=io.StringIO()) as out:
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertEqual(dev.sent[0][0], protocol.PAIR_START_MATCH)
        self.assertEqual(dev.sent[1][0], protocol.PAIR_WRITE_RF)
        self.assertIn("start_match sent", out.getvalue())

    def test_main_pair_run_write_rf_override(self):
        dev = RunFakeDev(a7=0)
        with mock.patch.object(probe, "RapooDevice", return_value=dev), \
                mock.patch.object(sys, "stdin", self.TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "0.01"}, clear=False
                ), mock.patch.object(
                    sys,
                    "argv",
                    ["probe", "--pair-run", "--write-rf", "01020304",
                     "--i-understand-risks"],
                ), mock.patch("sys.stdout", new=io.StringIO()):
            rc = probe.main()
        self.assertEqual(rc, 0)
        self.assertEqual(
            dev.sent[1][1],
            (protocol.PAIR_WRITE_RF_SUB, 1, 2, 3, 4),
        )

    def test_main_pair_run_bad_window_refuses(self):
        with mock.patch.object(sys, "stdin", self.TtyStdin()), \
                mock.patch.object(probe, "_confirm_prompt", return_value="yes"), \
                mock.patch.dict(
                    os.environ, {"PROBE_PAIR_WINDOW": "xyz"}, clear=False
                ), mock.patch.object(
                    sys, "argv", ["probe", "--pair-run", "--i-understand-risks"]
                ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("PROBE_PAIR_WINDOW", err.getvalue())

    def test_main_pair_run_and_discover_mutually_exclusive(self):
        with mock.patch.object(
            sys, "argv", ["probe", "--pair-run", "--pair-discover"]
        ):
            with self.assertRaises(SystemExit):
                probe.main()

    def test_main_pair_run_modifier_requires_pair_run_or_discover(self):
        with mock.patch.object(
            sys, "argv", ["probe", "--start-match"]
        ), mock.patch("sys.stderr", new=io.StringIO()) as err:
            rc = probe.main()
        self.assertEqual(rc, 2)
        self.assertIn("only apply", err.getvalue())


if __name__ == "__main__":
    unittest.main()

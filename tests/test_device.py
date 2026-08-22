import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import device, protocol, settings
from src.rapoo_vt7.device import (
    BaselineMissingError,
    CommandTimeout,
    DeviceNotFound,
    RapooDevice,
)


class FakeClock:
    """Auto-advancing clock so the timeout tests terminate fast."""

    def __init__(self, delta=0.2):
        self.t = 0.0
        self.delta = delta

    def monotonic(self):
        self.t += self.delta
        return self.t


def make_device(prefix=protocol.PREFIX_WIRELESS):
    dev = RapooDevice(require_baseline=False)
    dev._fd = object()
    dev._prefix = prefix
    return dev


def ack_reply():
    return bytes([protocol.REPORT_CMD, protocol.RESP_ACK]) + b"\x00" * 30


def empty_reply():
    return bytes([protocol.REPORT_CMD, protocol.RESP_EMPTY]) + b"\x00" * 30


def write_report(prefix, data, addr=(0x04, 0x01)):
    """Full output report for write_eeprom: [6, prefix, 0xA5, len, lo, hi, 0, 0, ...data]."""
    return (
        bytes(
            [
                protocol.REPORT_CMD,
                prefix,
                protocol.WRITE_EEPROM,
                len(data),
                addr[0] & 0xFF,
                addr[1] & 0xFF,
                0x00,
                0x00,
            ]
        )
        + bytes(data)
    )


class WriteEepromTest(unittest.TestCase):
    def test_sends_exact_report_and_returns_ack(self):
        dev = make_device()
        ack = ack_reply()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(device.os, "read", return_value=ack):
            resp = dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_called_once_with(
            dev._fd, write_report(protocol.PREFIX_WIRELESS, bytes([0x00]))
        )
        self.assertEqual(resp, ack)

    def test_usb_prefix_uses_0xff(self):
        dev = make_device(prefix=protocol.PREFIX_USB)
        ack = ack_reply()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(device.os, "read", return_value=ack):
            resp = dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_called_once_with(
            dev._fd, write_report(protocol.PREFIX_USB, bytes([0x00]))
        )
        self.assertEqual(resp, ack)

    def test_oversize_data_raises_value_error_and_nothing_sent(self):
        dev = make_device()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ) as mselect, mock.patch.object(device.os, "read") as mread:
            with self.assertRaises(ValueError):
                dev.write_eeprom((0x04, 0x01), bytes(25))
        mwrite.assert_not_called()
        mselect.assert_not_called()
        mread.assert_not_called()

    def test_exactly_24_bytes_succeeds_with_len_24(self):
        dev = make_device()
        ack = ack_reply()
        data = bytes(24)
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(device.os, "read", return_value=ack):
            resp = dev.write_eeprom((0x04, 0x01), data)
        written = mwrite.call_args[0][1]
        self.assertEqual(written, write_report(protocol.PREFIX_WIRELESS, data))
        self.assertEqual(written[3], 24)
        self.assertEqual(written[8:], data)
        self.assertEqual(resp, ack)

    def test_zero_length_data_raises_and_nothing_sent(self):
        dev = make_device()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ) as mselect, mock.patch.object(device.os, "read") as mread:
            with self.assertRaises(ValueError):
                dev.write_eeprom((0x04, 0x01), b"")
        mwrite.assert_not_called()
        mselect.assert_not_called()
        mread.assert_not_called()

    def test_bad_address_raises_before_writing(self):
        dev = make_device()
        for addr in ((0x04,), (0x04, 0x01, 0x00, 0x00)):
            with self.subTest(addr=addr):
                with mock.patch.object(
                    device.os, "write"
                ) as mwrite, mock.patch.object(
                    device.select, "select", return_value=([dev._fd], [], [])
                ) as mselect, mock.patch.object(device.os, "read") as mread:
                    with self.assertRaises(ValueError):
                        dev.write_eeprom(addr, bytes([0x00]))
                mwrite.assert_not_called()
                mselect.assert_not_called()
                mread.assert_not_called()

    def test_no_ack_raises_command_timeout_without_replay(self):
        dev = make_device()
        clock = FakeClock()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([], [], [])
        ), mock.patch.object(device.os, "read") as mread, mock.patch.object(
            device.time, "monotonic", clock.monotonic
        ):
            with self.assertRaises(CommandTimeout):
                dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_called_once()
        mread.assert_not_called()

    def test_asleep_empty_reply_raises_command_timeout_without_replay(self):
        dev = make_device()
        clock = FakeClock()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(
            device.os, "read", return_value=empty_reply()
        ), mock.patch.object(device.time, "monotonic", clock.monotonic):
            with self.assertRaises(CommandTimeout):
                dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_called_once()

    def test_two_candidates_timeout_sends_frame_exactly_once(self):
        # Regression (retro epic-1 F2): with BOTH interfaces as candidates, a
        # timed-out write must NOT be replayed on the other interface (the
        # way query() falls back) — the destructive frame leaves exactly
        # once, then CommandTimeout surfaces.
        dev = make_device()
        dev._candidates = [
            ("/dev/hidraw2", protocol.PREFIX_WIRELESS),
            ("/dev/hidraw9", protocol.PREFIX_USB),
        ]
        dev._active = 0
        clock = FakeClock()
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([], [], [])
        ), mock.patch.object(device.os, "read") as mread, mock.patch.object(
            device.time, "monotonic", clock.monotonic
        ):
            with self.assertRaises(CommandTimeout):
                dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        self.assertEqual(mwrite.call_count, 1)
        mread.assert_not_called()


class WriteEepromVerifyTest(unittest.TestCase):
    def test_match_returns_readback(self):
        dev = make_device()
        data = bytes([0xAA, 0xBB, 0xCC])
        read_reply = (
            bytes([protocol.REPORT_CMD, protocol.RESP_ACK])
            + b"\x00\x00\x00"
            + data
        )
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(
            device.os, "read", side_effect=[ack_reply(), read_reply]
        ):
            readback = dev.write_eeprom_verify((0x98, 0x08), data)
        self.assertEqual(readback, data)
        writes = mwrite.call_args_list
        self.assertEqual(len(writes), 2)
        self.assertEqual(
            writes[0].args,
            (
                dev._fd,
                write_report(protocol.PREFIX_WIRELESS, data, addr=(0x98, 0x08)),
            ),
        )
        self.assertEqual(
            writes[1].args,
            (
                dev._fd,
                bytes(
                    [
                        protocol.REPORT_CMD,
                        protocol.PREFIX_WIRELESS,
                        protocol.READ_EEPROM,
                        3,
                        0x98,
                        0x08,
                    ]
                ),
            ),
        )

    def test_mismatch_raises_value_error_after_write_applied(self):
        dev = make_device()
        data = bytes([0xAA, 0xBB, 0xCC])
        read_reply = (
            bytes([protocol.REPORT_CMD, protocol.RESP_ACK])
            + b"\x00\x00\x00"
            + bytes([0x11, 0x22, 0x33])
        )
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(
            device.os, "read", side_effect=[ack_reply(), read_reply]
        ):
            with self.assertRaises(ValueError):
                dev.write_eeprom_verify((0x98, 0x08), data)
        writes = mwrite.call_args_list
        self.assertEqual(len(writes), 2)
        self.assertEqual(
            writes[0].args,
            (
                dev._fd,
                write_report(protocol.PREFIX_WIRELESS, data, addr=(0x98, 0x08)),
            ),
        )
        self.assertEqual(
            writes[1].args,
            (
                dev._fd,
                bytes(
                    [
                        protocol.REPORT_CMD,
                        protocol.PREFIX_WIRELESS,
                        protocol.READ_EEPROM,
                        3,
                        0x98,
                        0x08,
                    ]
                ),
            ),
        )

    def test_short_readback_raises_value_error(self):
        dev = make_device()
        data = bytes([0xAA, 0xBB, 0xCC])
        read_reply = bytes([protocol.REPORT_CMD, protocol.RESP_ACK, 0x00])
        with mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(
            device.os, "read", side_effect=[ack_reply(), read_reply]
        ):
            with self.assertRaises(ValueError):
                dev.write_eeprom_verify((0x98, 0x08), data)
        self.assertEqual(mwrite.call_count, 2)


class OpenPrefixFilterTest(unittest.TestCase):
    """The receiver-only selection (D1a): open(prefix=...) must filter the
    _scan() candidates by protocol prefix and raise DeviceNotFound when no
    candidate matches — the USB-cable mouse (prefix 0xFF) is never opened."""

    def _candidates(self, pairs):
        return [(path, prefix) for path, prefix in pairs]

    def test_open_with_prefix_wireless_selects_receiver(self):
        dev = RapooDevice()
        dev._scan = lambda: self._candidates(
            [
                ("/dev/hidraw3", protocol.PREFIX_USB),
                ("/dev/hidraw2", protocol.PREFIX_WIRELESS),
            ]
        )
        with mock.patch.object(device.os, "open", return_value=7):
            dev.open(prefix=protocol.PREFIX_WIRELESS)
        self.assertEqual(dev.path, "/dev/hidraw2")
        self.assertEqual(dev._prefix, protocol.PREFIX_WIRELESS)
        self.assertEqual(dev._active, 0)
        dev.close()

    def test_open_with_prefix_usb_selects_cable_mouse(self):
        dev = RapooDevice()
        dev._scan = lambda: self._candidates(
            [
                ("/dev/hidraw3", protocol.PREFIX_USB),
                ("/dev/hidraw2", protocol.PREFIX_WIRELESS),
            ]
        )
        with mock.patch.object(device.os, "open", return_value=7):
            dev.open(prefix=protocol.PREFIX_USB)
        self.assertEqual(dev.path, "/dev/hidraw3")
        self.assertEqual(dev._prefix, protocol.PREFIX_USB)
        dev.close()

    def test_open_with_prefix_missing_raises_device_not_found(self):
        dev = RapooDevice()
        dev._scan = lambda: self._candidates(
            [("/dev/hidraw3", protocol.PREFIX_USB)]
        )
        with mock.patch.object(device.os, "open") as mopen:
            with self.assertRaises(DeviceNotFound):
                dev.open(prefix=protocol.PREFIX_WIRELESS)
        mopen.assert_not_called()

    def test_open_default_prefers_usb_cable_over_receiver(self):
        dev = RapooDevice()
        dev._scan = lambda: self._candidates(
            [
                ("/dev/hidraw2", protocol.PREFIX_WIRELESS),
                ("/dev/hidraw3", protocol.PREFIX_USB),
            ]
        )
        with mock.patch.object(device.os, "open", return_value=7):
            dev.open()
        self.assertEqual(dev.path, "/dev/hidraw3")
        self.assertEqual(dev._prefix, protocol.PREFIX_USB)
        dev.close()

    def test_open_default_no_candidate_raises_device_not_found(self):
        dev = RapooDevice()
        dev._scan = lambda: []
        with self.assertRaises(DeviceNotFound):
            dev.open()


class BaselineGateTest(unittest.TestCase):
    """Golden rule (epic-1 F1): the app refuses EEPROM writes while no
    restorable baseline exists. The gate fires before any I/O; diagnostic
    tools opt out via `require_baseline=False`."""

    def test_write_refused_without_baseline_and_nothing_sent(self):
        dev = make_device()
        dev._require_baseline = True
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=False
        ), mock.patch.object(device.os, "write") as mwrite:
            with self.assertRaises(BaselineMissingError):
                dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_not_called()

    def test_error_message_is_localized(self):
        dev = make_device()
        dev._require_baseline = True
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=False
        ):
            with self.assertRaises(BaselineMissingError) as ctx:
                dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        self.assertEqual(str(ctx.exception), device.i18n.tr("baseline_missing"))

    def test_write_allowed_when_baseline_exists(self):
        dev = make_device()
        dev._require_baseline = True
        ack = ack_reply()
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=True
        ), mock.patch.object(device.os, "write") as mwrite, mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(device.os, "read", return_value=ack):
            resp = dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        mwrite.assert_called_once()
        self.assertEqual(resp, ack)

    def test_require_baseline_false_bypasses_the_gate(self):
        dev = RapooDevice(require_baseline=False)
        dev._fd = object()
        dev._prefix = protocol.PREFIX_WIRELESS
        ack = ack_reply()
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=False
        ), mock.patch.object(device.os, "write"), mock.patch.object(
            device.select, "select", return_value=([dev._fd], [], [])
        ), mock.patch.object(device.os, "read", return_value=ack):
            resp = dev.write_eeprom((0x04, 0x01), bytes([0x00]))
        self.assertEqual(resp, ack)

    def test_verify_gate_fires_before_any_io(self):
        dev = make_device()
        dev._require_baseline = True
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=False
        ), mock.patch.object(device.os, "write") as mwrite:
            with self.assertRaises(BaselineMissingError):
                dev.write_eeprom_verify((0x04, 0x01), bytes([0x00]))
        mwrite.assert_not_called()

    def test_gate_runs_before_payload_validation(self):
        dev = make_device()
        dev._require_baseline = True
        with mock.patch.object(
            device.settings, "baseline_exists", return_value=False
        ):
            # Even an invalid payload surfaces the baseline error first: the
            # golden rule is the outermost precondition of every write.
            with self.assertRaises(BaselineMissingError):
                dev.write_eeprom((0x04,), b"")


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import device, protocol
from src.rapoo_vt7.device import CommandTimeout, RapooDevice


class FakeClock:
    """Auto-advancing clock so the timeout tests terminate fast."""

    def __init__(self, delta=0.2):
        self.t = 0.0
        self.delta = delta

    def monotonic(self):
        self.t += self.delta
        return self.t


def make_device(prefix=protocol.PREFIX_WIRELESS):
    dev = RapooDevice()
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


if __name__ == "__main__":
    unittest.main()

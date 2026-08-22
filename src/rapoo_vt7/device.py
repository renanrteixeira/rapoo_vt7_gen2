import errno
import fcntl
import glob
import os
import select
import struct
import time

from . import i18n, protocol, settings


class DeviceNotFound(Exception):
    pass


class DeviceOpenError(Exception):
    pass


class CommandTimeout(Exception):
    pass


class BaselineMissingError(Exception):
    """The golden rule refused an EEPROM write: no baseline file exists.

    `tools/probe.py --dump` creates the baseline. The app never writes
    without it; diagnostic tools opt out via `RapooDevice(require_baseline=
    False)` and manage their own restore logic.
    """


def _ioctl_const(direction, type_char, nr, size):
    return (direction << 30) | (ord(type_char) << 8) | (nr << 0) | (size << 16)


_HIDIOCGRDESCSIZE = _ioctl_const(2, "H", 1, 4)
_HIDIOCGRDESC = _ioctl_const(2, "H", 2, 4 + 4096)


class RapooDevice:
    def __init__(self, require_baseline=True):
        self._fd = None
        self._path = None
        self._candidates = []
        self._active = -1
        self._prefix = protocol.PREFIX_WIRELESS
        # Golden rule: the app refuses EEPROM writes until a restorable
        # baseline exists. Diagnostic tools opt out explicitly.
        self._require_baseline = require_baseline

    @staticmethod
    def _hidraw_list():
        for syspath in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
            name = os.path.basename(syspath)
            yield name, os.path.join("/dev", name), syspath

    @staticmethod
    def _pid_of(syspath):
        uevent = os.path.join(syspath, "device", "uevent")
        try:
            with open(uevent) as f:
                for line in f:
                    if line.startswith("HID_ID="):
                        return int(line.strip().rsplit(":", 1)[-1], 16)
        except OSError:
            pass
        return None

    @staticmethod
    def _is_rapoo(syspath):
        uevent = os.path.join(syspath, "device", "uevent")
        try:
            with open(uevent) as f:
                for line in f:
                    if line.startswith("HID_ID=") and "24AE" in line.upper():
                        return True
        except OSError:
            pass
        return False

    @staticmethod
    def _report_descriptor(dev_path):
        try:
            fd = os.open(dev_path, os.O_RDONLY)
        except OSError:
            return None
        try:
            size = struct.unpack(
                "I", fcntl.ioctl(fd, _HIDIOCGRDESCSIZE, struct.pack("I", 0))
            )[0]
            buf = fcntl.ioctl(fd, _HIDIOCGRDESC, struct.pack("I", size) + b"\x00" * size)
            return bytes(buf[4 : 4 + size])
        except OSError:
            return None
        finally:
            os.close(fd)

    def _scan(self):
        """Configuration interfaces (report id 6) of the 2.4G receiver and/or
        the mouse connected by USB cable. Returns a list of (path, prefix)."""
        found = []
        for name, dev, syspath in self._hidraw_list():
            if not self._is_rapoo(syspath):
                continue
            rdesc = self._report_descriptor(dev)
            if rdesc and bytes([0x85, protocol.REPORT_CMD]) in rdesc:
                pid = self._pid_of(syspath)
                prefix = (
                    protocol.PREFIX_WIRELESS
                    if pid in (None, protocol.PID)
                    else protocol.PREFIX_USB
                )
                found.append((dev, prefix))
        return found

    def find_path(self):
        candidates = self._scan()
        if not candidates:
            return None
        candidates.sort(key=lambda c: c[1] == protocol.PREFIX_USB, reverse=True)
        return candidates[0][0]

    def open(self, prefix=None):
        """Opens a configuration interface, optionally restricted to one
        protocol prefix.

        With `prefix=None` (default) the behavior is unchanged: it prefers the
        mouse over the USB cable (0x4613, prefix 0xFF) and falls back to the
        2.4G receiver (0x1413, prefix 0xA5) when no cable is present. With a
        prefix (e.g. `protocol.PREFIX_WIRELESS` for the receiver-only pairing
        discovery) the `_scan()` candidates are filtered to that prefix and
        `DeviceNotFound` is raised when none matches.
        """
        self._candidates = self._scan()
        if prefix is not None:
            self._candidates = [c for c in self._candidates if c[1] == prefix]
        if not self._candidates:
            raise DeviceNotFound(i18n.tr("device_not_found"))
        # Prefer the mouse over the USB cable (0x4613, prefix 0xFF); fall back
        # to the 2.4G receiver (0x1413, prefix 0xA5) when no cable is present.
        self._candidates.sort(key=lambda c: c[1] == protocol.PREFIX_USB, reverse=True)
        self._open_index(0)
        return self

    def _open_index(self, index):
        if self._fd is not None:
            self.close()
        path, prefix = self._candidates[index]
        try:
            self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise DeviceOpenError(i18n.tr("device_open_error", path=path)) from exc
        self._path = path
        self._prefix = prefix
        self._active = index

    def _try_next(self):
        for i in range(1, len(self._candidates) + 1):
            idx = (self._active + i) % len(self._candidates)
            try:
                self._open_index(idx)
                return True
            except DeviceOpenError:
                continue
        return False

    @property
    def path(self):
        return self._path

    @property
    def prefix(self):
        return self._prefix

    def close(self):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def send_command(self, cmd_id, args=(), prefix=None):
        if prefix is None:
            prefix = self._prefix
        payload = bytes([prefix, cmd_id]) + bytes(args)
        os.write(self._fd, bytes([protocol.REPORT_CMD]) + payload)
        return payload

    def _read_report(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r, _, _ = select.select([self._fd], [], [], 0.1)
            if not r:
                continue
            try:
                data = os.read(self._fd, 64)
            except BlockingIOError:
                continue
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    continue
                raise
            if data:
                return data
        return None

    def read_report(self, timeout=1.0):
        """Reads any raw report from the device (e.g. passive rid 7)."""
        return self._read_report(timeout)

    def read_response(self, cmd_id=None, timeout=1.0, capture_report7=()):
        """Reads the command reply (rid-6 ACK) within `timeout`.

        A passive report-7 whose sub-command byte (`data[1]`) is in
        `capture_report7` is returned instead of being discarded: during a
        pairing session the 0xA7 poll must not swallow the 0xB1
        pairing-success report that bursts in while it waits.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self._read_report(deadline - time.monotonic())
            if data is None:
                return None
            if (
                data[0] == protocol.REPORT_PASSIVE
                and len(data) > 1
                and data[1] in capture_report7
            ):
                return data
            if data[0] == protocol.REPORT_CMD and len(data) > 1:
                if data[1] == protocol.RESP_ACK:
                    return data
        return None

    def query(self, cmd_id, args=(), timeout=1.0, prefix=None, capture_report7=()):
        tried = set()
        while True:
            tried.add(self._active)
            try:
                self.send_command(cmd_id, args, prefix=prefix)
                resp = self.read_response(
                    cmd_id, timeout=timeout, capture_report7=capture_report7
                )
                if resp is None:
                    raise CommandTimeout(i18n.tr("no_response"))
                return resp
            except CommandTimeout:
                # Switch interface (receiver <-> USB cable) and try again.
                if len(self._candidates) <= 1 or len(tried) >= len(self._candidates):
                    raise
                if not self._try_next():
                    raise

    def get_battery(self):
        resp = self.query(protocol.GET_BATTERY_LEVEL, timeout=1.0)
        status = resp[protocol.BATTERY_OFFSET_STATUS]
        level = resp[protocol.BATTERY_OFFSET_LEVEL]
        return status, max(0, min(100, level))

    def get_work_mode(self):
        resp = self.query(protocol.GET_WORK_MODE, timeout=1.0)
        return resp[protocol.WORK_MODE_OFFSET]

    def get_firmware(self, fw_type=0):
        resp = self.query(protocol.GET_FIRMWARE, [fw_type & 0xFF], timeout=1.0)
        return resp

    def read_eeprom(self, addr, length=1):
        if length > 24:
            raise ValueError("read_eeprom: length max 24")
        resp = self.query(
            protocol.READ_EEPROM, [length & 0xFF, addr[0] & 0xFF, addr[1] & 0xFF],
            timeout=1.0,
        )
        return resp

    def _ensure_baseline(self):
        """Golden-rule gate: no EEPROM write without a restorable baseline.

        Runs before any validation that could still precede I/O, so a refused
        write never reaches the wire.
        """
        if self._require_baseline and not settings.baseline_exists():
            raise BaselineMissingError(i18n.tr("baseline_missing"))

    def write_eeprom(self, addr, data):
        self._ensure_baseline()
        if len(addr) != 2:
            raise ValueError("write_eeprom: addr must be 2 bytes")
        if len(data) == 0:
            raise ValueError("write_eeprom: data must not be empty")
        if len(data) > 24:
            raise ValueError("write_eeprom: data length max 24")
        args = (
            bytes([len(data)])
            + bytes([addr[0] & 0xFF, addr[1] & 0xFF])
            + b"\x00\x00"
            + bytes(data)
        )
        self.send_command(protocol.WRITE_EEPROM, args)
        resp = self.read_response(protocol.WRITE_EEPROM, timeout=1.0)
        if resp is None:
            raise CommandTimeout(i18n.tr("no_response"))
        return resp

    def write_eeprom_verify(self, addr, data):
        self.write_eeprom(addr, data)
        resp = self.read_eeprom(addr, len(data))
        readback = resp[
            protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + len(data)
        ]
        if readback != bytes(data):
            raise ValueError("write_eeprom_verify: data mismatch")
        return readback

"""Named EEPROM fields of the Rapoo VT7 with encode/decode codecs.

Pure metadata + codec module: no device import, no file/device I/O, no GUI.
Every addressable field of docs/FEATURES.md section 2 is registered in FIELDS,
with the 2-byte LE address derived from the bank-0 offsets in protocol.py.
"""

import os
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from . import protocol

EEPROM_BASELINE_PATH = os.path.expanduser(
    "~/.cache/rapoo-vt7/eeprom_baseline.json"
)

FIELD_TYPES = ("uint", "bool", "string")


@dataclass(frozen=True)
class Field:
    addr: Tuple[int, int]
    size: int = 1
    type: str = "uint"
    range: Optional[Tuple[int, int]] = None
    validator: Optional[Callable[[int], bool]] = None

    def encode(self, value):
        """Encodes `value` into `size` bytes (little-endian).

        - uint/bool: range and validator -> ValueError; value must fit size.
        - string: utf-8, padded with NUL or truncated to `size` bytes.
        """
        if self.type not in FIELD_TYPES:
            raise ValueError("unknown field type {!r}".format(self.type))
        if self.type == "string":
            raw = str(value).encode("utf-8")
            if len(raw) >= self.size:
                return raw[: self.size].decode("utf-8", errors="ignore").encode(
                    "utf-8"
                )
            return raw + b"\x00" * (self.size - len(raw))
        if self.type == "bool":
            value = 1 if value else 0
        if not isinstance(value, int) or value < 0 or value >= (1 << (8 * self.size)):
            raise ValueError(
                "value {!r} does not fit in {}-byte {} field".format(
                    value, self.size, self.type
                )
            )
        if self.range is not None and not (self.range[0] <= value <= self.range[1]):
            raise ValueError(
                "value {!r} out of range {}".format(value, self.range)
            )
        if self.validator is not None and not self.validator(value):
            raise ValueError(
                "value {!r} rejected by field validator".format(value)
            )
        return value.to_bytes(self.size, "little")

    def decode(self, raw):
        """Decodes `raw` bytes without validation (uint LE / bool / string)."""
        raw = bytes(raw)
        if self.type == "string":
            return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        if self.type == "bool":
            return len(raw) > 0 and raw[0] != 0
        return int.from_bytes(raw[: self.size], "little")


def _addr(offset):
    return tuple(protocol.eeprom_bank0(offset))


FIELDS = {
    # A. DPI: dpi_x_list/dpi_y_list are 2-byte LE value tables (50..26000 step
    #    50); dpi_current is the 1-byte current-gear index, dpi_enable_gear a
    #    1-byte count of active gears minus 1 (compact list — the physical DPI
    #    button cycles the first (enable+1) slots of the X/Y tables).
    "dpi_x_list": Field(_addr(protocol.MOUSE_DPI_X_LIST), size=2, range=(50, 26000)),
    "dpi_y_list": Field(_addr(protocol.MOUSE_DPI_Y_LIST), size=2, range=(50, 26000)),
    "dpi_current": Field(_addr(protocol.MOUSE_DPI_CUR)),
    "dpi_enable_gear": Field(_addr(protocol.MOUSE_DPI_ENABLE_GEAR)),
    # B. Performance / sensor
    "sensor_mode": Field(_addr(protocol.SENSOR_MODE)),
    "mouse_report": Field(_addr(protocol.MOUSE_REPORT)),
    "mouse_scan": Field(_addr(protocol.MOUSE_SCAN)),
    "mouse_slight": Field(_addr(protocol.MOUSE_SLIGHT)),
    "mouse_motion": Field(_addr(protocol.MOUSE_MOTION)),
    # RF strategy and low-power warning SHARE one EEPROM byte at 0x08D8
    # (RF_STRENGTHEN_SWITCH and LOW_POWE_WARN_SWITCH are the same address).
    # Reads are identical; writes are bit-masked (protocol.RF_STRENGTHEN_MASK /
    # LOW_POWE_WARN_MASK) so one field never zeroes the other's bits, and they
    # must be confirmed by re-reading the byte.
    "rf_strengthen_switch": Field(_addr(protocol.RF_STRENGTHEN_SWITCH)),
    "low_power_warn_switch": Field(_addr(protocol.LOW_POWE_WARN_SWITCH)),
    # C. Mouse parameters
    "mouse_downdelay": Field(_addr(protocol.MOUSE_DOWNDELAY)),
    "mouse_liftdelay": Field(_addr(protocol.MOUSE_LIFTDELAY)),
    "mouse_sleeptime": Field(_addr(protocol.MOUSE_SLEEPTIME)),
    "mouse_linear_ripple": Field(_addr(protocol.MOUSE_LINEAR_RIPPLE)),
    "mouse_sensorangle": Field(_addr(protocol.MOUSE_SENSORANGLE)),
    "mouse_glass": Field(_addr(protocol.MOUSE_GLASS)),
    "mouse_lowpower": Field(_addr(protocol.MOUSE_LOWPOWER)),
    "mouse_powersave": Field(_addr(protocol.MOUSE_POWERSAVE)),
    "mouse_dcswitch": Field(_addr(protocol.MOUSE_DCSWITCH)),
    # D. Button remap (formats to validate -> default size 1/uint)
    "mouse_left": Field(_addr(protocol.MOUSE_LEFT)),
    "mouse_middle": Field(_addr(protocol.MOUSE_MID)),
    "mouse_right": Field(_addr(protocol.MOUSE_RIGHT)),
    "mouse_dpi_add": Field(_addr(protocol.MOUSE_CPIADD)),
    "mouse_dpi_reduce": Field(_addr(protocol.MOUSE_CPIREDUCE)),
    "mouse_forward": Field(_addr(protocol.MOUSE_FORWARD)),
    "mouse_back": Field(_addr(protocol.MOUSE_BACK)),
    "mouse_scroll_forward": Field(_addr(protocol.MOUSE_ROLLFORWARD)),
    "mouse_scroll_back": Field(_addr(protocol.MOUSE_ROLLBACK)),
    "mouse_scroll_right": Field(_addr(protocol.MOUSE_ROLLRIGHT)),
    "mouse_scroll_left": Field(_addr(protocol.MOUSE_ROLLLEFT)),
    "mouse_bottom": Field(_addr(protocol.MOUSE_BOTTOM)),
    "mouse_ble": Field(_addr(protocol.MOUSE_BLE)),
    # E. System
    "config_name": Field(_addr(protocol.CONFIG_NAME), size=16, type="string"),
}

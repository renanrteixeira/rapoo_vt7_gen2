"""Named EEPROM fields of the Rapoo VT7 with encode/decode codecs.

Pure metadata + codec module: no device import, no file/device I/O, no GUI.
Every addressable field of docs/FEATURES.md section 2 is registered in FIELDS,
with the 2-byte LE address derived from the bank-0 offsets in protocol.py.
"""

import os
from dataclasses import dataclass
from typing import Optional, Tuple

from . import protocol

EEPROM_BASELINE_PATH = os.path.expanduser(
    "~/.cache/rapoo-vt7/eeprom_baseline.json"
)


def baseline_exists(path=None):
    """True when the EEPROM baseline file exists (golden-rule precondition).

    The golden rule: no EEPROM write before a restorable baseline exists
    (`tools/probe.py --dump` creates it). Diagnostic tools that manage their
    own restore logic opt out explicitly; the app never does.
    """
    return os.path.exists(path or EEPROM_BASELINE_PATH)

FIELD_TYPES = ("uint", "bool", "string")


@dataclass(frozen=True)
class Field:
    addr: Tuple[int, int]
    size: int = 1
    type: str = "uint"
    range: Optional[Tuple[int, int]] = None

    def encode(self, value):
        """Encodes `value` into `size` bytes (little-endian).

        - uint/bool: range -> ValueError; value must fit size.
        - string: UTF-8, NUL-padded to exactly `size` bytes; oversize input
          and embedded NUL bytes are REJECTED with ValueError (policy aligned
          with `system.encode_name` — silent truncation could split a
          multi-byte char or drop the terminator, corrupting the field).
        """
        if self.type not in FIELD_TYPES:
            raise ValueError("unknown field type {!r}".format(self.type))
        if self.type == "string":
            try:
                raw = str(value).encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError(
                    "string value cannot be encoded as UTF-8"
                ) from None
            if b"\x00" in raw:
                raise ValueError("string value contains a NUL byte")
            if len(raw) > self.size:
                raise ValueError(
                    "string value exceeds {} bytes".format(self.size)
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
    # sensor_mode is the SLOT-0 VIEW of the 7-slot mode table 0x08DC..0x08E2
    # (one byte per polling-rate slot; the active slot is owned by
    # performance.read_mode/set_mode — a bare dump of this field shows slot 0,
    # not the active mode).
    "sensor_mode": Field(_addr(protocol.SENSOR_MODE)),
    "mouse_report": Field(_addr(protocol.MOUSE_REPORT)),
    "mouse_scan": Field(_addr(protocol.MOUSE_SCAN)),
    # mouse_slight (0x0884) is the SAME BYTE as the lift_off slider of §C
    # (parameters.PARAMS "lift_off", byte 1..11 <-> 1.0..2.0 mm). This entry
    # exists for the raw dump; the semantic owner is parameters.py.
    "mouse_slight": Field(_addr(protocol.MOUSE_SLIGHT)),
    "mouse_motion": Field(_addr(protocol.MOUSE_MOTION)),
    # RF strategy (0x08D8, bit 0) and low-power warning (0x08D9) are DISTINCT
    # bytes — P9 device diff 2026-08-20 refuted the shared-byte hypothesis.
    # Writes go through performance.write_rf_strengthen / write_low_power_warn
    # (masked write for the D8 bit; plain verified writes for D9) and must be
    # confirmed by re-reading.
    "rf_strengthen_switch": Field(_addr(protocol.RF_STRENGTHEN_SWITCH)),
    "low_power_warn_switch": Field(_addr(protocol.LOW_POWE_WARN_SWITCH)),
    # Aux byte that tracks the warning toggle in-session (FF off / 0F on);
    # standalone semantics unresolved (P9, 2026-08-20). Registered so dumps
    # and --status capture it alongside its state byte.
    "low_power_warn_aux": Field(_addr(protocol.LOW_POWE_WARN_AUX)),
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
    # D. Button remap (confirmed: each field is a 4-byte method, see buttons.py)
    "mouse_left": Field(_addr(protocol.MOUSE_LEFT), size=4),
    "mouse_middle": Field(_addr(protocol.MOUSE_MID), size=4),
    "mouse_right": Field(_addr(protocol.MOUSE_RIGHT), size=4),
    "mouse_dpi_add": Field(_addr(protocol.MOUSE_CPIADD), size=4),
    "mouse_dpi_reduce": Field(_addr(protocol.MOUSE_CPIREDUCE), size=4),
    "mouse_forward": Field(_addr(protocol.MOUSE_FORWARD), size=4),
    "mouse_back": Field(_addr(protocol.MOUSE_BACK), size=4),
    "mouse_scroll_forward": Field(_addr(protocol.MOUSE_ROLLFORWARD), size=4),
    "mouse_scroll_back": Field(_addr(protocol.MOUSE_ROLLBACK), size=4),
    "mouse_scroll_right": Field(_addr(protocol.MOUSE_ROLLRIGHT), size=4),
    "mouse_scroll_left": Field(_addr(protocol.MOUSE_ROLLLEFT), size=4),
    "mouse_bottom": Field(_addr(protocol.MOUSE_BOTTOM), size=4),
    "mouse_ble": Field(_addr(protocol.MOUSE_BLE), size=4),
    # E. System
    "config_name": Field(_addr(protocol.CONFIG_NAME), size=16, type="string"),
}

# Cross-module alias map (retro epic-1 F7 reconciliation): the §C parameters
# are registered ONCE here under their dump names; parameters.PARAMS re-expresses
# each address under its user-facing name (and buttons.BUTTONS does the same for
# the D-section button fields). These tables must never drift apart —
# tests/test_settings.py::RegistryDriftGuardTest fails when either side changes
# an address without updating the other.
PARAM_FIELD_ALIASES = {
    "motion_sync": "mouse_motion",
    "glass_track": "mouse_glass",
    "dc_switch": "mouse_dcswitch",
    "linear_ripple": "mouse_linear_ripple",
    "sensor_angle": "mouse_sensorangle",
    "press_debounce": "mouse_downdelay",
    "release_debounce": "mouse_liftdelay",
    "sleep_time": "mouse_sleeptime",
    "lift_off": "mouse_slight",
    "low_power": "mouse_lowpower",
    "power_save": "mouse_powersave",
}

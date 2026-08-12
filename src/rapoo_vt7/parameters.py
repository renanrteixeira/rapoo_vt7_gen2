"""Section-C mouse parameters of the Rapoo VT7 (Phase 3, story 3-3).

The A Hub exposes a "Parameters" group whose bytes live in EEPROM bank 0
(motion sync, glass tracking, DC switch, corrections, debounce, sleep, ...).
Each §C byte was confirmed writable on the real device on 2026-08-11 with the
golden-rule write-test (read -> write -> re-read -> restore, every byte
restored exactly).

A toggle is shipped ONLY for a field whose byte semantics the on-device
write-test confirmed as a 1-byte on/off bool:
    motion_sync 0x0885, glass_track 0x08C5, dc_switch 0x08DA
The remaining §C bytes are parameters, NOT toggles, and are exposed as
read-only state:
    linear_ripple 0x08C3  reads/takes 0x03..0 (numeric scale, not a bool)
    sensor_angle 0x08C4   numeric/manual setting, scale unconfirmed
    press/release debounce (0x08C0/0x08C1, ms), sleep_time (0x08C2, minutes),
    lift_off (0x0884, mm scale) — numeric scales
    low_power (0x08C6) / power_save (0x08AC) — two candidate addresses whose
    exact function was not resolved; writing either is guesswork
Wave correction has no confirmed address at all. None of the shipped toggles
is bit-packed, so no masked write is needed here (the shared 0x08D8 byte and
its masked writes belong to the RF feature, story 3-2).
"""

from . import protocol

# name -> (bank0 offset, editable-as-toggle).
# `editable` is True ONLY for fields whose value semantics the on-device
# write-test confirmed (bool on/off). Everything else is read-only state.
PARAMS = (
    ("motion_sync", protocol.MOUSE_MOTION, True),
    ("glass_track", protocol.MOUSE_GLASS, True),
    ("dc_switch", protocol.MOUSE_DCSWITCH, True),
    ("linear_ripple", protocol.MOUSE_LINEAR_RIPPLE, False),
    ("sensor_angle", protocol.MOUSE_SENSORANGLE, False),
    ("press_debounce", protocol.MOUSE_DOWNDELAY, False),
    ("release_debounce", protocol.MOUSE_LIFTDELAY, False),
    ("sleep_time", protocol.MOUSE_SLEEPTIME, False),
    ("lift_off", protocol.MOUSE_SLIGHT, False),
    ("low_power", protocol.MOUSE_LOWPOWER, False),
    ("power_save", protocol.MOUSE_POWERSAVE, False),
)

_PARAM_BY_NAME = {name: (offset, editable) for name, offset, editable in PARAMS}

# Documented units for the read-only numeric rows (FEATURES.md §2.C). Fields
# without a confirmed scale (lift_off mm, sensor_angle) stay unit-less.
PARAM_UNITS = {
    "press_debounce": "ms",
    "release_debounce": "ms",
    "sleep_time": "min",
}

# Selectable §C parameters, each with its A Hub slider range (min, max, step)
# in the units the A Hub shows, a map tag and a unit. A parameter listed here
# renders as a slider in the Parâmetros tab instead of a read-only row and can
# be written via `set_param_choice` (verified by read-back).
#
# Map tags (byte <-> display value):
#   "plain"  byte and display are the same number (debounce ms, sleep min)
#   "signed" byte is a signed 8-bit value (sensor angle: -30..30 -> 0xE2..0x1E)
#   "mm"     byte 1..11 -> 1.0..2.0 mm, step 0.1 (lift_off; the 0x01 factory
#            read maps to the 1.0 mm minimum — the scale is inferred from the
#            A Hub 1.0..2.0 step-0.1 range, not yet double-confirmed on-device)
SELECTABLE = {
    "press_debounce": (0, 32, 2, "plain", "ms"),
    "release_debounce": (0, 32, 2, "plain", "ms"),
    "sleep_time": (2, 120, 1, "plain", "min"),
    "sensor_angle": (-30, 30, 1, "signed", "°"),
    "lift_off": (1.0, 2.0, 0.1, "mm", "mm"),
}

_SIGNED_BYTE = 256


def _range_of(name):
    return SELECTABLE[name][:3]


def _map_of(name):
    return SELECTABLE[name][3]


def is_selectable(name):
    """True if a §C parameter is editable through a slider."""
    return name in SELECTABLE


def param_range(name):
    """(min, max, step) of a selectable §C parameter in display units."""
    return _range_of(name)


def param_unit(name):
    """Unit suffix of a selectable §C parameter ("" if none)."""
    return SELECTABLE[name][4]


def param_digits(name):
    """Decimal places of a selectable §C parameter's display value."""
    return 1 if _map_of(name) == "mm" else 0


def byte_to_display(name, b):
    """Converts a raw byte read to the selectable parameter's display value."""
    tag = _map_of(name)
    if tag == "signed":
        return b - _SIGNED_BYTE if b > 127 else b
    if tag == "mm":
        return 1.0 + (b - 1) * 0.1
    return b


def display_to_byte(name, value):
    """Converts a selectable parameter's display value to the raw byte.

    Raises ValueError when the value is outside the parameter's range or not
    on its step grid — anything else would be guesswork on the device.
    """
    lo, hi, step = _range_of(name)
    if not isinstance(value, (int, float)):
        raise ValueError("value %r is not numeric" % (value,))
    if value < lo or value > hi:
        raise ValueError("value %r out of range %s..%s" % (value, lo, hi))
    grid = round((value - lo) / step)
    if abs((value - lo) - grid * step) > 1e-9:
        raise ValueError("value %r not on the %s grid" % (value, step))
    tag = _map_of(name)
    if tag == "signed":
        return int(value) & 0xFF
    if tag == "mm":
        return int(round((value - 1.0) / 0.1)) + 1
    return int(value)


def choice_label(name, value):
    """Display text of a selectable §C value (scaled as the A Hub shows it)."""
    digits = param_digits(name)
    number = "%.*f" % (digits, float(value))
    unit = param_unit(name)
    return "%s %s" % (number, unit) if unit else number


def _addr(offset):
    return tuple(protocol.eeprom_bank0(offset))


def _read(dev, addr, length):
    resp = dev.read_eeprom(addr, length)
    if not hasattr(resp, "__len__"):
        raise ValueError("invalid EEPROM reply")
    if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
        raise ValueError("short EEPROM reply")
    return bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])


def is_editable(name):
    """True if a §C parameter is exposed as an editable on/off toggle."""
    return _PARAM_BY_NAME[name][1]


def param_addr(name):
    """Absolute bank-0 address of a §C parameter as a hex string."""
    return "0x{:04X}".format(protocol.EEPROM_BANK0_BASE + _PARAM_BY_NAME[name][0])


def read_param(dev, name):
    """Reads one §C parameter byte and exposes its current state.

    `value` is the decoded meaning (bool for confirmed toggles, int raw for
    read-only params). Raises ValueError on a short/invalid reply.
    """
    offset, editable = _PARAM_BY_NAME[name]
    raw = _read(dev, _addr(offset), 1)
    if len(raw) != 1:
        raise ValueError("short §C reply for %s" % name)
    if editable and raw[0] not in (0, 1):
        raise ValueError("invalid toggle value %d for %s" % (raw[0], name))
    return {
        "name": name,
        "addr": param_addr(name),
        "raw": raw[0],
        "value": bool(raw[0]) if editable else raw[0],
        "editable": editable,
    }


def read_section(dev):
    """Reads every §C parameter into one payload with isolated per-field errors.

    A single broken byte never blanks the whole section: each field either has
    its read state or an error string. ValueError-class failures (short/invalid
    replies) are isolated per field; device-level failures (CommandTimeout,
    OSError) propagate so the caller surfaces the section error.
    """
    params = {}
    errors = {}
    for name, _offset, _editable in PARAMS:
        try:
            params[name] = read_param(dev, name)
        except ValueError as exc:
            errors[name] = str(exc)
    return {"params": params, "errors": errors}


def set_param(dev, name, enabled):
    """Sets a confirmed bool parameter (0x00/0x01) and verifies by re-reading.

    Refuses to write any parameter whose semantics were not confirmed by the
    on-device write-test (read-only, never guesswork). The write is confirmed
    by an immediate read-back; a mismatch raises ValueError so the change is
    never accepted.
    """
    offset, editable = _PARAM_BY_NAME[name]
    if not editable:
        raise ValueError("parameter %s is read-only (unconfirmed semantics)" % name)
    if not isinstance(enabled, (bool, int)) or enabled not in (0, 1):
        raise ValueError("enabled must be a bool/int 0/1")
    value = 1 if enabled else 0
    raw = dev.write_eeprom_verify(_addr(offset), bytes((value,)))
    if len(raw) != 1 or raw[0] != value:
        raise ValueError("§C write not verified (read back %r)" % (list(raw),))
    return {
        "name": name,
        "addr": param_addr(name),
        "raw": value,
        "value": bool(value),
        "editable": True,
    }


def set_param_choice(dev, name, value):
    """Sets a selectable §C parameter to a display value on its A Hub range,
    verified by re-reading (a mismatch rejects the change).

    The byte is derived from the display value by `display_to_byte`, which
    refuses anything off the parameter's range/grid — guesswork is never
    written.
    """
    if name not in _PARAM_BY_NAME:
        raise KeyError(name)
    if name not in SELECTABLE:
        raise ValueError("parameter %s has no selectable options" % name)
    value = display_to_byte(name, value)
    if isinstance(value, float):
        value = int(value)
    offset, _editable = _PARAM_BY_NAME[name]
    raw = dev.write_eeprom_verify(_addr(offset), bytes((value,)))
    if len(raw) != 1 or raw[0] != value:
        raise ValueError("§C write not verified (read back %r)" % (list(raw),))
    return {
        "name": name,
        "addr": param_addr(name),
        "raw": value,
        "value": byte_to_display(name, value),
        "editable": True,
        "option": True,
    }

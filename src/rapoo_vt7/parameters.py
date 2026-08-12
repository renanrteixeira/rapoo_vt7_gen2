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

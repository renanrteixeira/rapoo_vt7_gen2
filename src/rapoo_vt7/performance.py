"""Performance-mode handling for the Rapoo VT7 (Phase 3, story 5).

The A Hub (VT_nrf54L protocol, main bundle `yh` table + MousePerformanceUtil
chunk) shows that the sensor mode is a **7-slot table** at `0x08DC..0x08E2`
(bank 0), one byte per polling-rate index::

    slot 0..6  ->  125 / 250 / 500 / 1000 / 2000 / 4000 / 8000 Hz

Each slot holds the performance-mode id **0..5**. The id->name mapping is
REVERSED vs the A Hub UI card order (the bundle's `MousePerformanceUtil`
chunk pairs the card `mode_0_*` with `id:5`, etc.):

    id 0 Office | 1 Balance (Low Power) | 2 Fire (High Performance)
    id 3 Hyper core | 4 Gaming hyper core | 5 Fury gaming

"Setting a mode" writes the id into the slot of the currently active rate;
reading the mode reads that slot. Validated on the real device (2026-08-11):
the factory table is `[0, 0, 1, 1, 3, 3, 3]` (low rates -> power saving,
high rates -> Hyper core).

The polling-rate register `MOUSE_REPORT` (`0x0880`) stores the *rateCode*
(8/4/2/1/132/130/129). Report 7's **rpt_usb** byte mirrors that code
(validated: writing 0x0880=8 -> rpt_usb becomes 8; restore -> back), and the
A Hub's own rate-change listener matches `rateCode === rpt_usb`. The rpt_24g
byte is NOT a rate code (observed constant on this device) — it is ignored.
`rate_index_from_code` maps a validated rateCode to the slot index; any other
value (including 0, which is not a code — retro epic-3 decision) falls back to
the default 1000 Hz slot.

The RF strategy bit lives in byte `0x08D8` (bit 0) and the low-power warning
in its OWN byte `0x08D9` — device-diff confirmed (P9, 2026-08-20); the old
shared-byte/bit-mask hypothesis was refuted. The A Hub warning toggle also
rewrites an aux byte `0x08DB` (FF off / 0F on), which we mirror.
`read_rf`/`write_rf_*` expose that state; writes are verified by re-reading.
"""

from . import eeprom, protocol

PERF_MODE_COUNT = 6
PERF_MODES = tuple({"index": i, "key": "perf_mode_%d" % i} for i in range(PERF_MODE_COUNT))

RATE_HZ = (125, 250, 500, 1000, 2000, 4000, 8000)
RATE_INDEX_BY_CODE = {8: 0, 4: 1, 2: 2, 1: 3, 132: 4, 130: 5, 129: 6}
RATE_CODE_BY_INDEX = {idx: code for code, idx in RATE_INDEX_BY_CODE.items()}

SLOT_DEFAULT = 3  # 1000 Hz

# Which mode ids the A Hub offers at each rate slot (key = slot index 0..6;
# export `t` of MousePerformanceUtil). UI-only — the device accepts any byte.
PERF_SELECTABLE = {
    0: (0, 1),
    1: (0, 1),
    2: (0, 1, 2),
    3: (1, 2, 3, 4, 5),
    4: (2, 3, 4, 5),
    5: (3, 4, 5),
    6: (3, 4, 5),
}


def selectable_modes(slot):
    """Mode ids selectable for a rate slot (unknown slot -> all)."""
    return PERF_SELECTABLE.get(slot, tuple(range(PERF_MODE_COUNT)))


def _addr(slot):
    if not 0 <= slot < len(RATE_HZ):
        raise ValueError("slot out of range 0..%d" % (len(RATE_HZ) - 1))
    return eeprom.bank0(protocol.SENSOR_MODE + slot)


# RF strategy byte 0x08D8 (bit 0) and low-power warning byte 0x08D9 are
# DISTINCT bytes (P9 device diff, 2026-08-20 — the old shared-byte hypothesis
# was refuted on hardware). The A Hub warning toggle also rewrites an aux
# byte 0x08DB (FF off / 0F on) whose semantics remain unresolved; we mirror
# it so the device state stays byte-identical to what the A Hub produces.
RF_ADDR = tuple(protocol.eeprom_bank0(protocol.RF_STRENGTHEN_SWITCH))
WARN_ADDR = tuple(protocol.eeprom_bank0(protocol.LOW_POWE_WARN_SWITCH))
WARN_AUX_ADDR = tuple(protocol.eeprom_bank0(protocol.LOW_POWE_WARN_AUX))


def rf_state(raw, warn_raw):
    """Decodes the 0x08D8 + 0x08D9 bytes into the RF + low-power state."""
    return {
        "addr": "0x{:04X}".format((RF_ADDR[1] << 8) | RF_ADDR[0]),
        "raw": raw,
        "warn_raw": warn_raw,
        "rf_strengthen_switch": bool(raw & protocol.RF_STRENGTHEN_MASK),
        "low_power_warn_switch": warn_raw == protocol.LOW_POWE_WARN_ON,
    }


def read_rf(dev):
    """Reads 0x08D8 (RF strategy bit) and 0x08D9 (low-power warning).

    Raises ValueError on a short/invalid reply (surfaced as an RF status error
    by the caller).
    """
    raw = eeprom.read_bytes(dev, RF_ADDR, 1)
    warn = eeprom.read_bytes(dev, WARN_ADDR, 1)
    if len(raw) != 1 or len(warn) != 1:
        raise ValueError("short RF reply")
    return rf_state(raw[0], warn[0])


def _validate_enabled(enabled):
    if not isinstance(enabled, (bool, int)) or enabled not in (0, 1):
        raise ValueError("enabled must be a bool/int 0/1")


def _write_masked_byte(dev, addr, mask, enabled):
    """Read-modify-write of `mask` on one EEPROM byte, preserving the
    unrelated bits; confirmed by re-reading, a mismatch raises ValueError.

    Accepted limitation (retro epic-3): no inter-process lock — an external
    writer (e.g. the A Hub) changing the same byte inside the read/write
    window is silently lost. Single in-app writer (BatteryMonitor.submit
    serializes); risk accepted for the cross-process case only.
    """
    _validate_enabled(enabled)
    current = eeprom.read_bytes(dev, addr, 1)[0]
    new_byte = (current & ~mask) | (mask if enabled else 0)
    raw = dev.write_eeprom_verify(addr, bytes((new_byte,)))
    if len(raw) != 1 or raw[0] != new_byte:
        raise ValueError("RF write not verified (read back %r)" % (list(raw),))
    return new_byte
    return rf_state(new_byte)


def write_rf_strengthen(dev, enabled):
    """Sets the RF strategy bit (0 adaptive, 1 maximum RF) on 0x08D8,
    preserving the byte's other bits (device-confirmed P9: bit 0 only).
    Confirmed by re-reading; raises on mismatch."""
    _write_masked_byte(dev, RF_ADDR, protocol.RF_STRENGTHEN_MASK, enabled)
    return read_rf(dev)


def write_low_power_warn(dev, enabled):
    """Sets the low-battery warning on its OWN bytes (P9 device diff
    2026-08-20): 0x08D9 = 01/00 (state) and 0x08DB = 0F/FF (aux, semantics
    unresolved — mirrored to stay byte-identical with A Hub writes). Both
    writes are verified; the returned state comes from a fresh read and any
    mismatch raises ValueError. 0x08D8 (RF) is never touched.
    """
    _validate_enabled(enabled)
    state = protocol.LOW_POWE_WARN_ON if enabled else protocol.LOW_POWE_WARN_OFF
    aux = protocol.LOW_POWE_WARN_AUX_ON if enabled else protocol.LOW_POWE_WARN_AUX_OFF
    for addr, value in ((WARN_ADDR, state), (WARN_AUX_ADDR, aux)):
        raw = dev.write_eeprom_verify(addr, bytes((value,)))
        if len(raw) != 1 or raw[0] != value:
            raise ValueError(
                "low-power write not verified (read back %r)" % (list(raw),)
            )
    final = read_rf(dev)
    if final["low_power_warn_switch"] != bool(enabled):
        raise ValueError("low-power write not reflected in re-read")
    return final


def read_perf_state(dev, slot):
    """Reads the active-slot mode plus the RF/warning bytes into one payload.

    A mode-read failure always raises (the Desempenho tab must show the tab
    error). An RF-read failure is isolated: the mode is still returned and the
    RF section reports its own error via `rf_error`.
    """
    mode = read_mode(dev, slot)
    try:
        rf = read_rf(dev)
        rf_error = None
    except Exception as exc:
        rf = None
        rf_error = str(exc)
    return {"slot": slot, "mode": mode, "rf": rf, "rf_error": rf_error}


def rate_index_from_code(code):
    """Maps a report-7 rpt_usb RATE CODE to a slot index 0..6.

    The wire carries the validated codes 8/4/2/1/132/130/129 only. Any other
    value — including 0, which is not a code (retro epic-3: "unknown or
    unavailable" semantics) — falls back to SLOT_DEFAULT (1000 Hz). The old
    raw-index passthrough (0..6) was removed: no caller ever passed a raw
    index and it silently misread 0 as the 125 Hz slot. Never raises.
    """
    if isinstance(code, int) and not isinstance(code, bool):
        return RATE_INDEX_BY_CODE.get(code, SLOT_DEFAULT)
    return SLOT_DEFAULT


def rate_hz(code):
    """Polling rate in Hz for a rate code (or raw slot index).

    Uses the validated mapping via `rate_index_from_code`; unknown codes fall
    back to the default 1000 Hz slot. This is the state shown in the UI.
    """
    return RATE_HZ[rate_index_from_code(code)]


def set_rate(dev, hz):
    """Sets the polling rate by writing its rateCode to `MOUSE_REPORT`
    (`0x0880`) and verifying by re-reading.

    `hz` must be one of `RATE_HZ`. The write is confirmed by an immediate
    read-back (a mismatch raises ValueError); report 7 mirrors the change in
    `rpt_usb` (validated on the real device). Returns the new
    {"hz", "code", "slot"} triple.
    """
    if not isinstance(hz, int) or isinstance(hz, bool) or hz not in RATE_HZ:
        raise ValueError("rate must be an int in %r" % (list(RATE_HZ),))
    slot = RATE_HZ.index(hz)
    code = RATE_CODE_BY_INDEX[slot]
    addr = tuple(protocol.eeprom_bank0(protocol.MOUSE_REPORT))
    raw = dev.write_eeprom_verify(addr, bytes((code,)))
    if len(raw) != 1 or raw[0] != code:
        raise ValueError("rate write not verified (read back %r)" % (list(raw),))
    return {"hz": hz, "code": code, "slot": slot}


def read_table(dev):
    """Reads the full 7-slot mode table (slot i = mode id)."""
    raw = eeprom.read_bytes(dev, _addr(0), len(RATE_HZ))
    return list(raw)


def read_mode(dev, slot):
    """Reads the performance-mode id for one rate slot (0..6)."""
    if not isinstance(slot, int) or not 0 <= slot < len(RATE_HZ):
        raise ValueError("slot out of range 0..%d" % (len(RATE_HZ) - 1))
    return eeprom.read_bytes(dev, _addr(slot), 1)[0]


def set_mode(dev, slot, mode):
    """Sets the mode id for a rate slot and verifies by re-reading.

    Mirrors the A Hub mode write: one 1-byte write at `0x08DC + slot`.
    """
    if not isinstance(slot, int) or not 0 <= slot < len(RATE_HZ):
        raise ValueError("slot out of range 0..%d" % (len(RATE_HZ) - 1))
    if not isinstance(mode, int) or not 0 <= mode < PERF_MODE_COUNT:
        raise ValueError("mode must be an int in 0..%d" % (PERF_MODE_COUNT - 1))
    raw = dev.write_eeprom_verify(_addr(slot), bytes((mode,)))
    if len(raw) != 1 or raw[0] != mode:
        raise ValueError("mode write not verified (read back %r)" % (list(raw),))
    return {"slot": slot, "mode": mode}

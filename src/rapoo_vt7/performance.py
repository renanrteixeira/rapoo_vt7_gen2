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
`rate_index_from_code` maps a code (or a raw 0..6 index) to the slot index.

The RF strategy byte `0x08D8` is SHARED with the low-power warning switch:
`RF_STRENGTHEN_SWITCH` and `LOW_POWE_WARN_SWITCH` are the same address, a bit
mask (bit 0 = RF strengthen, bit 1 = low-power warning). `read_rf`/`write_rf_*`
expose that state and write with a mask so the unrelated bits are preserved,
verifying by re-reading the byte.
"""

from . import protocol

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
    return tuple(protocol.eeprom_bank0(protocol.SENSOR_MODE + slot))


def _read(dev, addr, length):
    resp = dev.read_eeprom(addr, length)
    if not hasattr(resp, "__len__"):
        raise ValueError("invalid EEPROM reply")
    if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
        raise ValueError("short EEPROM reply")
    return bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])


# Shared RF byte at 0x08D8 (bank 0): RF_STRENGTHEN_SWITCH and
# LOW_POWE_WARN_SWITCH are the SAME address. The byte is a bit mask, so a
# per-field write must preserve the other field's bits and be verified by
# re-reading the whole byte.
RF_SHARED_ADDR = tuple(protocol.eeprom_bank0(protocol.RF_STRENGTHEN_SWITCH))


def rf_state(raw):
    """Decodes the shared 0x08D8 byte into the RF + low-power state."""
    return {
        "addr": "0x{:04X}".format((RF_SHARED_ADDR[1] << 8) | RF_SHARED_ADDR[0]),
        "raw": raw,
        "rf_strengthen_switch": bool(raw & protocol.RF_STRENGTHEN_MASK),
        "low_power_warn_switch": bool(raw & protocol.LOW_POWE_WARN_MASK),
    }


def read_rf(dev):
    """Reads the shared 0x08D8 byte and exposes both switches consistently.

    Raises ValueError on a short/invalid reply (surfaced as an RF status error
    by the caller).
    """
    raw = _read(dev, RF_SHARED_ADDR, 1)
    if len(raw) != 1:
        raise ValueError("short RF reply")
    return rf_state(raw[0])


def _write_shared_byte(dev, mask, enabled):
    """Writes `mask` on the shared 0x08D8 byte, preserving the unrelated bits.

    The write is confirmed by re-reading the byte; a mismatch raises ValueError
    so the change is never accepted. Only the shared byte is written.
    """
    if not isinstance(enabled, (bool, int)) or enabled not in (0, 1):
        raise ValueError("enabled must be a bool/int 0/1")
    current = _read(dev, RF_SHARED_ADDR, 1)[0]
    new_byte = (current & ~mask) | (mask if enabled else 0)
    raw = dev.write_eeprom_verify(RF_SHARED_ADDR, bytes((new_byte,)))
    if len(raw) != 1 or raw[0] != new_byte:
        raise ValueError("RF write not verified (read back %r)" % (list(raw),))
    return rf_state(new_byte)


def write_rf_strengthen(dev, enabled):
    """Sets the RF strengthen switch (0 adaptive, 1 maximum RF) preserving the
    low-power warning bits. Confirmed by re-reading; raises on mismatch."""
    return _write_shared_byte(dev, protocol.RF_STRENGTHEN_MASK, enabled)


def write_low_power_warn(dev, enabled):
    """Sets the low-battery warning switch preserving the RF strategy bits.
    Confirmed by re-reading; raises on mismatch."""
    return _write_shared_byte(dev, protocol.LOW_POWE_WARN_MASK, enabled)


def read_perf_state(dev, slot):
    """Reads the active-slot mode plus the shared RF byte into one payload.

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
    """Maps a report-7 rpt value (rateCode or raw index) to a slot index 0..6.

    Falls back to the default 1000 Hz slot when the value is unrecognized.
    Never raises (unhashable inputs fall back too).
    """
    if isinstance(code, int) and not isinstance(code, bool):
        if code in RATE_INDEX_BY_CODE:
            return RATE_INDEX_BY_CODE[code]
        if 0 <= code < len(RATE_HZ):
            return code
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
    raw = _read(dev, _addr(0), len(RATE_HZ))
    return list(raw)


def read_mode(dev, slot):
    """Reads the performance-mode id for one rate slot (0..6)."""
    if not isinstance(slot, int) or not 0 <= slot < len(RATE_HZ):
        raise ValueError("slot out of range 0..%d" % (len(RATE_HZ) - 1))
    return _read(dev, _addr(slot), 1)[0]


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

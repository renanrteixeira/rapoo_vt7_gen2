"""System-level operations of the Rapoo VT7 (Phase 5, story 9: factory reset).

The mouse exposes the `return_factory_settings` command (`0xAD`) that restores
its on-board configuration to the factory defaults — a destructive operation
that must be guarded by an explicit confirmation dialog in the GUI. This module
owns the command + the post-reset verification only; the dialog lives in
`gui.py` and the `submit(..., wake=True)` wiring in `main.py`.

Factory reset is a **command, not an EEPROM write**: it never touches
`write_eeprom`, so it does not follow the golden rule (dump before write) and
must not be gated behind a baseline-exists check. It also never touches the
baseline file (`~/.cache/rapoo-vt7/eeprom_baseline.json`).

After the `0xAD` ACK the mouse reboots, so the post-reset verification reads
the key EEPROM fields with a bounded retry (see `RESET_READ_ATTEMPTS`). The
verification compares three factory-default markers:

    MOUSE_DPI_CUR       0x0898  active gear index (factory default = gear 0)
    RF_STRENGTHEN_SWITCH 0x08D8  shared RF byte (factory default = 0x00:
                                 adaptive RF, no low-power warning)
    SENSOR_MODE         0x08DC  the 7-slot performance-mode table, whose
                                 factory content [0,0,1,1,3,3,3] was VALIDATED
                                 on the real device (2026-08-11)

The DPI-current default (gear index 0) is the natural factory state — the
first gear of the (reset) DPI table. The two other defaults are
device-validated. A reset is only reported as verified when the post-reset
state BOTH differs from the pre-reset state (the command actually changed
something) AND matches these factory defaults; either condition failing raises
`FactoryResetVerifyError`.
"""

import time

from . import protocol
from .device import CommandTimeout

# How many times the post-reset verification read is attempted, and the pause
# between attempts: after the 0xAD ACK the mouse reboots and may not answer
# the EEPROM reads for a moment. Each read already has its own 1 s device
# timeout (via `query`), so this is the outer bound of the reboot wait.
RESET_READ_ATTEMPTS = 5
RESET_READ_DELAY = 0.4

# Factory defaults the post-reset verification compares against.
#   dpi_cur: gear index 0 (first gear of the factory DPI table).
#   rf_byte: 0x00 (adaptive RF, low-power warning off) — the device read 0x00.
#   sensor_mode: the validated factory performance-mode table.
FACTORY_DPI_CUR = 0
FACTORY_RF_BYTE = 0x00
FACTORY_SENSOR_MODE = (0, 0, 1, 1, 3, 3, 3)


class FactoryResetError(ValueError):
    """Base class of the factory-reset failures surfaced to the user."""


class FactoryResetAckError(FactoryResetError):
    """The 0xAD reply was not a simple ACK (data[1] != RESP_ACK).

    The live mouse either did not answer (CommandTimeout, surfaced by the
    caller as the asleep/no-response path) or answered with an unexpected
    payload. In both cases nothing is written and the state is unchanged.
    """


class FactoryResetVerifyError(FactoryResetError):
    """The post-reset EEPROM reads did not confirm the factory defaults."""


def _addr(offset):
    return tuple(protocol.eeprom_bank0(offset))


def _read(dev, addr, length):
    resp = dev.read_eeprom(addr, length)
    if not hasattr(resp, "__len__"):
        raise ValueError("invalid EEPROM reply")
    if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
        raise ValueError("short EEPROM reply")
    return bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])


def read_verify_state(dev):
    """Reads the three factory-default markers into one payload.

    Returns {"dpi_cur", "rf_byte", "sensor_mode"} where `sensor_mode` is the
    full 7-slot table as a list. Raises ValueError/CommandTimeout on a bad
    reply — the caller retries the whole read after the reset reboot.
    """
    dpi_cur = _read(dev, _addr(protocol.MOUSE_DPI_CUR), 1)
    rf_byte = _read(dev, _addr(protocol.RF_STRENGTHEN_SWITCH), 1)
    sensor_mode = _read(dev, _addr(protocol.SENSOR_MODE), len(FACTORY_SENSOR_MODE))
    if len(dpi_cur) != 1 or len(rf_byte) != 1:
        raise ValueError("short factory-verify reply")
    return {
        "dpi_cur": dpi_cur[0],
        "rf_byte": rf_byte[0],
        "sensor_mode": list(sensor_mode),
    }


def _is_factory_state(state):
    return (
        state["dpi_cur"] == FACTORY_DPI_CUR
        and state["rf_byte"] == FACTORY_RF_BYTE
        and state["sensor_mode"] == list(FACTORY_SENSOR_MODE)
    )


def _read_verify_state_after_reset(dev, attempts, delay):
    """Re-reads the verify state with a bounded retry for the reboot.

    When every attempt fails the reset was ACKed but the mouse never answered
    the post-reset reads (reboot longer than the retry window, or it fell
    back asleep). Surface that as `FactoryResetVerifyError` — a verification
    failure — rather than leaking the raw `CommandTimeout`, which the caller
    would otherwise present as a generic "no response / mouse asleep" error.
    """
    last = None
    for i in range(attempts):
        try:
            return read_verify_state(dev)
        except (CommandTimeout, OSError, ValueError) as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(delay)
    raise FactoryResetVerifyError(
        "could not verify the reset (no post-reset response): %s" % last
    )


def factory_reset(dev, attempts=RESET_READ_ATTEMPTS, delay=RESET_READ_DELAY):
    """Sends the factory-reset command and verifies the device returned to
    the factory defaults.

    Steps:
      1. read the pre-reset verify state (the baseline of the change check),
      2. send `RETURN_FACTORY_SETTINGS` (0xAD) and require a plain ACK,
      3. re-read the verify state (retrying while the mouse reboots),
      4. verify it changed AND matches the factory defaults.

    Returns {"before", "after", "acked": True}. Raises FactoryResetAckError
    when the reply is not an ACK and FactoryResetVerifyError when the
    post-reset state does not confirm the reset (no change detected, or the
    fields are not at the factory defaults). No EEPROM is written.
    """
    before = read_verify_state(dev)
    resp = dev.query(protocol.RETURN_FACTORY_SETTINGS, timeout=1.0)
    if resp is None or len(resp) < 2 or resp[1] != protocol.RESP_ACK:
        raise FactoryResetAckError("factory reset reply was not an ACK")
    after = _read_verify_state_after_reset(dev, attempts, delay)
    if after == before:
        raise FactoryResetVerifyError("reset did not change the mouse state")
    if not _is_factory_state(after):
        raise FactoryResetVerifyError("post-reset state is not the factory defaults")
    return {"before": before, "after": after, "acked": True}
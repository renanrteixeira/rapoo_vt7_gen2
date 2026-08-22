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

The `0xAD` command carries the A Hub `returnFactory` payload
`[0x52, 0x3D, 0x00, 0x00, 0x00]` — a bare `0xAD` (no payload) is answered with
an empty reply and does nothing, as validated on the real device (2026-08-19,
story D3). With the payload the mouse answers a plain ACK and reboots.

After the `0xAD` ACK the mouse reboots — the hidraw interface changes (the
boot was observed moving hidraw8 -> hidraw9) — so the post-reset verification
re-opens the device and reads the key EEPROM fields with a bounded retry (see
`RESET_READ_ATTEMPTS`). The verification compares three factory-default
markers:

    MOUSE_DPI_CUR       0x0898  active gear index (factory default = gear 5,
                                 i.e. 6400 of the reset table — NOT gear 0)
    RF_STRENGTHEN_SWITCH 0x08D8  shared RF byte (factory default = 0x00:
                                 adaptive RF, no low-power warning)
    SENSOR_MODE         0x08DC  the 7-slot performance-mode table, whose
                                 factory content [0,0,1,2,3,3,3] was VALIDATED
                                 on the real device (2026-08-19, story D3:
                                 stable readback after the live 0xAD reset;
                                 the earlier [0,0,1,1,3,3,3] was a configured
                                 user state, not the factory default)

The factory defaults were validated by an actual on-device reset: the DPI
table returns to [400, 800, 1200, 1600, 3200, 6400, 26000] with all 7 gears
enabled (enable=6) and the active gear 5 selected. A reset is only reported
as verified when the post-reset state BOTH differs from the pre-reset state
(the command actually changed something) AND matches these factory defaults;
either condition failing raises `FactoryResetVerifyError`.

Besides the reset command, this module owns the **device-name primitives**
(story 5-2): `read_device_name`/`write_device_name` for the 16-byte
`CONFIG_NAME` field, with the A Hub `renameConfig` encoding (trim -> UTF-8
bytes -> reject > 16 / embedded NUL -> NUL-pad to exactly 16) and the golden
rule of verifying the write by an immediate re-read. The GUI surface lives in
`gui.py` (System tab) and the `submit(..., wake=True)` wiring in `main.py`.
"""

import time

from . import eeprom, i18n, protocol
from .device import CommandTimeout

# How many times the post-reset verification read is attempted, and the pause
# between attempts: after the 0xAD ACK the mouse reboots and may not answer
# the EEPROM reads for a moment. Each read already has its own 1 s device
# timeout (via `query`), so this is the outer bound of the reboot wait.
RESET_READ_ATTEMPTS = 5
RESET_READ_DELAY = 0.4

# Factory defaults the post-reset verification compares against.
#   dpi_cur: gear index 5 (the active gear of the factory DPI table — the
#            reset selects 6400, not gear 0). Validated by a live on-device
#            reset (2026-08-19, story D3).
#   rf_byte: 0x00 (adaptive RF, low-power warning off) — the device read 0x00.
#   sensor_mode: the factory performance-mode table, validated by a live
#                on-device reset: [0,0,1,2,3,3,3] (slot 3 = 2, not 1).
FACTORY_DPI_CUR = 5
FACTORY_RF_BYTE = 0x00
FACTORY_SENSOR_MODE = (0, 0, 1, 2, 3, 3, 3)

# The A Hub `returnFactory` payload. A bare 0xAD is answered with an empty
# reply and does nothing; the real reset frame is
# [prefix, 0xAD, 0x52, 0x3D, 0x00, 0x00, 0x00] (validated on the device
# 2026-08-19, story D3: ACK + reboot + factory defaults).
FACTORY_RESET_PAYLOAD = (0x52, 0x3D, 0x00, 0x00, 0x00)


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


# The device name is a fixed 16-byte NUL-padded UTF-8 field (CONFIG_NAME,
# bank 0, reads "CFG1" on the real device). Writes follow the A Hub
# `renameConfig` rule: trim -> UTF-8 bytes -> reject > 16 bytes / embedded
# NUL -> NUL-pad to exactly 16 -> write_eeprom_verify.
CONFIG_NAME_LENGTH = 16


class DeviceNameError(ValueError):
    """Base class of the device-name failures surfaced to the user.

    Named `DeviceNameError` (not `NameError`) so the module never shadows the
    Python builtin.
    """


class NameEmptyError(DeviceNameError):
    """The trimmed name is empty (blank input). Raised before any device write."""


class NameTooLongError(DeviceNameError):
    """The trimmed name exceeds the 16-byte EEPROM field. Raised before any
    device write."""


class NameVerifyError(DeviceNameError):
    """The readback after the rename write did not match the written bytes."""


def read_verify_state(dev):
    """Reads the three factory-default markers into one payload.

    Returns {"dpi_cur", "rf_byte", "sensor_mode"} where `sensor_mode` is the
    full 7-slot table as a list. Raises ValueError/CommandTimeout on a bad
    reply — the caller retries the whole read after the reset reboot.
    """
    dpi_cur = eeprom.read_bytes(dev, eeprom.bank0(protocol.MOUSE_DPI_CUR), 1)
    rf_byte = eeprom.read_bytes(dev, eeprom.bank0(protocol.RF_STRENGTHEN_SWITCH), 1)
    sensor_mode = eeprom.read_bytes(dev, eeprom.bank0(protocol.SENSOR_MODE), len(FACTORY_SENSOR_MODE))
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

    The mouse reboots after the 0xAD ACK and its hidraw path changes, so
    each attempt re-opens the device (a fresh scan picks up the new path)
    before reading. When every attempt fails the reset was ACKed but the
    mouse never answered the post-reset reads (reboot longer than the retry
    window, or it fell back asleep). Surface that as `FactoryResetVerifyError`
    — a verification failure — rather than leaking the raw `CommandTimeout`,
    which the caller would otherwise present as a generic "no response / mouse
    asleep" error.
    """
    last = None
    for i in range(attempts):
        try:
            dev.open()
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
      2. send `RETURN_FACTORY_SETTINGS` (0xAD) with the A Hub `returnFactory`
         payload and require a plain ACK,
      3. re-open the device (the mouse reboots; its hidraw path changes) and
         re-read the verify state (retrying while the mouse reboots),
      4. verify it changed AND matches the factory defaults.

    Returns {"before", "after", "acked": True}. Raises FactoryResetAckError
    when the reply is not an ACK and FactoryResetVerifyError when the
    post-reset state does not confirm the reset (no change detected, or the
    fields are not at the factory defaults). No EEPROM is written.
    """
    before = read_verify_state(dev)
    # Single-execution send/read, NOT `dev.query`: query() replays the
    # command on the other interface after a timeout, and 0xAD is destructive
    # — the mouse must receive exactly one factory-reset frame.
    dev.send_command(protocol.RETURN_FACTORY_SETTINGS, FACTORY_RESET_PAYLOAD)
    resp = dev.read_response(protocol.RETURN_FACTORY_SETTINGS, timeout=1.0)
    if resp is None:
        # No answer (mouse asleep): same semantics as query()'s timeout, but
        # WITHOUT the replay — a destructive command is sent exactly once.
        raise CommandTimeout(i18n.tr("no_response"))
    if len(resp) < 2 or resp[1] != protocol.RESP_ACK:
        raise FactoryResetAckError("factory reset reply was not an ACK")
    after = _read_verify_state_after_reset(dev, attempts, delay)
    if after == before:
        raise FactoryResetVerifyError("reset did not change the mouse state")
    if not _is_factory_state(after):
        raise FactoryResetVerifyError("post-reset state is not the factory defaults")
    return {"before": before, "after": after, "acked": True}


def encode_name(name):
    """A Hub `renameConfig` encoding of the device name.

    trim the input -> UTF-8 bytes -> reject when it exceeds the 16-byte field
    or contains an embedded NUL byte (which would silently truncate the name
    on readback) -> NUL-pad to exactly 16. Returns bytes. Raises
    `DeviceNameError` subclasses before any device I/O: `NameEmptyError` on
    blank input, `NameTooLongError` when the UTF-8 encoding is longer than 16
    bytes, and `DeviceNameError` itself on an embedded NUL byte or an
    un-encodable input (a lone surrogate from pasted clipboard text would
    otherwise escape as `UnicodeEncodeError` and crash the GTK handler — F6).
    """
    try:
        raw = str(name).strip().encode("utf-8")
    except UnicodeEncodeError:
        raise DeviceNameError("device name cannot be encoded as UTF-8") from None
    if not raw:
        raise NameEmptyError("device name is empty")
    if b"\x00" in raw:
        raise DeviceNameError("device name contains a NUL byte")
    if len(raw) > CONFIG_NAME_LENGTH:
        raise NameTooLongError("device name exceeds 16 bytes")
    return raw + b"\x00" * (CONFIG_NAME_LENGTH - len(raw))


def read_device_name(dev):
    """Reads the 16-byte device name (CONFIG_NAME, bank 0) and decodes it.

    Returns the first NUL-terminated segment as a str (UTF-8 with
    errors="replace" — a raw "CFG1" is shown as-is, no A Hub default-config
    localization). Raises ValueError/CommandTimeout on a bad reply.
    """
    raw = eeprom.read_bytes(dev, eeprom.bank0(protocol.CONFIG_NAME), CONFIG_NAME_LENGTH)
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def write_device_name(dev, name):
    """Writes the device name and verifies it by an immediate re-read.

    Golden rule: the write stays a bank-0 EEPROM write ≤ 24 B, confirmed by
    `write_eeprom_verify`. `encode_name` refuses blank / >16-byte input before
    any device access; a verify mismatch raises `NameVerifyError`. Returns the
    decoded readback name (what the mouse actually stores).
    """
    encoded = encode_name(name)
    try:
        readback = dev.write_eeprom_verify(eeprom.bank0(protocol.CONFIG_NAME), encoded)
    except ValueError as exc:
        raise NameVerifyError("device-name write did not verify") from exc
    return readback.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
"""Receiver-pairing protocol discovery (story 5-3).

The A Hub's receiver-pairing flow (`deviceMatcher`, chunk
`docs/index-B0XNTd12.js`) talks to the 2.4G receiver with three commands that
were unmapped until this story. The wire form (decision D3a) is a FULL frame
with the receiver prefix included:

    sendStartMatch     -> payload [0xA0, 0x81]            -> frame [0xA5, 0xA0, 0x81]
    sendWriteRF        -> payload [0xA1, 0x8F, rf0..rf3]  -> frame [0xA5, 0xA1, 0x8F, ...]
    sendGetMatchResult -> payload [0xA7]                  -> frame [0xA5, 0xA7]

`sendWriteRF` in the bundle draws 4 random RF bytes; here `pairing_commands`
does the same (`os.urandom(4)`) unless explicit bytes are supplied. The
WebHID reply byte 1 of `sendGetMatchResult` — hidraw `data[2]` — is `0` when
the match failed; any other value is unvalidated (🔶) and is only dumped raw,
never interpreted.

The connected-mouse poll comes from `docs/BaseSetting-CsajUb0l.js`
(`getConnectedMouseVid`/`getConnectedMousePid`): a `read_eeprom` of 2 bytes
little-endian at the raw addresses 0x0000 (VID) and 0x0004 (PID). The WebHID
bytes 4-5 are the raw `data[EEPROM_DATA_OFFSET..]`; non-zero means the
receiver has a mouse attached.

This module is DISCOVERY ONLY: it encodes the commands, builds the frames and
decodes the read-only probes. The destructive `0xA0`/`0xA1` commands are never
sent from the app; the `tools/probe.py --pair-discover` harness fires them only
behind an Ask First gate (explicit flag + TTY confirmation, never auto). It
mirrors the `system.py` `_read`/typed-error pattern.
"""

import os

from . import protocol
from .device import CommandTimeout


class PairingDiscoveryError(ValueError):
    """Base class of the receiver-pairing discovery failures surfaced to the
    caller (mirrors system.py's typed-error pattern)."""


# The physical 3-step pairing flow (A Hub locale strings
# `settings.deviceMatcher.step1/2/3`), printed by `--pair-discover` so a human
# knows what to do while the raw reports are captured.
PAIRING_FLOW = {
    "step1": (
        "Connect the receiver to the computer, then connect the mouse in "
        "wired (USB cable) mode."
    ),
    "step2": (
        "Disconnect the wired connection and power-cycle the mouse (turn its "
        "power switch off, then on again)."
    ),
    "step3": (
        "While 'matching in progress', press the LEFT + MIDDLE + RIGHT buttons "
        "simultaneously until the pairing result is reported."
    ),
}


def pairing_commands(rf_bytes=None):
    """Builds the full frames of the receiver-pairing commands.

    Returns a dict `{"start_match", "write_rf", "get_result"}` where each
    value is the FULL frame `[prefix, cmdId, ...args]` (decision D3a) — the
    exact bytes the A Hub `sendRaw`/`sendCMD` writes on output report 6 (minus
    the report id). `write_rf` uses `rf_bytes` when given (must be exactly 4
    bytes) or `os.urandom(4)` like the bundle. Raises `PairingDiscoveryError`
    on a wrong RF byte length.
    """
    if rf_bytes is None:
        rf_bytes = os.urandom(4)
    if not isinstance(rf_bytes, (bytes, bytearray, memoryview)):
        raise PairingDiscoveryError("RF bytes must be a bytes-like object")
    rf_bytes = bytes(rf_bytes)
    if len(rf_bytes) != 4:
        raise PairingDiscoveryError("RF bytes must be exactly 4 bytes")
    return {
        "start_match": [
            protocol.PREFIX_WIRELESS,
            protocol.PAIR_START_MATCH,
            protocol.PAIR_MATCH_SUB,
        ],
        "write_rf": [
            protocol.PREFIX_WIRELESS,
            protocol.PAIR_WRITE_RF,
            protocol.PAIR_WRITE_RF_SUB,
        ]
        + list(rf_bytes),
        "get_result": [
            protocol.PREFIX_WIRELESS,
            protocol.PAIR_GET_RESULT,
        ],
    }


def match_result_byte(resp):
    """Decodes the 0xA7 match-result byte (hidraw raw report `data[2]`).

    Returns the int, or None when the reply is missing, too short
    (`len <= MATCH_RESULT_OFFSET`) or not an ACK (`data[1] != RESP_ACK`) —
    never raises IndexError and never decodes garbage (mirrors
    `_decode_connected_field`). 0 = match failed (validated 2026-08-17).
    """
    if not hasattr(resp, "__len__"):
        return None
    if (
        len(resp) <= protocol.MATCH_RESULT_OFFSET
        or resp[1] != protocol.RESP_ACK
    ):
        return None
    return resp[protocol.MATCH_RESULT_OFFSET]


def _decode_connected_field(resp):
    """Decodes one 2-byte LE EEPROM field with the reply-shape guard.

    Returns the int value, or None when the reply is missing, too short
    (`len < EEPROM_DATA_OFFSET + 2`) or not an ACK (`data[1] != RESP_ACK`) —
    never raises IndexError and never decodes garbage.
    """
    if not hasattr(resp, "__len__"):
        return None
    if (
        len(resp) < protocol.EEPROM_DATA_OFFSET + 2
        or resp[1] != protocol.RESP_ACK
    ):
        return None
    return resp[protocol.EEPROM_DATA_OFFSET] | (
        resp[protocol.EEPROM_DATA_OFFSET + 1] << 8
    )


def decode_connected_vid_pid(dev):
    """Polls the connected-mouse VID (0x0000) and PID (0x0004) the receiver is
    paired to.

    Reads both 2-byte LE fields via `read_eeprom` and returns
    `{"vid": str, "pid": str}`. Each field decodes to an uppercase hex string
    ("24AE"/"4613" when attached) or "none attached" when the reply is
    short/non-ACK. A `CommandTimeout` (receiver asleep / no answer) propagates
    to the caller, which treats it as a partial probe.
    """
    vid_resp = dev.read_eeprom(protocol.CONNECTED_MOUSE_VID_ADDR, 2)
    pid_resp = dev.read_eeprom(protocol.CONNECTED_MOUSE_PID_ADDR, 2)
    vid = _decode_connected_field(vid_resp)
    pid = _decode_connected_field(pid_resp)
    return {
        "vid": "none attached" if vid is None or vid == 0 else "%04X" % vid,
        "pid": "none attached" if pid is None or pid == 0 else "%04X" % pid,
    }

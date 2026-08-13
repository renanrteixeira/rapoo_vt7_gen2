"""Button remap of the Rapoo VT7 (Phase 4, story 4-1).

Each of the 13 physical buttons has a bank-0 EEPROM field (0x0600-0x0638)
storing a **4-byte "method"**: `<type><p1><p2><p3>`. The field size and the
function codes were CONFIRMED ON DEVICE (2026-08-12): every readable button
read back the exact A Hub `method` byte-for-byte (left=03 00 01 00, DPI+=
08 00 05 00, scroll fwd=0b ff 00 ff, bottom=0a 00 00 00, ...) and a
reversible write-test on 0x0634 wrote 07 00 00 00 -> re-read verified ->
restored 0a 00 00 00 (MATCH).

The method table comes from the A Hub chunk `keyPosition-D9HhW_CA.js`
(downloaded to /tmp/opencode/ahub-chunks/). The type byte groups the
function: 0x03 mouse button, 0x08 DPI, 0x09 fire/sniper, 0x0a config/DIY,
0x0b/0x0c scroll, 0x07 disable, 0x04 media, 0x02 combo, 0x05 macro.
Keyboard keys are a single HID usage byte and combos/macros have their own
formats — those categories are NOT offered in the picker yet (their write
formats derive from the bundle and are gated until device-validated). Only
the confirmed 4-byte function methods are shippable. `METHODS` is the picker
offer list; `_DECODE_ONLY` labels read-backs (BLE left variant, gated combos)
without offering them.
"""

from . import protocol

# (name, bank0 offset) of every physical button, in address order.
BUTTONS = (
    ("mouse_left", protocol.MOUSE_LEFT),
    ("mouse_middle", protocol.MOUSE_MID),
    ("mouse_right", protocol.MOUSE_RIGHT),
    ("mouse_dpi_add", protocol.MOUSE_CPIADD),
    ("mouse_dpi_reduce", protocol.MOUSE_CPIREDUCE),
    ("mouse_forward", protocol.MOUSE_FORWARD),
    ("mouse_back", protocol.MOUSE_BACK),
    ("mouse_scroll_forward", protocol.MOUSE_ROLLFORWARD),
    ("mouse_scroll_back", protocol.MOUSE_ROLLBACK),
    ("mouse_scroll_right", protocol.MOUSE_ROLLRIGHT),
    ("mouse_scroll_left", protocol.MOUSE_ROLLLEFT),
    ("mouse_bottom", protocol.MOUSE_BOTTOM),
    ("mouse_ble", protocol.MOUSE_BLE),
)

_BUTTON_BY_NAME = dict(BUTTONS)

# Confirmed 4-byte function methods, id -> bytes. Extracted from the A Hub
# chunk `keyPosition-D9HhW_CA.js` (functions with a fixed 4-byte method).
# This dict is what the "Botões" tab offers in the picker, so it only holds
# functions whose write format is device-validated / a confirmed 4-byte
# method. Keyboard keys (single HID usage byte), combos (0x02 prefix) and
# macros (0x05 prefix) are NOT here: their write formats derive from the
# bundle and stay gated until device-validated (spec "Ask First"). They are
# decoded read-only via `_DECODE_ONLY`.
METHODS = {
    # mouse buttons (type 0x03)
    "mouse_left": bytes.fromhex("03000100"),
    "mouse_middle": bytes.fromhex("03000400"),
    "mouse_right": bytes.fromhex("03000200"),
    "nav_forward": bytes.fromhex("03001000"),
    "nav_back": bytes.fromhex("03000800"),
    # DPI (type 0x08)
    "dpi_plus": bytes.fromhex("08000500"),
    "dpi_minus": bytes.fromhex("08000600"),
    "dpi_cycle_plus": bytes.fromhex("08000300"),
    "dpi_cycle_minus": bytes.fromhex("08000400"),
    # scroll (type 0x0b vertical, 0x0c horizontal). NOTE: scroll_forward and
    # scroll_backward share the same method (the bundle assigns the direction
    # contextually) — decoding reports the id matching the physical button.
    "scroll_forward": bytes.fromhex("0bff00ff"),
    "scroll_backward": bytes.fromhex("0bff00ff"),
    "scroll_left": bytes.fromhex("0cff00ff"),
    "scroll_right": bytes.fromhex("0cff01ff"),
    # functions (type 0x09 fire/sniper, 0x0a config/DIY, 0x07 disable)
    "fire_button": bytes.fromhex("09000200"),
    "sniper_button": bytes.fromhex("09000100"),
    "diy_button": bytes.fromhex("0a000000"),
    "config_switch": bytes.fromhex("0a000200"),
    "button_disable": bytes.fromhex("07000000"),
    # media / window / edit (type 0x04)
    "media_prev": bytes.fromhex("040000b6"),
    "media_play_pause": bytes.fromhex("040000cd"),
    "media_next": bytes.fromhex("040000b5"),
    "media_stop": bytes.fromhex("040000b7"),
    "media_mute": bytes.fromhex("040000e2"),
    "media_vol_up": bytes.fromhex("040000e9"),
    "media_vol_down": bytes.fromhex("040000ea"),
    "app_player": bytes.fromhex("04000183"),
    "app_mail": bytes.fromhex("0400018a"),
    "app_calculator": bytes.fromhex("04000192"),
    "app_computer": bytes.fromhex("04000194"),
    "app_search": bytes.fromhex("04000221"),
}

# Methods that label read-backs but are NOT offered in the picker: the BLE
# button's left-click variant (03 00 01 01, confirmed on-device) and the
# bundle-derived combo (0x02) / macro (0x05) / keyboard (1-byte HID) codes,
# gated until their write formats are device-validated.
_DECODE_ONLY = {
    "mouse_left_ble": bytes.fromhex("03000101"),
    "win_close": bytes.fromhex("023d0400"),
    "win_lock": bytes.fromhex("020f0800"),
    "win_app": bytes.fromhex("02150800"),
    "win_desktop": bytes.fromhex("02070800"),
    "win_zoom_in": bytes.fromhex("02570800"),
    "win_zoom_out": bytes.fromhex("022d0800"),
    "edit_copy": bytes.fromhex("02060100"),
    "edit_paste": bytes.fromhex("02190100"),
    "edit_cut": bytes.fromhex("021b0100"),
    "edit_select_all": bytes.fromhex("02040100"),
}

# Decode-only preference for shared methods: when two physical buttons hold
# the same method bytes (scroll fwd/back = 0b ff 00 ff), the picker label
# must match the physical button the field belongs to.
_SCROLL_BY_BUTTON = {
    "mouse_scroll_forward": "scroll_forward",
    "mouse_scroll_back": "scroll_backward",
}

_ID_BY_METHOD = {}
for _fid, _method in METHODS.items():
    _ID_BY_METHOD.setdefault(_method, _fid)  # first id wins on collisions
for _fid, _method in _DECODE_ONLY.items():
    _ID_BY_METHOD.setdefault(_method, _fid)


def _addr(offset):
    return tuple(protocol.eeprom_bank0(offset))


def _read(dev, addr, length):
    resp = dev.read_eeprom(addr, length)
    if not hasattr(resp, "__len__"):
        raise ValueError("invalid EEPROM reply")
    if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
        raise ValueError("short EEPROM reply")
    return bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])


def button_addr(name):
    """Absolute bank-0 address of a button as a hex string."""
    return "0x{:04X}".format(protocol.EEPROM_BANK0_BASE + _BUTTON_BY_NAME[name])


def method_name(method, button=None):
    """Function id for a 4-byte method, or None when the method is unknown.

    The scroll direction is contextual: both physical scroll buttons hold
    `0b ff 00 ff`, so when `button` names one of them the matching direction
    id is returned (otherwise the first id wins, as before).
    """
    fid = _ID_BY_METHOD.get(bytes(method))
    if fid == "scroll_forward" and button in _SCROLL_BY_BUTTON:
        return _SCROLL_BY_BUTTON[button]
    return fid


def is_left_click(method):
    """True when a method is a left-click function (type 0x03, button index 1).

    A mouse-button method is `<type=0x03> <0x00> <index> <flag>`: the button
    index lives in byte 2 (left = 0x01, right = 0x02, middle = 0x04). Covers
    both the plain left button (03 00 01 00) and the BLE switch (03 00 01 01),
    which the device reads back with the same left-click semantics plus a
    trailing flag.
    """
    b = bytes(method)
    return len(b) >= 3 and b[0] == 0x03 and b[2] == 0x01


def read_button(dev, name):
    """Reads one button's 4-byte method and decodes it.

    `method` is the raw 4 bytes, `fn` the function id (or None for an
    unknown/raw method, shown as hex). Raises ValueError on a short reply.
    """
    raw = _read(dev, _addr(_BUTTON_BY_NAME[name]), 4)
    if len(raw) != 4:
        raise ValueError("short button reply for %s" % name)
    return {
        "name": name,
        "addr": button_addr(name),
        "method": raw,
        "fn": method_name(raw, name),
        "raw_hex": raw.hex(),
    }


def read_section(dev):
    """Reads every button into one payload with isolated per-field errors.

    A single broken field never blanks the whole section: each button either
    has its read state or an error string. ValueError-class failures (short
    replies) are isolated per field; device-level failures (CommandTimeout,
    OSError) propagate so the caller surfaces the section error.
    """
    buttons = {}
    errors = {}
    for name, _offset in BUTTONS:
        try:
            buttons[name] = read_button(dev, name)
        except ValueError as exc:
            errors[name] = str(exc)
    return {"buttons": buttons, "errors": errors}


def _other_is_left(dev, name):
    """True when another button reads back as left-click; False when the read
    fails (a flaky field must not block the ≥1-left rule, only a confirmed
    left elsewhere allows the remap away from left-click)."""
    try:
        return is_left_click(read_button(dev, name)["method"])
    except ValueError:
        return False


class NoLeftClickError(ValueError):
    """The ≥1-left-click rule refused a remap (no other left-click button).
    The UI translates this into a localized message."""


def set_function(dev, name, fn_id, keep_left=True):
    """Assigns a confirmed function method to a button, verified by re-reading.

    Writes the 4-byte method and confirms it with an immediate read-back; a
    mismatch raises ValueError so the change is never accepted. When
    `keep_left` is True and `name` is a left-click-capable button, the write
    is refused for a non-left-click function (the ≥1-left-button rule) unless
    another button is already left-click-capable.
    """
    if fn_id not in METHODS:
        raise ValueError("unknown function %r" % fn_id)
    if name not in _BUTTON_BY_NAME:
        raise ValueError("unknown button %r" % name)
    addr = _addr(_BUTTON_BY_NAME[name])
    method = METHODS[fn_id]
    current = _read(dev, addr, 4)
    if keep_left and is_left_click(current) and not is_left_click(method):
        # The button being remapped away from left-click is only allowed when
        # at least one other button keeps left-click. A failed read of an
        # other button counts as "no left elsewhere" (a broken/flaky field
        # must not block the rule) — the write is refused rather than aborted.
        others_left = any(
            other != name and _other_is_left(dev, other)
            for other, _offset in BUTTONS
        )
        if not others_left:
            raise NoLeftClickError()
    raw = dev.write_eeprom_verify(addr, method)
    if len(raw) != 4 or bytes(raw) != method:
        raise ValueError("button write not verified (read back %r)" % (list(raw),))
    return {
        "name": name,
        "addr": button_addr(name),
        "method": method,
        "fn": fn_id,
        "raw_hex": method.hex(),
    }
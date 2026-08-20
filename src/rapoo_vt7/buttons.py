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
Keyboard keys (`00 00 <HID> 00`, HID usage byte) and combos (`02 <key1>
<modifier> <key2>`) and macros (`05 00 <slot> 00`) derive from the bundle and
are shippable after their write formats are device-validated. `METHODS` is
the picker offer list; `_DECODE_ONLY` labels read-backs (BLE left variant)
without offering them.
"""

from . import protocol
from .device import CommandTimeout

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
}

# Keyboard keys (keyType 1 of the A Hub keyPosition table): key id -> HID
# usage byte. The mouse stores a keyboard assignment as `00 00 <HID> 00`
# (the bundle pads the single HID byte into the 4-byte method).
KEYBOARD = {
    "kb_esc": 0x29,
    "kb_f1": 0x3a,
    "kb_f2": 0x3b,
    "kb_f3": 0x3c,
    "kb_f4": 0x3d,
    "kb_f5": 0x3e,
    "kb_f6": 0x3f,
    "kb_f7": 0x40,
    "kb_f8": 0x41,
    "kb_f9": 0x42,
    "kb_f10": 0x43,
    "kb_f11": 0x44,
    "kb_f12": 0x45,
    "kb_tilde": 0x35,
    "kb_1": 0x1e,
    "kb_2": 0x1f,
    "kb_3": 0x20,
    "kb_4": 0x21,
    "kb_5": 0x22,
    "kb_6": 0x23,
    "kb_7": 0x24,
    "kb_8": 0x25,
    "kb_9": 0x26,
    "kb_0": 0x27,
    "kb_dash": 0x2d,
    "kb_plus": 0x2e,
    "kb_backspace": 0x2a,
    "kb_tab": 0x2b,
    "kb_q": 0x14,
    "kb_w": 0x1a,
    "kb_e": 0x08,
    "kb_r": 0x15,
    "kb_t": 0x17,
    "kb_y": 0x1c,
    "kb_u": 0x18,
    "kb_i": 0x0c,
    "kb_o": 0x12,
    "kb_p": 0x13,
    "kb_bracket_left": 0x2f,
    "kb_bracket_right": 0x30,
    "kb_backslash": 0x31,
    "kb_caps": 0x39,
    "kb_a": 0x04,
    "kb_s": 0x16,
    "kb_d": 0x07,
    "kb_f": 0x09,
    "kb_g": 0x0a,
    "kb_h": 0x0b,
    "kb_j": 0x0d,
    "kb_k": 0x0e,
    "kb_l": 0x0f,
    "kb_semicolon": 0x33,
    "kb_quote": 0x34,
    "kb_enter": 0x28,
    "kb_shift_left": 0xe1,
    "kb_z": 0x1d,
    "kb_x": 0x1b,
    "kb_c": 0x06,
    "kb_v": 0x19,
    "kb_b": 0x05,
    "kb_n": 0x11,
    "kb_m": 0x10,
    "kb_comma": 0x36,
    "kb_period": 0x37,
    "kb_slash": 0x38,
    "kb_shift_right": 0xe5,
    "kb_ctrl_left": 0xe0,
    "kb_win_left": 0xe3,
    "kb_alt_left": 0xe2,
    "kb_space": 0x2c,
    "kb_alt_right": 0xe6,
    "kb_win_right": 0xe7,
    "kb_menu": 0x65,
    "kb_ctrl_right": 0xe4,
    "kb_prtsc": 0x46,
    "kb_scroll": 0x47,
    "kb_pause": 0x48,
    "kb_insert": 0x49,
    "kb_home": 0x4a,
    "kb_pgup": 0x4b,
    "kb_delete": 0x4c,
    "kb_end": 0x4d,
    "kb_pgdn": 0x4e,
    "kb_arrow_up": 0x52,
    "kb_arrow_left": 0x50,
    "kb_arrow_down": 0x51,
    "kb_arrow_right": 0x4f,
    "kb_numlock": 0x53,
    "kp_slash": 0x54,
    "kp_asterisk": 0x55,
    "kp_minus": 0x56,
    "kp_7": 0x5f,
    "kp_8": 0x60,
    "kp_9": 0x61,
    "kp_4": 0x5c,
    "kp_5": 0x5d,
    "kp_6": 0x5e,
    "kp_plus": 0x57,
    "kp_1": 0x59,
    "kp_2": 0x5a,
    "kp_3": 0x5b,
    "kp_enter": 0x58,
    "kp_0": 0x62,
    "kp_decimal": 0x63,
}

# Language-neutral keyboard key labels (from the A Hub keyPosition table).
KEYBOARD_LABEL = {
    "kb_esc": "Esc",
    "kb_f1": "F1",
    "kb_f2": "F2",
    "kb_f3": "F3",
    "kb_f4": "F4",
    "kb_f5": "F5",
    "kb_f6": "F6",
    "kb_f7": "F7",
    "kb_f8": "F8",
    "kb_f9": "F9",
    "kb_f10": "F10",
    "kb_f11": "F11",
    "kb_f12": "F12",
    "kb_tilde": "`",
    "kb_1": "1",
    "kb_2": "2",
    "kb_3": "3",
    "kb_4": "4",
    "kb_5": "5",
    "kb_6": "6",
    "kb_7": "7",
    "kb_8": "8",
    "kb_9": "9",
    "kb_0": "0",
    "kb_dash": "-",
    "kb_plus": "=",
    "kb_backspace": "Back",
    "kb_tab": "Tab",
    "kb_q": "Q",
    "kb_w": "W",
    "kb_e": "E",
    "kb_r": "R",
    "kb_t": "T",
    "kb_y": "Y",
    "kb_u": "U",
    "kb_i": "I",
    "kb_o": "O",
    "kb_p": "P",
    "kb_bracket_left": "[",
    "kb_bracket_right": "]",
    "kb_backslash": "\\",
    "kb_caps": "Caps",
    "kb_a": "A",
    "kb_s": "S",
    "kb_d": "D",
    "kb_f": "F",
    "kb_g": "G",
    "kb_h": "H",
    "kb_j": "J",
    "kb_k": "K",
    "kb_l": "L",
    "kb_semicolon": ";",
    "kb_quote": "'",
    "kb_enter": "Enter",
    "kb_shift_left": "Shift",
    "kb_z": "Z",
    "kb_x": "X",
    "kb_c": "C",
    "kb_v": "V",
    "kb_b": "B",
    "kb_n": "N",
    "kb_m": "M",
    "kb_comma": ",",
    "kb_period": ".",
    "kb_slash": "/",
    "kb_shift_right": "Shift",
    "kb_ctrl_left": "Ctrl",
    "kb_win_left": "Win",
    "kb_alt_left": "Alt",
    "kb_space": "Space",
    "kb_alt_right": "Alt",
    "kb_win_right": "Win",
    "kb_menu": "Menu",
    "kb_ctrl_right": "Ctrl",
    "kb_prtsc": "PrtSc",
    "kb_scroll": "Scroll",
    "kb_pause": "Pause",
    "kb_insert": "Insert",
    "kb_home": "Home",
    "kb_pgup": "PgUp",
    "kb_delete": "Delete",
    "kb_end": "End",
    "kb_pgdn": "PgDn",
    "kb_arrow_up": "↑",
    "kb_arrow_left": "←",
    "kb_arrow_down": "↓",
    "kb_arrow_right": "→",
    "kb_numlock": "Num",
    "kp_slash": "/",
    "kp_asterisk": "*",
    "kp_minus": "-",
    "kp_7": "7",
    "kp_8": "8",
    "kp_9": "9",
    "kp_4": "4",
    "kp_5": "5",
    "kp_6": "6",
    "kp_plus": "+",
    "kp_1": "1",
    "kp_2": "2",
    "kp_3": "3",
    "kp_enter": "Enter",
    "kp_0": "0",
    "kp_decimal": ".Del",
}

# Fixed combos (keyType 2 of the keyPosition table, type 0x02 prefix). These
# are the A Hub preset combinations — offered in the picker alongside the
# keyboard keys once their write format is device-validated.
COMBO = {
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

# Modifier keys (for building custom combos): key id -> bit in the combo
# modifier byte. The A Hub builds `02 <key1> <modifier> <key2>` with the
# modifier byte a plain bitmask (Ctrl L = 0x01, Shift L = 0x02, Alt L = 0x04,
# Win L = 0x08, Ctrl R = 0x10, Shift R = 0x20, Alt R = 0x40, Win R = 0x80).
MODIFIER = {
    "kb_ctrl_left": 0x01,
    "kb_shift_left": 0x02,
    "kb_alt_left": 0x04,
    "kb_win_left": 0x08,
    "kb_ctrl_right": 0x10,
    "kb_shift_right": 0x20,
    "kb_alt_right": 0x40,
    "kb_win_right": 0x80,
}

# Macros (keyType 8): 12 slots, stored as `05 00 <slot> 00` methods. The
# macro CONTENTS live elsewhere in EEPROM (the A Hub macro editor) — the
# picker only assigns a slot to a button.
MACRO_SLOTS = 12


def keyboard_method(key):
    """4-byte method for a keyboard key: `00 00 <HID> 00`."""
    return bytes((0x00, 0x00, KEYBOARD[key], 0x00))


def combo_method(key1, modifier=0, key2=None):
    """4-byte combo method `02 <key1> <modifier> <key2>`.

    Matches the A Hub `L()`: a single-key combo pads key2 with 0x00
    (e.g. Alt+F4 = `02 3d 04 00`); two keys set key2 (`02 k1 mod k2`).
    """
    if key2 is None:
        return bytes((0x02, KEYBOARD[key1], modifier, 0x00))
    return bytes((0x02, KEYBOARD[key1], modifier, KEYBOARD[key2]))


def macro_method(slot):
    """4-byte macro method `05 00 <slot> 00` for a macro slot 0..11."""
    return bytes((0x05, 0x00, slot, 0x00))


# Reverse maps for decode.
_HID_BY_KEY = {hid: key for key, hid in KEYBOARD.items()}
_MODIFIER_BY_BIT = {bit: key for key, bit in MODIFIER.items()}

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
for _fid, _method in COMBO.items():
    _ID_BY_METHOD.setdefault(_method, _fid)
for _slot in range(MACRO_SLOTS):
    _ID_BY_METHOD.setdefault(macro_method(_slot), "macro_%d" % _slot)


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
    id is returned (otherwise the first id wins, as before). Keyboard keys
    (`00 00 <HID> 00`) decode to their `kb_`/`kp_` key id.
    """
    b = bytes(method)
    fid = _ID_BY_METHOD.get(b)
    if fid == "scroll_forward" and button in _SCROLL_BY_BUTTON:
        return _SCROLL_BY_BUTTON[button]
    if fid is None and len(b) == 4 and b[0] == 0x00 and b[1] == 0x00 and b[3] == 0x00:
        return _HID_BY_KEY.get(b[2])
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
    except (ValueError, CommandTimeout, OSError):
        return False


class NoLeftClickError(ValueError):
    """The ≥1-left-click rule refused a remap (no other left-click button).
    The UI translates this into a localized message."""


class UnknownFunctionError(ValueError):
    """`set_function` received a function id that is not in the offer lists.
    The UI translates this into a localized message."""


def function_method(fn_id):
    """4-byte method for a function id across every offer category.

    Resolves `METHODS`, `COMBO`, `KEYBOARD` (encoded `00 00 <HID> 00`) and
    `macro_<slot>`. Returns None for an unknown id.
    """
    method = METHODS.get(fn_id)
    if method is not None:
        return method
    method = COMBO.get(fn_id)
    if method is not None:
        return method
    if fn_id in KEYBOARD:
        return keyboard_method(fn_id)
    if fn_id.startswith("macro_") and fn_id[6:].isdigit():
        slot = int(fn_id[6:])
        if 0 <= slot < MACRO_SLOTS:
            return macro_method(slot)
    return None


def set_function(dev, name, fn_id, keep_left=True):
    """Assigns a confirmed function method to a button, verified by re-reading.

    Writes the 4-byte method and confirms it with an immediate read-back; a
    mismatch raises ValueError so the change is never accepted. When
    `keep_left` is True and `name` is a left-click-capable button, the write
    is refused for a non-left-click function (the ≥1-left-button rule) unless
    another button is already left-click-capable.
    """
    method = function_method(fn_id)
    if method is None:
        raise UnknownFunctionError(fn_id)
    if name not in _BUTTON_BY_NAME:
        raise ValueError("unknown button %r" % name)
    addr = _addr(_BUTTON_BY_NAME[name])
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
"""DPI read/write operations for the Rapoo VT7 (Phase 2).

Pure device-level functions: each takes an open RapooDevice and returns the
result or raises on error/validation. No GUI, no threads — testable against
a fake device (see tests/test_dpi.py).

The firmware stores the DPI config as a COMPACT list: the 0x0896 byte is the
number of active gears minus 1, and the physical DPI button cycles the first
(enable+1) slots of the X/Y tables (validated on the device: enable=1 -> the
button cycles only slots 0..1). "Disabling" a DPI means removing it from the
compact list, exactly like the official A Hub setDeviceGears()/delete.
"""

from . import eeprom, protocol, settings

GEAR_LENGTH = protocol.MOUSE_DPI_GEAR_LENGTH  # 7
DPI_MIN = 50
DPI_MAX = 26000
DPI_STEP = 50
ADD_DEFAULT = 800  # value appended by add_gear() when none is given


def _addr_at(offset, item):
    return eeprom.bank0(offset + 2 * item)


def _read_field(dev, field):
    return field.decode(eeprom.read_bytes(dev, field.addr, field.size))


def _read_list(dev, offset):
    out = []
    for i in range(GEAR_LENGTH):
        raw = eeprom.read_bytes(dev, _addr_at(offset, i), 2)
        out.append(raw[0] | (raw[1] << 8))
    return out


def _validate_dpi(value):
    if not isinstance(value, int):
        raise ValueError("DPI must be an integer")
    if not DPI_MIN <= value <= DPI_MAX:
        raise ValueError("DPI %d out of range %d..%d" % (value, DPI_MIN, DPI_MAX))
    if (value - DPI_MIN) % DPI_STEP != 0:
        raise ValueError("DPI %d is not a multiple of %d" % (value, DPI_STEP))


def read_dpi(dev):
    """Reads the current gear + enable byte and the X/Y tables (7 values
    each, 2-byte LE) and returns {'gear', 'enable', 'x': [7], 'y': [7]}.

    The device-provided gear byte is clamped into the active cycle
    (0..active_count(enable)-1): a garbage byte from the device must never
    crash the consumers that index the X/Y tables with it."""
    info = {
        "gear": _read_field(dev, settings.FIELDS["dpi_current"]),
        "enable": _read_field(dev, settings.FIELDS["dpi_enable_gear"]),
        "x": _read_list(dev, protocol.MOUSE_DPI_X_LIST),
        "y": _read_list(dev, protocol.MOUSE_DPI_Y_LIST),
    }
    info["gear"] = min(
        max(int(info["gear"]), 0), active_count(info["enable"]) - 1
    )
    return info


def active_count(enable):
    """Number of DPIs in the physical-button cycle.

    The EEPROM enable byte (0x0896) stores (count - 1): the button cycles the
    first `count` slots of the X/Y lists. Validated on the device (enable=1
    -> the button alternates only between slots 0 and 1)."""
    n = (int(enable) & 0xFF) + 1
    return max(1, min(GEAR_LENGTH, n))


def active_gears(info):
    """[(slot, x)] of the DPIs in the button cycle (slots 0..enable)."""
    n = active_count(info.get("enable", 0))
    return [(i, info["x"][i]) for i in range(n)]


def _active_xy(info):
    n = active_count(info.get("enable", 0))
    return list(info["x"][:n]), list(info["y"][:n])


def _sorted_active(xl, yl, cur_value):
    """Sorts the active X/Y lists by X ascending (keeping X/Y pairs together)
    and returns (xl, yl, new_cur) — new_cur is the first slot holding
    `cur_value`, so the current DPI keeps its VALUE across the reorder."""
    pairs = sorted(zip(xl, yl), key=lambda p: p[0])
    xl2 = [p[0] for p in pairs]
    yl2 = [p[1] for p in pairs]
    new_cur = next((i for i, v in enumerate(xl2) if v == cur_value), 0)
    return xl2, yl2, new_cur


def set_gears(dev, x_list, y_list=None):
    """Writes a compact gear list + the enable byte (count-1).

    The button cycle = the first len(x_list) slots of the tables, so the
    values are written at the start of the X/Y lists (the tail slots keep
    their stale values and are not cycled)."""
    if y_list is None:
        y_list = x_list
    if not (1 <= len(x_list) <= GEAR_LENGTH):
        raise ValueError("gear list must have 1..%d entries" % GEAR_LENGTH)
    if len(y_list) != len(x_list):
        raise ValueError("X and Y lists must have the same length")
    for v in x_list:
        _validate_dpi(v)
    for v in y_list:
        _validate_dpi(v)
    xf = settings.FIELDS["dpi_x_list"]
    yf = settings.FIELDS["dpi_y_list"]
    xbytes = b"".join(xf.encode(v) for v in x_list)
    ybytes = b"".join(yf.encode(v) for v in y_list)
    dev.write_eeprom_verify(_addr_at(protocol.MOUSE_DPI_X_LIST, 0), xbytes)
    dev.write_eeprom_verify(_addr_at(protocol.MOUSE_DPI_Y_LIST, 0), ybytes)
    field = settings.FIELDS["dpi_enable_gear"]
    readback = dev.write_eeprom_verify(field.addr, field.encode(len(x_list) - 1))
    return {
        "list": list(x_list),
        "enable": len(x_list) - 1,
        "verify": bytes(readback).hex().upper(),
    }


def add_gear(dev, info, value=None):
    """Appends a gear to the button cycle (max 7) keeping the list sorted
    ascending by value. `value` defaults to 800. The current gear follows its
    DPI value across the reorder (the DPI in use never changes)."""
    if value is None:
        value = ADD_DEFAULT
    _validate_dpi(value)
    xl, yl = _active_xy(info)
    if len(xl) >= GEAR_LENGTH:
        raise ValueError("max %d gears reached" % GEAR_LENGTH)
    xl.append(value)
    yl.append(value)
    cur_value = info["x"][int(info["gear"])]
    xl, yl, new_cur = _sorted_active(xl, yl, cur_value)
    res = set_gears(dev, xl, yl)
    set_gear(dev, new_cur)
    return dict(
        res,
        gear=new_cur,
        current=new_cur,
        cur_x=cur_value,
        x=value,
        slot=xl.index(value),
    )


def delete_gear(dev, info, slot):
    """Removes a gear from the button cycle.

    Compacts the list (the slots after `slot` shift down), writes it back
    and re-selects the current gear like the A Hub does (first remaining
    gear when the current one was deleted). Raises when `slot` is not in the
    active cycle or only one gear is left."""
    n = active_count(info.get("enable", 0))
    if not isinstance(slot, int) or not 0 <= slot < n:
        raise ValueError("slot must be an int in 0..%d" % (n - 1))
    if n <= 1:
        raise ValueError("cannot delete the last gear")
    xl, yl = _active_xy(info)
    cur = int(info["gear"])
    xl.pop(slot)
    yl.pop(slot)
    res = set_gears(dev, xl, yl)
    if slot == cur:
        new_cur = 0
    elif slot < cur:
        new_cur = cur - 1
    else:
        new_cur = cur
    new_cur = max(0, min(new_cur, len(xl) - 1))
    set_gear(dev, new_cur)
    return dict(res, current=new_cur)


def set_gear(dev, gear):
    """Switches the DPI gear (0..6) and re-reads to verify."""
    if not isinstance(gear, int) or not 0 <= gear < GEAR_LENGTH:
        raise ValueError("gear must be an int in 0..%d" % (GEAR_LENGTH - 1))
    field = settings.FIELDS["dpi_current"]
    readback = dev.write_eeprom_verify(field.addr, field.encode(gear))
    return {"gear": gear, "verify": bytes(readback).hex().upper()}


def set_value(dev, info, gear, x, y=None):
    """Sets the X (and Y, default = X) DPI of a gear, 50..26000 step 50, IN
    PLACE — the gear list/cycle is untouched (no reorder, no re-select).

    Only the current gear (its radio button is marked) is applied: its slot
    holds the DPI in use, so changing its value switches the mouse to the new
    value immediately. Editing any other gear only stores the value."""
    if not isinstance(gear, int):
        raise ValueError("gear must be an int")
    if y is None:
        y = x
    _validate_dpi(x)
    _validate_dpi(y)
    xl, yl = _active_xy(info)
    if not 0 <= gear < len(xl):
        raise ValueError("gear must be an int in 0..%d" % (len(xl) - 1))
    cur = int(info["gear"])
    applied = gear == cur
    xf = settings.FIELDS["dpi_x_list"]
    yf = settings.FIELDS["dpi_y_list"]
    dev.write_eeprom_verify(_addr_at(protocol.MOUSE_DPI_X_LIST, gear), xf.encode(x))
    dev.write_eeprom_verify(_addr_at(protocol.MOUSE_DPI_Y_LIST, gear), yf.encode(y))
    return {
        "gear": gear,
        "x": x,
        "y": y,
        "applied": applied,
        "current": cur,
        "cur_x": x if applied else xl[cur],
    }

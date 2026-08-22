"""Shared EEPROM access helpers for the Rapoo VT7.

One implementation of the bank-0 address building and of the validated
read-and-slice pattern that every feature module (dpi, performance,
parameters, buttons, system) uses: read via the device, check the reply is
long enough, slice the payload bytes that start at `EEPROM_DATA_OFFSET`.

Pure helpers over the device object — no GUI, no threads; testable against
a fake device.
"""

from . import protocol


def bank0(offset):
    """Absolute 2-byte LE bank-0 address tuple for a register offset."""
    return tuple(protocol.eeprom_bank0(offset))


def read_bytes(dev, addr, length):
    """Reads `length` EEPROM bytes at `addr` and returns the payload slice.

    Raises ValueError on a non-sequence or short reply (the caller surfaces
    it as a field/section error); device-level failures (CommandTimeout,
    OSError) propagate.
    """
    resp = dev.read_eeprom(addr, length)
    if not hasattr(resp, "__len__"):
        raise ValueError("invalid EEPROM reply")
    if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
        raise ValueError("short EEPROM reply")
    return bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])

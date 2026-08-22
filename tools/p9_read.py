"""P9 ampliado helper: read-only snapshot of the bytes under test.

Usage: python3 tools/p9_read.py
Prints the raw byte of each A Hub-mapped parameter plus the shared RF byte.
READS ONLY - never writes. Diagnostic tool (baseline gate opted out).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import eeprom, protocol  # noqa: E402
from src.rapoo_vt7.device import RapooDevice  # noqa: E402

TARGETS = (
    ("press_debounce", protocol.MOUSE_DOWNDELAY),
    ("release_debounce", protocol.MOUSE_LIFTDELAY),
    ("sleep_time", protocol.MOUSE_SLEEPTIME),
    ("sensor_angle", protocol.MOUSE_SENSORANGLE),
    ("lift_off", protocol.MOUSE_SLIGHT),
    ("rf_shared", protocol.RF_STRENGTHEN_SWITCH),
    ("rate_code", protocol.MOUSE_REPORT),
)


def main():
    dev = RapooDevice(require_baseline=False)
    dev.open()
    try:
        for name, off in TARGETS:
            addr = tuple(protocol.eeprom_bank0(off))
            b = eeprom.read_bytes(dev, addr, 1)[0]
            extra = ""
            if name == "sensor_angle":
                extra = " (signed: %d)" % (b - 256 if b > 127 else b)
            print("%-18s 0x%04X = 0x%02X (%3d)%s" % (name, off, b, b, extra))
    finally:
        dev.close()


if __name__ == "__main__":
    main()

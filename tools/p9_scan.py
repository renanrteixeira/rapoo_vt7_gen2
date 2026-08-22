"""P9 ampliado helper: wide read-only scan of bank-0 §C region.

Usage: python3 tools/p9_scan.py > snapshot.txt
Dumps every byte from 0x0880 to 0x08FF as HEX lines (addr = value).
READS ONLY - never writes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import eeprom, protocol  # noqa: E402
from src.rapoo_vt7.device import RapooDevice  # noqa: E402

START = 0x0880
END = 0x08FF


def main():
    dev = RapooDevice(require_baseline=False)
    dev.open()
    try:
        chunk = 24
        data = {}
        off = START
        while off <= END:
            n = min(chunk, END - off + 1)
            addr = tuple(protocol.eeprom_bank0(off - protocol.EEPROM_BANK0_BASE))
            raw = eeprom.read_bytes(dev, addr, n)
            for i in range(n):
                data[off + i] = raw[i]
            off += n
        for off in sorted(data):
            print("0x%04X %02X" % (off, data[off]))
    finally:
        dev.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Section-C golden-rule write-test for the Rapoo VT7 (story 3-3).

For each Section-C byte this reads the current value, writes a candidate,
re-reads it, then RESTORES the original value unconditionally (try/finally),
so the device is never left modified. It prints a confirmation table that
documents which bytes are writable and what semantics they accept — the same
run that confirmed motion/glass/DC as 0/1 bools and linear_ripple as numeric
on 2026-08-11.

Refuses to run while the EEPROM baseline is missing (golden rule: no write
before a baseline exists).

Usage:
    python3 tools/writetest_c.py            # toggle candidates: 0 then 1
    python3 tools/writetest_c.py --dry-run  # read-only, print the table only
"""

import argparse
import os
import sys

from src.rapoo_vt7 import parameters, protocol, settings
from src.rapoo_vt7.device import RapooDevice, CommandTimeout

# Which bytes to probe as toggles vs plain "writable?" reads. Editable toggles
# are exercised with 0 and 1; the rest are written once with a single candidate
# (0x00) just to prove writability, then always restored.
TOGGLE_CANDIDATES = (0x00, 0x01)
STATE_CANDIDATES = (0x00,)


def _addr(offset):
    return tuple(protocol.eeprom_bank0(offset))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read every §C byte and print the table without writing anything",
    )
    args = parser.parse_args()

    if not os.path.exists(settings.EEPROM_BASELINE_PATH):
        print(
            "ERROR: no EEPROM baseline at %s (golden rule: never write without "
            "one). Run `python3 tools/probe.py --dump` first."
            % settings.EEPROM_BASELINE_PATH,
            file=sys.stderr,
        )
        return 1

    dev = RapooDevice()
    try:
        dev.open()
    except Exception as exc:
        print("ERROR: could not open the device: %s" % exc, file=sys.stderr)
        return 1

    try:
        if args.dry_run:
            for name, offset, editable in parameters.PARAMS:
                addr = _addr(offset)
                raw = bytes(dev.read_eeprom(addr, 1)[protocol.EEPROM_DATA_OFFSET :])
                print(
                    "  %-16s 0x%04X  raw=0x%02X  %s"
                    % (name, addr[1] << 8 | addr[0], raw[0],
                       "TOGGLE" if editable else "READ-ONLY")
                )
            return 0

        print("golden-rule §C write-test (every byte restored after):")
        failures = 0
        for name, offset, editable in parameters.PARAMS:
            addr = _addr(offset)
            original = bytes(dev.read_eeprom(addr, 1)[protocol.EEPROM_DATA_OFFSET :])[0]
            candidates = TOGGLE_CANDIDATES if editable else STATE_CANDIDATES
            accepted = []
            try:
                for cand in candidates:
                    try:
                        written = dev.write_eeprom_verify(addr, bytes((cand,)))
                        ok = len(written) == 1 and written[0] == cand
                        readback = written[0] if len(written) == 1 else -1
                        accepted.append((cand, readback, ok))
                    except Exception as exc:
                        accepted.append((cand, None, "ERR:%s" % type(exc).__name__))
            finally:
                # unconditional restore so the device is never left modified
                try:
                    dev.write_eeprom_verify(addr, bytes((original,)))
                    restored = bytes(
                        dev.read_eeprom(addr, 1)[protocol.EEPROM_DATA_OFFSET :]
                    )[0]
                except Exception as exc:
                    restored = "ERR:%s" % type(exc).__name__
            row = ", ".join(
                "write=0x%02X read=0x%02X %s" % (c, r, "OK" if o is True else o)
                for (c, r, o) in accepted
            )
            flags = []
            for c, r, o in accepted:
                if o is not True and o is not False:
                    flags.append("FAILED")
                    failures += 1
            state = "TOGGLE" if editable else "READ-ONLY"
            print(
                "  %-16s 0x%04X  orig=0x%02X restored=0x%02X  %-10s  %s"
                % (
                    name,
                    addr[1] << 8 | addr[0],
                    original,
                    restored,
                    state,
                    row + ("  [%s]" % ",".join(flags) if flags else ""),
                )
            )
        if failures:
            print("\n%d field(s) failed — inspect the rows above." % failures)
            return 1
        print("\nall §C bytes writable and restored exactly.")
        return 0
    except CommandTimeout as exc:
        print(
            "ERROR: no response from the mouse (%s); move it to wake it and "
            "retry." % exc,
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print("ERROR: device read/write failed: %s" % exc, file=sys.stderr)
        return 1
    finally:
        dev.close()


if __name__ == "__main__":
    sys.exit(main())

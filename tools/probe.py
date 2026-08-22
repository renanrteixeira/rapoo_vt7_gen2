import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7 import buttons as button_mod
from src.rapoo_vt7 import i18n, pairing, parameters, protocol, settings, system
from src.rapoo_vt7.device import DeviceNotFound, RapooDevice, CommandTimeout


def fmt(b):
    return " ".join(f"{x:02X}" for x in (b or b""))


def query(dev, cmd_id, args=(), label=None):
    label = label or protocol.__dict__.get(
        f"cmd_{cmd_id}", f"cmd 0x{cmd_id:02X}"
    )
    resp = dev.query(cmd_id, args, timeout=1.2)
    print(f"  {label}: {fmt(resp)}")
    return resp


def battery_probe(dev):
    print(i18n.tr("probe_battery_title"))
    for i in range(3):
        resp = dev.query(protocol.GET_BATTERY_LEVEL, timeout=1.2)
        status = resp[protocol.BATTERY_OFFSET_STATUS]
        level = resp[protocol.BATTERY_OFFSET_LEVEL]
        print(
            i18n.tr(
                "probe_battery_line",
                num=i + 1,
                data=fmt(resp),
                status=status,
                level=level,
            )
        )
        time.sleep(0.15)


def firmware_probe(dev):
    print(i18n.tr("probe_firmware_title"))
    resp = query(dev, protocol.GET_FIRMWARE, [0x00], "get_firmware")
    if len(resp) > protocol.FIRMWARE_OFFSET_MAJOR:
        minor = resp[protocol.FIRMWARE_OFFSET_MINOR]
        major = resp[protocol.FIRMWARE_OFFSET_MAJOR]
        pid = (resp[7] << 8) | resp[6]
        print(i18n.tr("probe_firmware_line", major=major, minor=minor, pid=pid))
    try:
        receiver = system.read_receiver_firmware(dev)
    except (CommandTimeout, DeviceNotFound, OSError, ValueError) as exc:
        print(i18n.tr("probe_receiver_fw_error", error=exc))
    else:
        print(i18n.tr("probe_receiver_fw_line", version=receiver))


def eeprom_probe(dev):
    print(i18n.tr("probe_eeprom_title"))
    for addr, label in [
        (protocol.EEPROM_CURRENT_CONNECT_PROTOCOL, "CURRENT_CONNECT_PROTOCOL"),
        (protocol.EEPROM_CONFIG_CURRENT, "CONFIG_CURRENT"),
    ]:
        resp = query(dev, protocol.READ_EEPROM, [1, addr[0], addr[1]], label)
        if len(resp) > protocol.EEPROM_DATA_OFFSET:
            print(
                i18n.tr(
                    "probe_eeprom_value",
                    value=resp[protocol.EEPROM_DATA_OFFSET],
                )
            )


def work_mode_probe(dev):
    print(i18n.tr("probe_workmode_title"))
    query(dev, protocol.GET_WORK_MODE, [], "get_work_mode")


def build_baseline(dev):
    """Reads the full EEPROM bank 0 (0x0600-0x0A00) in 24-byte blocks
    (last partial block: 16 bytes) via read_eeprom and returns a JSON-ready
    dict. Raises CommandTimeout if the mouse does not answer."""
    start = protocol.EEPROM_BANK0_BASE
    end = protocol.EEPROM_BANK0_END
    blocks = {}
    addr = start
    while addr < end:
        length = min(protocol.EEPROM_READ_MAX, end - addr)
        resp = dev.read_eeprom(protocol.eeprom_bank0(addr - start), length)
        if len(resp) < protocol.EEPROM_DATA_OFFSET + length:
            raise ValueError(
                "short EEPROM reply: got %d want %d"
                % (len(resp) - protocol.EEPROM_DATA_OFFSET, length)
            )
        data = bytes(resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + length])
        blocks["0x{:04X}".format(addr)] = data.hex().upper()
        addr += length
    return {
        "device": getattr(dev, "path", None) or "rapoo-vt7",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bank": 0,
        "start": start,
        "end": end,
        "blocks": blocks,
    }


def write_baseline(path, data):
    """Atomically writes the baseline JSON (temp file + os.replace), so a
    failure never leaves a partial/corrupt baseline behind."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=directory or None, prefix=".eeprom_baseline.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# Legacy "looks like a bit toggle" hypothesis fields. Section-C bytes are NOT
# listed here anymore: their value semantics are confirmed and they are fully
# covered by the authoritative `PARAM_FIELDS`/`params` block below (a byte must
# not appear as both a generic toggle hypothesis and a confirmed §C state).
TOGGLE_FIELDS = (
    "dpi_enable_gear",
)

# Section-C mouse parameters with the value semantics confirmed by the
# on-device write-test (read -> write -> re-read -> restore, 2026-08-11):
# `editable` True = bool on/off toggle confirmed; False = numeric/unconfirmed
# byte shown as read-only state, never written as guesswork.
PARAM_FIELDS = tuple(
    (name, offset, editable) for name, offset, editable in parameters.PARAMS
)


def button_fields():
    """The registered button-remap fields (0x0600-0x0638), derived from
    settings.FIELDS so the hypothesis list never drifts from the registry."""
    buttons = []
    for name, field in settings.FIELDS.items():
        absolute = (field.addr[1] << 8) | field.addr[0]
        if 0x0600 <= absolute <= 0x0638:
            buttons.append((name, field.addr))
    buttons.sort(key=lambda item: (item[1][1] << 8) | item[1][0])
    return buttons


def build_status(dev, report7_window=6.0):
    """Reads every registered EEPROM field (settings.FIELDS) and returns a
    JSON-ready dict: per-field addr/raw/decoded value, the format-hypothesis
    block (4-byte button methods, RF bit of 0x08D8 + warning byte 0x08D9) and
    the passive-report-7 cross-validation section. Raises CommandTimeout if
    the mouse does not answer and ValueError on a short reply."""
    by_addr = {}
    for name, field in settings.FIELDS.items():
        size = field.size
        if field.addr not in by_addr:
            by_addr[field.addr] = size
        elif size > by_addr[field.addr]:
            by_addr[field.addr] = size
    raw_by_addr = {}
    for addr, size in by_addr.items():
        resp = dev.read_eeprom(addr, size)
        if len(resp) < protocol.EEPROM_DATA_OFFSET + size:
            raise ValueError(
                "short EEPROM reply: got %d want %d"
                % (len(resp) - protocol.EEPROM_DATA_OFFSET, size)
            )
        raw_by_addr[addr] = bytes(
            resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + size]
        )

    fields = {}
    for name, field in settings.FIELDS.items():
        raw = raw_by_addr[field.addr][: field.size]
        fields[name] = {
            "addr": "0x{:04X}".format((field.addr[1] << 8) | field.addr[0]),
            "raw": raw.hex().upper(),
            "value": field.decode(raw),
        }

    hypothesis = build_hypothesis(raw_by_addr)
    report7 = capture_report7(dev, report7_window)
    checks = build_checks(dev, fields, report7)
    return {
        "fields": fields,
        "hypothesis": hypothesis,
        "report7": None if report7 is None else fmt(report7),
        "checks": checks,
    }


def build_hypothesis(raw_by_addr):
    """Emits the format hypotheses: the 4-byte button fields (0x0600-0x0638)
    print the raw method plus its decoded A Hub function (or hex when
    unknown), the RF block prints the strategy bit of 0x08D8 plus the
    separate low-power-warning byte 0x08D9 (P9 device diff, 2026-08-20 — the
    old shared-byte/bit-mask hypothesis was refuted on hardware), the toggle
    fields print a bit breakdown, and every Section-C mouse parameter prints
    its confirmed value semantics (bool toggle vs read-only raw byte). Uses
    the bytes already read by build_status, so no field is read twice."""
    buttons = []
    for name, addr in button_fields():
        method = raw_by_addr[addr][:4]
        buttons.append(
            {
                "name": name,
                "addr": "0x{:04X}".format((addr[1] << 8) | addr[0]),
                "raw": method.hex().upper(),
                "fn": button_mod.method_name(method, name),
                "left_click": button_mod.is_left_click(method),
            }
        )

    rf_addr = tuple(protocol.eeprom_bank0(protocol.RF_STRENGTHEN_SWITCH))
    warn_addr = tuple(protocol.eeprom_bank0(protocol.LOW_POWE_WARN_SWITCH))
    rf_raw = raw_by_addr[rf_addr][0]
    warn_raw = raw_by_addr[warn_addr][0]
    rf = {
        "addr": "0x{:04X}".format((rf_addr[1] << 8) | rf_addr[0]),
        "raw": rf_raw,
        "bits": "0b{:08b}".format(rf_raw),
        "rf_strengthen_switch": bool(rf_raw & protocol.RF_STRENGTHEN_MASK),
        "warn_addr": "0x{:04X}".format((warn_addr[1] << 8) | warn_addr[0]),
        "warn_raw": warn_raw,
        "low_power_warn_switch": warn_raw == protocol.LOW_POWE_WARN_ON,
    }

    toggles = []
    for name in TOGGLE_FIELDS:
        field = settings.FIELDS[name]
        addr = field.addr
        byte = raw_by_addr[addr][0]
        toggles.append(
            {
                "name": name,
                "addr": "0x{:04X}".format((addr[1] << 8) | addr[0]),
                "raw": byte,
                "bits": "0b{:08b}".format(byte),
            }
        )

    params = []
    for name, offset, editable in PARAM_FIELDS:
        addr = tuple(protocol.eeprom_bank0(offset))
        byte = raw_by_addr[addr][0] if addr in raw_by_addr else None
        params.append(
            {
                "name": name,
                "addr": "0x{:04X}".format(
                    protocol.EEPROM_BANK0_BASE + offset
                ),
                "raw": byte,
                "editable": editable,
                "state": (
                    "on"
                    if editable and byte
                    else "off"
                    if editable and not byte
                    else "raw"
                ),
            }
        )
    return {
        "buttons": buttons,
        "rf": rf,
        "toggles": toggles,
        "params": params,
    }


def capture_report7(dev, window=6.0):
    """Listens up to `window` seconds for a passive report 7 and returns the
    raw bytes, or None if it does not arrive (mouse asleep / quiet)."""
    end = time.time() + window
    while time.time() < end:
        data = dev.read_report(0.5)
        if data and len(data) > protocol.R7_CONFIG and data[0] == protocol.REPORT_PASSIVE:
            return data
    return None


def build_checks(dev, fields, report7):
    """Cross-validates the EEPROM read-back against the passive report 7:
    DPI gear index, DPI X and Y (at the current gear) against report-7
    dpiX/dpiY. Returns a list of {field, eeprom, report7, match}."""
    checks = []
    if report7 is None:
        return checks
    gear = report7[protocol.R7_DPI_GEAR]
    cur = fields["dpi_current"]["value"]
    checks.append(
        {
            "field": "dpi_current",
            "eeprom": cur,
            "report7": gear,
            "match": "MATCH" if cur == gear else "MISMATCH",
        }
    )
    dpi_x = report7[protocol.R7_DPI_X] | (report7[protocol.R7_DPI_X + 1] << 8)
    dpi_y = report7[protocol.R7_DPI_Y] | (report7[protocol.R7_DPI_Y + 1] << 8)
    for name, offset, report_value in (
        ("dpi_x", protocol.MOUSE_DPI_X_LIST, dpi_x),
        ("dpi_y", protocol.MOUSE_DPI_Y_LIST, dpi_y),
    ):
        if 0 <= gear < protocol.MOUSE_DPI_GEAR_LENGTH:
            addr = protocol.eeprom_bank0(offset + 2 * gear)
            resp = dev.read_eeprom(addr, 2)
            if len(resp) < protocol.EEPROM_DATA_OFFSET + 2:
                raise ValueError("short EEPROM reply for DPI list")
            raw = bytes(
                resp[protocol.EEPROM_DATA_OFFSET : protocol.EEPROM_DATA_OFFSET + 2]
            )
            eeprom_value = raw[0] | (raw[1] << 8)
        else:
            eeprom_value = None
        checks.append(
            {
                "field": name,
                "eeprom": eeprom_value,
                "report7": report_value,
                "match": (
                    "MATCH"
                    if eeprom_value is not None and eeprom_value == report_value
                    else "MISMATCH"
                    if eeprom_value is not None
                    else "UNVERIFIED"
                ),
            }
        )
    for name in ("rpt_24g", "rpt_usb"):
        checks.append(
            {
                "field": name,
                "eeprom": None,
                "report7": report7[
                    protocol.R7_RPT_24G
                    if name == "rpt_24g"
                    else protocol.R7_RPT_USB
                ],
                "match": "INFO",
            }
        )
    # Rate mirror (story 3-2): report-7 rpt_usb IS the rateCode from 0x0880,
    # validated on the device. Cross-check like the DPI fields instead of the
    # bare INFO above (which is kept for rpt_24g, not a rate code).
    rate_eeprom = fields["mouse_report"]["value"]
    rate_report = report7[protocol.R7_RPT_USB]
    checks.append(
        {
            "field": "rate_mirror",
            "eeprom": rate_eeprom,
            "report7": rate_report,
            "match": "MATCH" if rate_eeprom == rate_report else "MISMATCH",
        }
    )
    return checks


def print_status(status):
    print("=== EEPROM field status (raw/decoded) ===")
    for name, field in sorted(status["fields"].items()):
        print(
            "  {:<22} {}  raw={:<16} value={}".format(
                name, field["addr"], field["raw"], field["value"]
            )
        )
    print("=== Format hypotheses ===")
    for b in status["hypothesis"]["buttons"]:
        fn = b["fn"] or "RAW %s" % b["raw"]
        print(
            "  {:<22} {}  method={:<8} fn={}{}".format(
                b["name"],
                b["addr"],
                b["raw"],
                fn,
                "  (left-click)" if b["left_click"] else "",
            )
        )
    s = status["hypothesis"]["rf"]
    print(
        "  RF {}  raw={} bits={}  rf_strengthen_switch={}".format(
            s["addr"],
            s["raw"],
            s["bits"],
            "on" if s["rf_strengthen_switch"] else "off",
        )
    )
    print(
        "  low-power warning {}  raw={:02X}  low_power_warn_switch={}".format(
            s["warn_addr"],
            s["warn_raw"],
            "on" if s["low_power_warn_switch"] else "off",
        )
    )
    for t in status["hypothesis"]["toggles"]:
        print(
            "  toggle {:<16} {}  raw={} bits={}".format(
                t["name"], t["addr"], t["raw"], t["bits"]
            )
        )
    print("=== Section-C parameters (confirmed value semantics) ===")
    for p in status["hypothesis"]["params"]:
        if p["editable"]:
            print(
                "  param  {:<16} {}  raw={} -> TOGGLE ({})".format(
                    p["name"], p["addr"], p["raw"], p["state"]
                )
            )
        else:
            print(
                "  param  {:<16} {}  raw={} -> READ-ONLY (numeric/unconfirmed)".format(
                    p["name"], p["addr"], p["raw"]
                )
            )
    print("=== Passive report 7 cross-validation ===")
    if not status["checks"]:
        print("  no report 7 received (move the mouse to send one)")
    else:
        print("  report7 raw: {}".format(status["report7"]))
        for c in status["checks"]:
            print(
                "  {:<10} eeprom={!s:<10} report7={!s:<10} -> {}".format(
                    c["field"], c["eeprom"], c["report7"], c["match"]
                )
            )


def status_main(report7_window=6.0):
    dev = RapooDevice()
    try:
        dev.open()
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc))
        return 1
    try:
        status = build_status(dev, report7_window=report7_window)
    except CommandTimeout as exc:
        print(
            "ERROR: status aborted - no response from the mouse ({}); "
            "move the mouse to wake it, then retry.".format(exc),
            file=sys.stderr,
        )
        return 1
    except ValueError as exc:
        print(
            "ERROR: status aborted - invalid read-back: {}".format(exc),
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(
            "ERROR: status failed - could not read the device: {}".format(exc),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print("ERROR: status failed: {}".format(exc), file=sys.stderr)
        return 1
    finally:
        dev.close()
    print_status(status)
    return 0


def _confirm_prompt(message):
    """Prompt wrapper around input() so headless tests can inject an answer."""
    return input(message)


def _pair_destructive(args, stdin=None, prompt=None):
    """Gate + plan for the destructive receiver-pairing commands (0xA0/0xA1).

    Returns `([], None)` when no destructive flag is present (read-only mode).
    Otherwise returns `(["start_match", ...], rf_bytes)` after the Ask First
    gate passes. Raises `ValueError` with the refusal reason when:
      - `--write-rf` does not carry exactly 4 hex bytes,
      - `--i-understand-risks` is missing,
      - stdin is not a TTY (auto-refuse — no prompt, no hang), or
      - the human does not type the confirmation word.
    """
    if stdin is None:
        stdin = sys.stdin
    if prompt is None:
        prompt = _confirm_prompt
    destructive = []
    rf_bytes = None
    if args.start_match:
        destructive.append("start_match")
    if args.write_rf:
        if not args.start_match:
            raise ValueError(
                "--write-rf requires --start-match: the A Hub always pairs "
                "them, and a raw 0xA1 RF write without entering pairing mode "
                "can orphan the currently-paired mouse"
            )
        try:
            rf_bytes = bytes.fromhex(args.write_rf)
        except ValueError:
            raise ValueError(
                "--write-rf must be a hex string (got {!r})".format(args.write_rf)
            )
        if len(rf_bytes) != 4:
            raise ValueError(
                "--write-rf must be exactly 4 bytes (8 hex digits)"
            )
        destructive.append("write_rf")
    if not destructive:
        return [], None
    if not args.i_understand_risks:
        raise ValueError(
            "destructive pairing commands (0xA0/0xA1) require "
            "--i-understand-risks (Ask First)"
        )
    if not stdin.isatty():
        raise ValueError(
            "destructive pairing commands need a TTY for confirmation; "
            "stdin is not a TTY — refused (no prompt)"
        )
    try:
        answer = prompt(
            "This changes the receiver's pairing state (0xA0 start match / "
            "0xA1 write RF). Type 'yes' to continue: "
        )
    except EOFError:
        raise ValueError("confirmation not given (EOF)")
    if answer.strip().lower() != "yes":
        raise ValueError("confirmation not given")
    return destructive, rf_bytes


def pair_discover_main(window=6.0, want_result=False, destructive=None, rf_bytes=None):
    """Opens the 2.4G receiver ONLY (prefix 0xA5) and runs the read-only
    receiver-pairing discovery probes.

    Safe probes: connected-mouse VID/PID poll (`pairing.decode_connected_vid_pid`),
    an optional 0xA7 match-result read (raw dump, only behind `want_result`),
    and a fixed `window`-second listen for raw reports. `destructive` (already
    Ask First gated by `main`) fires the 0xA0/0xA1 commands and dumps their raw
    replies. A probe timeout marks the dump "partial" and exits non-zero; empty
    replies are printed raw and noted as asleep (non-fatal). When no receiver
    is present `open(prefix=0xA5)` raises `DeviceNotFound` first — the USB-cable
    mouse is never read.
    """
    dev = RapooDevice()
    try:
        dev.open(prefix=protocol.PREFIX_WIRELESS)
    except DeviceNotFound as exc:
        print(
            "ERROR: 2.4G receiver (24ae:1413) not found — no configuration "
            "interface with prefix 0xA5 ({}). Pairing commands target the "
            "receiver; plug it in, or use --status/--dump for the mouse.".format(
                exc
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc), file=sys.stderr)
        return 1
    partial = False
    try:
        print("== Receiver pairing discovery (receiver iface: {}) ==".format(dev.path))
        print("== 3-step pairing flow (A Hub deviceMatcher) ==")
        for i, step in enumerate(pairing.PAIRING_FLOW.values(), 1):
            print("  {}. {}".format(i, step))
        try:
            connected = pairing.decode_connected_vid_pid(dev)
        except CommandTimeout as exc:
            print("  connected mouse VID/PID: no response ({})".format(exc))
            partial = True
        except OSError as exc:
            print(
                "  connected mouse VID/PID: read failed: {}".format(exc),
                file=sys.stderr,
            )
            partial = True
        else:
            print(
                "  connected mouse VID: {:<8} PID: {}".format(
                    connected["vid"], connected["pid"]
                )
            )
        if want_result:
            try:
                frame = pairing.pairing_commands()["get_result"]
                resp = dev.query(frame[1], frame[2:], timeout=1.2, prefix=frame[0])
            except (CommandTimeout, OSError) as exc:
                print("  match result (0xA7): no response ({})".format(exc))
                partial = True
            else:
                result = resp[2] if len(resp) > 2 else None
                print(
                    "  match result (0xA7) raw: {}  reply byte: {!s}".format(
                        fmt(resp), result
                    )
                )
        for cmd in destructive or []:
            try:
                frame = pairing.pairing_commands(rf_bytes=rf_bytes)[cmd]
                dev.send_command(frame[1], frame[2:], prefix=frame[0])
                print("  {} sent: {}".format(cmd, fmt(frame)))
                resp = dev.read_response(timeout=1.2)
            except (CommandTimeout, OSError) as exc:
                print("  {} -> no reply: {}".format(cmd, exc), file=sys.stderr)
                partial = True
            except (KeyError, pairing.PairingDiscoveryError) as exc:
                print(
                    "  {} -> cannot build frame: {}".format(cmd, exc),
                    file=sys.stderr,
                )
                partial = True
            else:
                if resp is None:
                    print(
                        "  {} -> no input-6 reply (expected — 0xA0/0xA1 reply "
                        "only on the feature report, unreadable on hidraw); "
                        "watch report 7 / 0xA7 for the pairing result".format(cmd)
                    )
                else:
                    print("  {} -> {}".format(cmd, fmt(resp)))
        print(
            "== Raw reports ({}s listen window; move the mouse, or press "
            "L+M+R while matching to emit report 7) ==".format(window)
        )
        end = time.time() + window
        while time.time() < end:
            try:
                data = dev.read_report(0.5)
            except OSError as exc:
                print(
                    "  listen read failed: {}".format(exc),
                    file=sys.stderr,
                )
                partial = True
                break
            if not data:
                continue
            note = ""
            if (
                data[0] == protocol.REPORT_CMD
                and len(data) > 1
                and data[1] == protocol.RESP_EMPTY
            ):
                note = "  (empty — receiver/mouse asleep)"
            print(
                "  <- rid={:02d} len={} {}{}".format(
                    data[0], len(data), fmt(data), note
                )
            )
    finally:
        dev.close()
    if partial:
        print(
            "NOTE: discovery partial — some probes got no response.",
            file=sys.stderr,
        )
        return 1
    return 0


def pair_run_main(window=60.0, rf_bytes=None):
    """Runs the full A Hub `MatcherDialog` flow on the real receiver.

    Opens the 2.4G receiver ONLY (prefix 0xA5), prints the 3-step physical
    flow, sends `start_match` + `write_rf` (full frames via
    `pairing_commands()`; `rf_bytes` overrides the random RF), then runs the
    bounded matching loop: it listens report 7 raw (flagging a `0xB1` success
    sub-command), polls 0xA7 every ~1.5 s for `window` seconds and prints the
    result-byte history. This is the ON-DEVICE validation harness: the run is
    destructive (Ask First gated in `main` via `_pair_destructive`), the human
    must follow the 3 steps while it runs, and its observed evidence pins the
    success/failure semantics in FEATURES.md.
    """
    dev = RapooDevice()
    try:
        dev.open(prefix=protocol.PREFIX_WIRELESS)
    except DeviceNotFound as exc:
        print(
            "ERROR: 2.4G receiver (24ae:1413) not found — no configuration "
            "interface with prefix 0xA5 ({}). Pairing targets the receiver; "
            "plug it in and re-run --pair-run.".format(exc),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc), file=sys.stderr)
        return 1
    try:
        print("== Receiver pairing run (A Hub MatcherDialog flow) ==")
        print("== 3-step pairing flow (deviceMatcher) ==")
        for i, step in enumerate(pairing.PAIRING_FLOW.values(), 1):
            print("  {}. {}".format(i, step))
        frames = pairing.pairing_commands(rf_bytes=rf_bytes)
        # Readiness gate (mirrors the GUI session, F9): never fire the
        # destructive start_match/write_rf into a sleeping receiver. Probe
        # 0xA7 up to 3 attempts (~1 s apart); any reply proves it is awake.
        gate = frames["get_result"]
        awake = False
        for attempt in range(3):
            try:
                dev.query(gate[1], gate[2:], timeout=1.0, prefix=gate[0])
                awake = True
                break
            except CommandTimeout:
                print(
                    "  readiness probe (0xA7): no response (attempt {}/3)".format(
                        attempt + 1
                    ),
                    file=sys.stderr,
                )
                time.sleep(1.0)
            except OSError as exc:
                print("  readiness probe failed: {}".format(exc), file=sys.stderr)
                return 1
        if not awake:
            print(
                "  REFUSED: receiver not responding — power on the wireless "
                "mouse / bring it in range, then re-run",
                file=sys.stderr,
            )
            return 1
        for cmd in ("start_match", "write_rf"):
            frame = frames[cmd]
            try:
                dev.send_command(frame[1], frame[2:], prefix=frame[0])
            except OSError as exc:
                print(
                    "  send failed ({}) — receiver unplugged?".format(exc),
                    file=sys.stderr,
                )
                return 1
            print("  {} sent: {}".format(cmd, fmt(frame)))
        print(
            "  (0xA0/0xA1 reply only on the feature report, unreadable on "
            "hidraw — watch report 7 / 0xA7 for the pairing result)"
        )
        history = []
        b1_seen = False
        end = time.time() + window
        next_poll = time.time()
        while time.time() < end:
            try:
                data = dev.read_report(0.3)
            except OSError as exc:
                print(
                    "  listen read failed: {}".format(exc),
                    file=sys.stderr,
                )
                return 1
            if data and data[0] == protocol.REPORT_PASSIVE and len(data) > 1:
                note = (
                    "  <<< 0xB1 PAIRING SUCCESS"
                    if data[1] == protocol.PAIR_SUCCESS_REPORT
                    else ""
                )
                if data[1] == protocol.PAIR_SUCCESS_REPORT:
                    b1_seen = True
                print(
                    "  <- rid={:02d} len={} {}{}".format(
                        data[0], len(data), fmt(data), note
                    )
                )
            if time.time() >= next_poll:
                next_poll = time.time() + 1.5
                try:
                    frame = frames["get_result"]
                    resp = dev.query(
                        frame[1], frame[2:], timeout=1.0, prefix=frame[0]
                    )
                except (CommandTimeout, OSError) as exc:
                    print("  match result (0xA7): no response ({})".format(exc))
                    history.append(None)
                    continue
                result = pairing.match_result_byte(resp)
                history.append(result)
                print("  match result (0xA7): reply byte {!s}".format(result))
        print("== Result ==")
        print("  0xA7 result-byte history: {}".format(history))
        print("  0xB1 (report 7) observed: {}".format(b1_seen))
        if b1_seen:
            print("  ==> SUCCESS signal observed (report-7 0xB1)")
        nonzero = [r for r in history if r not in (None, 0)]
        if nonzero:
            print(
                "  ==> non-zero 0xA7 bytes observed (success candidate): "
                "{}".format(nonzero)
            )
        if 0 in history:
            print("  ==> failed bytes observed (0xA7 data[2]==0)")
        if not b1_seen and not nonzero and 0 not in history:
            print(
                "inconclusive: no result byte observed (receiver did not "
                "respond?)",
                file=sys.stderr,
            )
            return 1
        return 0
    finally:
        dev.close()


def factory_reset_gate(args, stdin=None, prompt=None):
    """Ask First gate for the destructive 0xAD factory reset (D3).

    Returns `True` after the confirmation passes. Raises `ValueError` with
    the refusal reason when `--i-understand-risks` is missing, stdin is not a
    TTY (auto-refuse — no prompt, no hang), or the human does not type the
    confirmation word.
    """
    if stdin is None:
        stdin = sys.stdin
    if prompt is None:
        prompt = _confirm_prompt
    if not args.i_understand_risks:
        raise ValueError(
            "destructive factory reset (0xAD) requires --i-understand-risks "
            "(Ask First)"
        )
    if not stdin.isatty():
        raise ValueError(
            "destructive factory reset needs a TTY for confirmation; "
            "stdin is not a TTY — refused (no prompt)"
        )
    try:
        answer = prompt(
            "This resets the mouse to the factory defaults (0xAD "
            "return_factory_settings): DPI list, sensor modes, RF strategy, "
            "button remaps and the device name are all wiped. Type 'yes' to "
            "continue: "
        )
    except EOFError:
        raise ValueError("confirmation not given (EOF)")
    if answer.strip().lower() != "yes":
        raise ValueError("confirmation not given")
    return True


def factory_reset_main(attempts=None):
    """Opens the device, runs `system.factory_reset` (0xAD + post-reset
    verification against the factory-default markers) and prints the
    before/after verify state. DESTRUCTIVE — Ask First gated in `main` via
    `factory_reset_gate`. Exits non-zero when the device does not answer or
    the post-reset state does not confirm the reset.
    """
    dev = RapooDevice()
    try:
        dev.open()
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc))
        return 1
    try:
        result = system.factory_reset(
            dev,
            attempts=attempts if attempts is not None else system.RESET_READ_ATTEMPTS,
        )
    except CommandTimeout as exc:
        print(
            "ERROR: factory reset aborted - no response (mouse asleep?): "
            "{}".format(exc),
            file=sys.stderr,
        )
        return 1
    except (system.FactoryResetAckError, system.FactoryResetVerifyError) as exc:
        print("ERROR: factory reset failed: {}".format(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("ERROR: factory reset aborted: {}".format(exc), file=sys.stderr)
        return 1
    finally:
        dev.close()
    print("ACKED: the device confirmed the 0xAD reset")
    print("BEFORE: {}".format(result["before"]))
    print("AFTER:  {}".format(result["after"]))
    print("OK - the device returned to the factory defaults")
    return 0


def dump_main():
    dev = RapooDevice()
    try:
        dev.open()
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc))
        return 1
    try:
        baseline = build_baseline(dev)
        write_baseline(settings.EEPROM_BASELINE_PATH, baseline)
    except CommandTimeout as exc:
        print(
            "ERROR: dump aborted - no response from the mouse ({}); "
            "baseline NOT written (move the mouse to wake it, then retry).".format(
                exc
            ),
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        print(
            "ERROR: dump aborted - could not write baseline: {}".format(exc),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print("ERROR: dump failed: {}".format(exc), file=sys.stderr)
        return 1
    finally:
        dev.close()
    print(
        "Baseline written to {} ({} blocks, 0x{:04X}-0x{:04X})".format(
            settings.EEPROM_BASELINE_PATH,
            len(baseline["blocks"]),
            baseline["start"],
            baseline["end"],
        )
    )
    return 0


def main():
    parser = argparse.ArgumentParser(prog="probe")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dump",
        action="store_true",
        help="dump full EEPROM bank 0 (0x0600-0x0A00) to the baseline JSON and exit",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="read every registered EEPROM field (raw/decoded), print format "
        "hypotheses and cross-validate against the passive report 7, then exit",
    )
    group.add_argument(
        "--pair-discover",
        action="store_true",
        help="open the 2.4G receiver only and run the receiver-pairing "
        "discovery probes (connected-mouse VID/PID poll, optional 0xA7 result, "
        "raw report dump over a fixed listen window), print the 3-step pairing "
        "flow, then exit",
    )
    group.add_argument(
        "--pair-run",
        action="store_true",
        help="run the full receiver-pairing flow (start match + write RF, then "
        "poll 0xA7 and listen report 7 for the 0xB1 success sub-command over "
        "PROBE_PAIR_WINDOW seconds), printing the result-byte history; "
        "DESTRUCTIVE — requires --i-understand-risks and a TTY confirmation",
    )
    group.add_argument(
        "--factory-reset",
        action="store_true",
        help="send the 0xAD return_factory_settings command and verify the "
        "device returned to the factory defaults (reads the DPI-current, RF "
        "byte and sensor-mode markers before/after, retrying while the mouse "
        "reboots); DESTRUCTIVE — requires --i-understand-risks and a TTY "
        "confirmation",
    )
    parser.add_argument(
        "--pair-result",
        action="store_true",
        help="(with --pair-discover) also read the 0xA7 match result and dump "
        "it raw",
    )
    parser.add_argument(
        "--start-match",
        action="store_true",
        help="(with --pair-discover) fire 0xA0 enter-pairing-mode; "
        "DESTRUCTIVE — requires --i-understand-risks and a TTY confirmation",
    )
    parser.add_argument(
        "--write-rf",
        metavar="RFHEX",
        help="(with --pair-discover) fire 0xA1 write-RF with the given 4-byte "
        "hex RF address; DESTRUCTIVE — requires --i-understand-risks and a TTY "
        "confirmation",
    )
    parser.add_argument(
        "--i-understand-risks",
        action="store_true",
        help="acknowledge the destructive commands (receiver-pairing 0xA0/0xA1, "
        "factory reset 0xAD — Ask First)",
    )
    args = parser.parse_args()

    if not (args.pair_discover or args.pair_run or args.factory_reset) and (
        args.pair_result
        or args.start_match
        or args.write_rf
        or args.i_understand_risks
    ):
        print(
            "ERROR: --pair-result/--start-match/--write-rf/--i-understand-risks "
            "only apply with --pair-discover/--pair-run/--factory-reset",
            file=sys.stderr,
        )
        return 2

    if args.dump:
        return dump_main()
    if args.status:
        return status_main()
    if args.factory_reset:
        try:
            factory_reset_gate(args)
        except ValueError as exc:
            print("REFUSED: {}".format(exc), file=sys.stderr)
            return 2
        return factory_reset_main()
    if args.pair_run:
        # The full flow always fires 0xA0 + 0xA1: reuse the Ask First gate.
        args.start_match = True
        try:
            _destructive, rf_bytes = _pair_destructive(args)
        except ValueError as exc:
            print("REFUSED: {}".format(exc), file=sys.stderr)
            return 2
        try:
            window = float(os.environ.get("PROBE_PAIR_WINDOW", "60.0"))
        except ValueError:
            print("REFUSED: PROBE_PAIR_WINDOW must be a float", file=sys.stderr)
            return 2
        if window <= 0:
            print("REFUSED: PROBE_PAIR_WINDOW must be positive", file=sys.stderr)
            return 2
        return pair_run_main(window=window, rf_bytes=rf_bytes)
    if args.pair_discover:
        try:
            destructive, rf_bytes = _pair_destructive(args)
        except ValueError as exc:
            print("REFUSED: {}".format(exc), file=sys.stderr)
            return 2
        try:
            window = float(os.environ.get("PROBE_PAIR_WINDOW", "6.0"))
        except ValueError:
            print("REFUSED: PROBE_PAIR_WINDOW must be a float", file=sys.stderr)
            return 2
        if window <= 0:
            print("REFUSED: PROBE_PAIR_WINDOW must be positive", file=sys.stderr)
            return 2
        return pair_discover_main(
            window=window,
            want_result=args.pair_result,
            destructive=destructive,
            rf_bytes=rf_bytes,
        )

    dev = RapooDevice()
    try:
        dev.open()
    except Exception as exc:
        print(i18n.tr("probe_error_open", error=exc))
        return 1
    print(i18n.tr("probe_config_interface", path=dev.path))

    battery_probe(dev)
    firmware_probe(dev)
    work_mode_probe(dev)
    eeprom_probe(dev)

    print(i18n.tr("probe_waiting"))
    end = time.time() + 6
    while time.time() < end:
        data = dev._read_report(0.5)
        if data:
            print(f"  <- rid={data[0]:02d} len={len(data)} {fmt(data)}")

    dev.close()
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

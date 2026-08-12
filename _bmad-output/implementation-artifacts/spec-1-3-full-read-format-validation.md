---
title: '1-3 Full read + format validation'
type: 'feature'
created: '2026-08-10'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 1
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/CONTEXT.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The EEPROM field formats are low-confidence (1B vs 2B LE, on/off, ranges), so later phases (DPI, parameters, buttons) cannot safely write values; the registry needs a read-only validation pass that resolves each format against the real device.

**Approach:** Add `--status` to `tools/probe.py`: read every registered field, decode it, cross-validate DPI/gear/polling against the passive report 7, and print format hypotheses for uncertain fields (2B button fields, shared 0x08D8 bit mask). On the real device, record validated formats in `docs/FEATURES.md` §2 (🔶→✅) and answer open questions 1/3/6/7 in the memlog, feeding confirmed sizes back into `settings.py` as data edits.

## Boundaries & Constraints

**Always:**
- Read-only: `--status` never writes EEPROM. Reads via `dev.read_eeprom` + `EEPROM_DATA_OFFSET` (raw reply slice), decoding through `settings.FIELDS` (AD-6) — the registry is the single name→address map.
- Every registered field is read and printed: name, absolute bank-0 address, raw bytes (hex), decoded value. The shared byte 0x08D8 is read once and printed under both field names (`rf_strengthen_switch`, `low_power_warn_switch`) with its bit layout.
- Cross-validation: capture passive report 7 (listen window, ~6 s, move the mouse) and compare EEPROM `dpi_current`/`dpi_x_list`/`dpi_y_list` against report-7 gear/X/Y, and report-7 `rpt_24g`/`rpt_usb`; print MATCH/MISMATCH per field. No report 7 → "no report" marker, not an error.
- Format hypothesis output for uncertain fields: 2B button fields (0x0600–0x0638) print both 1B and 2B LE interpretations; `dpi_enable_gear`, toggles and the 0x08D8 mask print a bit/byte breakdown. Conclusions are recorded (below), not auto-applied.
- Failures abort like `--dump`: device open failure, `CommandTimeout` (asleep — print the wake hint), short reply, `OSError` → clean message, non-zero exit, no partial report confusion.
- New tests for the status builder and CLI wiring in `tests/test_probe.py`; run `python3 -m unittest discover -s tests`.
- After on-device validation, record conclusions: update `docs/FEATURES.md` §2 (🔶→✅), answer Q1/3/6/7 in `_bmad-output/specs/spec-rapoo-vt7/.memlog.md`, and apply confirmed format corrections to `settings.py` `FIELDS` as data edits (AD-6) with matching test updates.

**Ask First:**
- If validating any field requires writing to the device (even a reversible test), HALT — this story is read-only.
- If a format cannot be confirmed from reads alone (e.g. button codes need a write to pin down), record it as still-open rather than guessing.

**Never:**
- No writes to the device. No GUI changes. No changes to `session.py`/worker.
- No raw `os.write`/`os.read` outside `device.py`; `probe.py` uses `read_eeprom`/`read_report` only.
- No new i18n keys (probe is a diagnostics CLI, AD-7).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy status | device awake, all fields readable | every field printed (name/addr/raw/decoded); report-7 cross-check MATCH | n/a |
| Device asleep / timeout | `read_eeprom` raises `CommandTimeout` | abort with wake hint, non-zero exit | clean message |
| Device absent / open fails | `open()` raises | return 1 + error message | clean message |
| No report 7 in window | listen timeout | cross-validation section marked "no report", status still prints | n/a |
| Short EEPROM reply | reply shorter than requested | `ValueError` → abort cleanly | clean message |
| Shared 0x08D8 byte | one read | both field interpretations + bit layout | n/a |

</frozen-after-approval>

## Code Map

- `docs/FEATURES.md` §2 -- authoritative field table; the validation pass flips 🔶→✅ and records answers to Q1 (formats), Q3 (lift-off), Q6 (0x08D8 mask), Q7 (report-7 mirror). Context file, edited only with validated findings.
- `src/rapoo_vt7/settings.py` -- `FIELDS` registry (34 entries incl. `dpi_x_list` 2B LE, `dpi_current` 1B index, `config_name` 16B string). Confirmed corrections become data edits here.
- `src/rapoo_vt7/protocol.py` -- already has `REPORT_PASSIVE=7`, `EEPROM_DATA_OFFSET=5`, `eeprom_bank0()`, §2 offsets. Add report-7 offset constants for gear/dpiX/dpiY/rpt_24g/rpt_usb used by cross-validation.
- `tools/probe.py` -- `--dump`/`build_baseline`/`write_baseline`/`dump_main` patterns (L76/105/128/169); the existing passive-listen loop (L195-197, 6 s window, `dev.read_report`) is the report-7 capture template. Add `--status` sibling.
- `tests/test_probe.py` -- existing FakeDev (address-derived data at `EEPROM_DATA_OFFSET`) + mock style; new status tests follow it.
- `_bmad-output/specs/spec-rapoo-vt7/.memlog.md` -- records Q1/3/6/7 answers.

## Tasks & Acceptance

**Execution:**
- [x] `tools/probe.py` -- add argparse `--status` and `status_main()`; `build_status(dev)` iterates `settings.FIELDS` (reading the shared 0x08D8 once, both names), slices `EEPROM_DATA_OFFSET`, decodes via `Field.decode`, and emits per-field name/addr/raw/decoded plus the format-hypothesis block; captures report 7 (~6 s) and cross-validates gear/X/Y/rpt vs EEPROM with MATCH/MISMATCH. Aborts on open failure/`CommandTimeout`/short reply/`OSError` with clean messages and non-zero exit.
- [x] `src/rapoo_vt7/protocol.py` -- add report-7 offset constants (gear, dpiX lo/hi, dpiY lo/hi, rpt_24g, rpt_usb) matching the raw-report layout. No behavioral change.
- [x] `tests/test_probe.py` -- NEW tests: `build_status` reads every FIELDS entry (0x08D8 read once, both names printed); decodes a known value; cross-validation MATCH and MISMATCH (fake report-7 buffer); no-report marker; `CommandTimeout`/short-reply abort; `status_main` open-failure returns 1; `--status` CLI wiring via patched `sys.argv`.
- [x] On-device validation (requires awake mouse): run `python3 tools/probe.py --status`, confirm each format, then update `docs/FEATURES.md` §2 (🔶→✅), answer Q1/3/6/7 in the memlog, and apply confirmed sizes to `settings.py` `FIELDS` with matching test updates.

**Acceptance Criteria:**
- Given an awake device, when `python3 tools/probe.py --status` runs, then every `settings.FIELDS` entry is printed with raw bytes and a decoded value, and the report-7 cross-check shows MATCH/MISMATCH per mirrored field.
- Given a `CommandTimeout` during status, when `status_main` runs, then it aborts with the wake hint and a non-zero exit.
- Given a short EEPROM reply, when `build_status` runs, then it raises `ValueError` and `status_main` returns non-zero with a clean message.
- Given report 7 absent in the window, when status runs, then the cross-validation section says "no report" without failing the run.
- Given confirmed device findings, when `docs/FEATURES.md` §2 and the memlog are updated, then validated fields show ✅ and Q1/3/6/7 have recorded answers, with `settings.py` formats matching.

## Spec Change Log

- On-device results (2026-08-10): all 34 fields read; formats match the registry as-is (DPI 2B LE, everything else 1B, config_name 16B string) — **no size corrections needed** in `settings.py`. Buttons left open (2B read showed no consistent pattern) per the Ask-First rule; recorded in FEATURES.md §D and memlog Q1. Q1/3/6/7 answered in the memlog.
- Review (2026-08-11): every claim verified against the repo — `--status` CLI (`tools/probe.py:447`), `R7_*` report-7 constants (`protocol.py:56`), 34 fields in `settings.py`, status tests in `tests/test_probe.py`, FEATURES.md §2 flipped 🔶→✅ with on-device read values, memlog Q1/3/6/7 answered. Suite: 102 tests OK. Approved → done.

## Design Notes

`--status` is the non-destructive companion to `--dump` (AD-9: separate process, own device). It produces the "real current configuration" report that FEATURES.md Phase 1 requires and is the vehicle for format resolution: since writes are forbidden in this story, the only way to pin a format is consistency with report 7 (DPI/gear/rpt) or an obvious interpretation (buttons read as 2B: high byte consistently 0 → 1B-padded). Anything a read cannot settle stays open in the memlog for the write-based phase (S4+). The `0x08D8` shared mask and the lift-off field (Q3) are explicitly hypothesis-printed, not auto-resolved.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass (existing + new status tests). **Ran: 63 tests OK.**
- `python3 -m py_compile src/rapoo_vt7/protocol.py tools/probe.py` -- expected: no errors. **Ran: OK.**
- `python3 tools/probe.py --status` -- expected (device awake): full field dump + report-7 cross-check; confirm formats recorded in FEATURES.md §2 and memlog Q1/3/6/7. **Ran on device: 34 fields, report 7 captured; gear/dpiX/dpiY MATCH (5000==5000); FEATURES.md §2 updated 🔶→✅; memlog Q1/3/6/7 answered.**

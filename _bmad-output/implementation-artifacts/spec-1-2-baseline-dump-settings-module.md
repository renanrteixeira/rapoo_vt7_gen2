---
title: '1-2 Baseline dump + settings module'
type: 'feature'
created: '2026-08-10'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/CONTEXT.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** No EEPROM field may be written before a baseline backup exists (golden rule), and later phases need a way to reference fields by name with validation instead of raw addresses.

**Approach:** Add `--dump` to `tools/probe.py` that reads bank 0 (`0x0600`–`0x0A00`) in 24-byte blocks and atomically writes a JSON baseline to `~/.cache/rapoo-vt7/eeprom_baseline.json`; add a new pure `settings.py` module registering every `docs/FEATURES.md` §2 field as a named, range-validated `Field`.

## Boundaries & Constraints

**Always:**
- `settings.py` is pure metadata + codec: `Field(addr, size, type, range, validator)` plus `encode`/`decode`. No `device` import, no file/device I/O, no GTK (AD-6).
- EEPROM addresses live only in `protocol.py` (bank-0 offsets, matching the existing `MOUSE_DPI_X_LIST` style). `settings.py` derives each 2-byte LE address via `protocol.eeprom_bank0(offset)` — never hardcodes absolute hex.
- Baseline path is a shared constant: `EEPROM_BASELINE_PATH = os.path.expanduser("~/.cache/rapoo-vt7/eeprom_baseline.json")` in `settings.py`, consumed by `probe.py --dump` (AD-6/AD-9).
- Dump covers full bank 0: start `0x0600`, end `0x0A00` (exclusive), 24-byte blocks, last partial block 16 bytes (43 blocks total).
- Baseline JSON written atomically (temp file + `os.replace`) — never a partial/corrupt baseline on failure (AD-10 discipline).
- A `--dump` failure (device asleep, `CommandTimeout`, unwritable path) aborts with an error message and leaves any previous baseline file untouched.
- Formats are NOT validated here: fields default to `size=1`/`type=uint` except DPI value fields (2-byte LE) and name (string). S3 corrects sizes as data edits, never code.
- New tests: `tests/test_settings.py` (registry/encode/decode) and `tests/test_probe.py` (dump builder + atomic write). Run `python3 -m unittest discover -s tests`.
- `probe.py` keeps its current unconditional diagnostic mode; `--dump` is an additional mode (argparse), not a replacement.

**Ask First:**
- If any EEPROM field is written to the real device in this story (even a reversible one), HALT — S2 must only capture the baseline.

**Never:**
- No writes to the device. No GUI changes. No `session.py`/worker changes (that is a later story; the golden-rule executor comes with the session).
- No i18n key additions (probe is a diagnostics CLI, not a user surface — AD-7).
- No raw `os.write`/`os.read` outside `device.py`; `probe.py` uses `read_eeprom` only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy dump | device awake, bank 0 readable | 43 blocks read, JSON written atomically | n/a |
| Device asleep / timeout | `read_eeprom` raises `CommandTimeout` | abort, no file written; previous baseline preserved | error message, non-zero exit |
| Unwritable path | baseline dir/file not writable | abort, previous file untouched | `OSError` → error message, non-zero exit |
| Re-run | baseline already exists | atomically replaced | n/a |
| Field encode | value in range → bytes LE of `size`; out of range | `ValueError` | n/a |
| Field decode | raw bytes | uint/bool/string, no validation | n/a |

</frozen-after-approval>

## Code Map

- `docs/FEATURES.md` §2 -- authoritative field table (A: DPI, B: performance, C: params, D: buttons, E: name). Registry registers every field listed here. Context file, not modified.
- `src/rapoo_vt7/protocol.py` -- already has `MOUSE_DPI_X_LIST=0x0288`, `MOUSE_DPI_Y_LIST=0x02C8`, `MOUSE_DPI_CUR=0x0298` (bank-0 offsets), `eeprom_bank0()` (L81). Add remaining §2 offsets here only.
- `src/rapoo_vt7/settings.py` -- NEW. `Field` + `encode`/`decode` + `FIELDS` + `EEPROM_BASELINE_PATH`. Pure module (AD-6).
- `tools/probe.py` -- main() L73; data at `protocol.EEPROM_DATA_OFFSET` (5). Add argparse + `--dump`: `build_baseline(dev)` (testable) and `write_baseline(path, data)` (temp+`os.replace`).
- `src/rapoo_vt7/config.py` -- atomic write pattern reference (L24-29).
- `tests/test_device.py` / `tests/test_battery.py` -- existing mock style; discovery via `python3 -m unittest discover -s tests`.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/settings.py` -- NEW pure module: `Field` dataclass (`addr` 2-byte LE tuple, `size`, `type` in {"uint","bool","string"}, `range` tuple or None, `validator` callable or None), `encode` (LE, length `size`, range/validator → `ValueError`; string → utf-8 padded/truncated), `decode` (uint LE / bool / string null-trimmed; no validation), `EEPROM_BASELINE_PATH`, and `FIELDS` dict keyed by snake_case names covering all §2 items, addresses via `protocol.eeprom_bank0(offset)`.
- [x] `src/rapoo_vt7/protocol.py` -- add bank-0 offset constants for §2 fields not yet present (DPI enable, perf mode, sensor params, RF, §C, buttons 0x0600–0x0638, name 0x09EC), flat `UPPER_CASE`. No behavioral change.
- [x] `tools/probe.py` -- argparse (`--dump`); `build_baseline(dev)` reads 0x0600–0x0A00 step 24 (last 16) via `read_eeprom`, slicing `EEPROM_DATA_OFFSET`, returning `{"device","captured_at","bank","start","end","blocks"}`; `write_baseline` atomic; prints path on success, non-zero exit on failure.
- [x] `tests/test_settings.py` -- NEW: registry covers §2 names; encode/decode roundtrip (uint 1B, uint 2B LE, bool, string); out-of-range `ValueError`; derived addresses match absolute bank-0 hex.
- [x] `tests/test_probe.py` -- NEW: `build_baseline` mocked → 43 blocks (`0x0600`,`0x0618`,…, last 16); `write_baseline` valid JSON; CommandTimeout/OSError abort without touching existing file.

**Acceptance Criteria:**
- Given `probe.py --dump` on an awake device, when run, then the baseline JSON exists with 43 blocks covering 0x0600–0x0A00.
- Given a `read_eeprom` `CommandTimeout` mid-dump, when `build_baseline` runs, then the exception propagates and no baseline file is created/replaced.
- Given a value in range, when `field.encode(v)` runs, then `len(out) == field.size` with correct LE layout; out of range → `ValueError`.
- Given a registered field, when `Field.decode` runs, then uint/bool/string decoding is correct without validation.
- Given the suite, when `python3 -m unittest discover -s tests` runs, then all tests pass.

## Spec Change Log

## Design Notes

`settings.py` stores `size`/`type` as data so S3's format corrections are data edits, not code changes (AD-6, spine deferred item). The baseline is a full bank-0 snapshot (not per-field) so golden-rule and restore have complete coverage; the registry is the name→address map later phases consume. `probe.py` remains a separate process with its own device (AD-9), never runs inside the app.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass (existing + new `test_settings.py` + `test_probe.py`).
- `python3 -m py_compile src/rapoo_vt7/settings.py src/rapoo_vt7/protocol.py tools/probe.py` -- expected: no errors.

## Suggested Review Order

**Field registry (design intent)**

- One source of truth mapping every FEATURES.md §2 name to a validated EEPROM field
  [`settings.py:76`](../../src/rapoo_vt7/settings.py#L76)

- Named `Field` metadata: type, size, range and validator drive both directions
  [`settings.py:22`](../../src/rapoo_vt7/settings.py#L22)

- Little-endian codec with range checks; strings NUL-padded, codepoint-safe truncation
  [`settings.py:29`](../../src/rapoo_vt7/settings.py#L29)

- Unvalidated decode mirrors the read path (S3 owns format validation)
  [`settings.py:62`](../../src/rapoo_vt7/settings.py#L62)

**Address derivation**

- Bounds-guarded bank-0 offset→address mapping shared by registry and dump
  [`protocol.py:131`](../../src/rapoo_vt7/protocol.py#L131)

- §2 offsets added for sensor, params, buttons and name
  [`protocol.py:123`](../../src/rapoo_vt7/protocol.py#L123)

**Baseline dump**

- Reads full bank 0 in 24-byte blocks; rejects truncated replies
  [`probe.py:76`](../../tools/probe.py#L76)

- Atomic temp+replace so a failed dump never corrupts a baseline
  [`probe.py:105`](../../tools/probe.py#L105)

- Error handling: timeout with wake hint, OSError and generic failures abort cleanly
  [`probe.py:128`](../../tools/probe.py#L128)

- `--dump` CLI wiring routes to `dump_main`
  [`probe.py:169`](../../tools/probe.py#L169)

**Tests**

- Registry↔FEATURES.md drift test (skips the not-applicable §2.F section)
  [`test_settings.py:105`](../../tests/test_settings.py#L105)

- Dump builder, atomic write and failure paths (including CLI entry point)
  [`test_probe.py:42`](../../tests/test_probe.py#L42)

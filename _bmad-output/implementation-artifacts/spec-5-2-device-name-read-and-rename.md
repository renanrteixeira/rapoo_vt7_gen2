---
title: 'Device name read and rename (5-2)'
type: 'feature'
created: '08-13-2026'
status: 'done'
review_loop_iteration: 0
context: []
baseline_commit: '83b0d42cd4fc62e3806cd7ca7d0e42e3b8f57f02'
---

## Intent

**Problem:** The mouse's 16-byte device name (`0x09EC`, bank-0 `CONFIG_NAME`, reads "CFG1" on the real device) can be read via the settings registry but cannot be viewed or changed from the app — users cannot label their device.

**Approach:** Add name read/write primitives to `system.py` (A Hub semantics: trim → UTF-8 bytes ≤ 16 → NUL-pad to 16 → `write_eeprom_verify`) and a device-name section in the existing "Sistema" tab: read the name on tab open, edit in a `Gtk.Entry`, "Rename" writes via `submit(..., wake=True)` with immediate readback verify, result surfaced non-blocking and localized.

## Boundaries & Constraints

**Always:**
- Golden rule on the write: EEPROM write ≤ 24 B bank-0 → verify by immediate re-read (`write_eeprom_verify`); never write before the baseline exists.
- Name encoding matches the A Hub `renameConfig`: trim user input → UTF-8 bytes → reject if > 16 bytes (a multi-byte char counts as 2) → NUL-pad to exactly 16 → write.
- Read decodes the first NUL-terminated segment, UTF-8 `errors="replace"` (raw "CFG1" shown as-is — no A Hub default-config localization).
- All user strings localized (`i18n.LANGS` pt_BR/en/es); re-translation on language change re-renders the name row labels.
- Name read on tab open is passive (no wake); rename is user-initiated via `submit(..., wake=True)`. Callbacks run on the monitor thread → `GLib.idle_add` before touching GTK.
- Errors surface non-blocking (System-tab status label).
- GUI-only user surface — `probe.py` stays a diagnostics harness.

**Ask First:**
- If the real device returns a non-ACK reply or a verify mismatch during the rename write, do not retry — surface the error and ask the user how to proceed.

**Never:**
- No changes to `Field.encode` in `settings.py` (the name module encodes explicitly; the registry stays read-only for `probe.py --status`).
- No writes from passive paths; no auto-rename; no deletion/clear-name feature (A Hub `deleteConfig` is out of scope).
- No other EEPROM fields, factory reset, or pairing in this story.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| READ_HAPPY | mouse connected, tab opens | current name shown (e.g. "CFG1"), NUL-stripped | N/A |
| READ_ERROR | device asleep/timeout on open | status shows localized read error, entry stays empty | non-blocking; no wake |
| RENAME_HAPPY | ≤16 UTF-8 bytes, awake | write + readback verify → success status, name shown | N/A |
| RENAME_TOO_LONG | entry > 16 UTF-8 bytes | refuse write, localized "too long" status | no device write |
| RENAME_EMPTY | entry empty or all spaces (trimmed) | refuse write, localized "empty" status | no device write |

## Code Map

- `src/rapoo_vt7/system.py` -- 5-1 sibling: `_addr`/`_read` helpers, typed errors (:54-67). Add name primitives.
- `src/rapoo_vt7/protocol.py` -- `CONFIG_NAME = 0x03EC` (:144); `eeprom_bank0` (:152), `EEPROM_DATA_OFFSET=5` (:72), `EEPROM_READ_MAX=24` (:87).
- `src/rapoo_vt7/device.py` -- reuse `read_eeprom` (:231) / `write_eeprom_verify` (:259); no changes.
- `src/rapoo_vt7/gui.py` -- `_build_system_section` (:666) add name row (Entry+button); `set_system_message` (:719); `_on_lang_changed` (:1216) re-translates.
- `src/rapoo_vt7/main.py` -- window build (:109) wires `on_rename`; `_on_factory_reset` (:485) = submit(wake=True) template.
- `src/rapoo_vt7/i18n.py` -- `LANGS` pt_BR (:3)/en (:173)/es (:343); factory_reset key block = pattern.
- `tests/test_system.py` -- `FakeDev.read_eeprom` (:36), `FakeMonitor.submit`, `FakeWindow.set_system_message`, stubs `_StubButton/_StubLabel`.
- `docs/FEATURES.md` -- roadmap (:288), §2.E row (:135).

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/system.py` -- add `read_device_name(dev)` (read 16 B, NUL-strip, UTF-8 decode) and `write_device_name(dev, name)` (trim→UTF-8→reject>16→NUL-pad→`write_eeprom_verify`) + typed errors (`NameTooLongError`, `NameEmptyError`, `NameVerifyError`) -- protocol sibling pattern
- [x] `src/rapoo_vt7/gui.py` -- add device-name section to `_build_system_section` (Entry + Rename button + status reuse + busy guard), read on tab open, re-translation -- user surface
- [x] `src/rapoo_vt7/main.py` -- wire `_on_rename` (submit wake=True) + `_rename_done`/`_rename_error` (GLib.idle_add, localized, refresh name row) -- monitor integration
- [x] `src/rapoo_vt7/i18n.py` -- add name keys (pt_BR/en/es): section label, entry placeholder, rename button, statuses (read_error, empty, too_long, success, verify_error) -- localization
- [x] `tests/test_system.py` -- add core tests: read decodes/NUL-strips, encode pads / refuses >16 / refuses empty, verify roundtrip, GUI section construction, rename via FakeMonitor with wake=True -- coverage (core I/O + AC)
- [x] `docs/FEATURES.md` -- flip roadmap row (:288) and mark §2.E row updated when merged -- tracking

**Acceptance Criteria:**
- Given mouse connected, when the System tab opens, then the current name is read and shown (non-blocking).
- Given ≤16-byte input and awake mouse, when Rename is clicked, then `write_eeprom_verify` succeeds, readback is shown, and a localized success status appears.
- Given >16-byte or empty/whitespace input, when Rename is clicked, then the write is refused with a localized status and no device write occurs.

## Spec Change Log

_Empty until the first bad_spec loopback._

## Design Notes

The name module encodes explicitly instead of reusing `Field.encode` (`settings.py:39-42` truncates at the size boundary without re-appending a NUL and can return < 16 bytes when a multi-byte char is cut — divergent from the A Hub rule). The registry stays the read-only source for `probe.py --status`. "CFG1" shown as raw text (A Hub's localized default-config label for bank 0 not replicated).

## Verification

**Commands:**
- `python3 -m pytest tests/test_system.py tests/test_settings.py -q` -- all pass (303 baseline + new)
- `python3 -m compileall -q src/rapoo_vt7/system.py src/rapoo_vt7/gui.py src/rapoo_vt7/main.py src/rapoo_vt7/i18n.py` -- no errors

**Manual checks (if no CLI):**
- `./run.sh` → "Sistema" tab: "CFG1" appears; rename on real device; success + re-open persists; >16-byte and empty inputs refused.

## Suggested Review Order

**Encoding + verified write (core)**

- A Hub-compatible name codec: trim → UTF-8 ≤16B → NUL-pad, typed errors
  [`system.py:195`](../../src/rapoo_vt7/system.py#L195)

- Golden-rule verified write with readback decode
  [`system.py:226`](../../src/rapoo_vt7/system.py#L226)

**Busy-guard + System tab surface**

- Op-scoped busy flags — a reset/rename completion never lifts the other's guard
  [`gui.py:793`](../../src/rapoo_vt7/gui.py#L793)

- Rename click with sync-exception safety and busy guard
  [`gui.py:731`](../../src/rapoo_vt7/gui.py#L731)

- Focus-guarded entry update (read never clobbers typing) + tab-open read
  [`gui.py:753`](../../src/rapoo_vt7/gui.py#L753)

**Monitor wiring**

- submit(wake=True) rename with pre-validation refusal
  [`main.py:554`](../../src/rapoo_vt7/main.py#L554)

- Verify-mismatch surfaces error and re-reads the stored name
  [`main.py:583`](../../src/rapoo_vt7/main.py#L583)

- Factory-reset done now also refreshes the name row
  [`main.py:519`](../../src/rapoo_vt7/main.py#L519)

**Localization + tests**

- 8 name keys × 3 locales (placeholder-format safe)
  [`i18n.py:172`](../../src/rapoo_vt7/i18n.py#L172)

- Core codec, busy-guard, re-translation and wake-path coverage
  [`test_system.py:333`](../../tests/test_system.py#L333)
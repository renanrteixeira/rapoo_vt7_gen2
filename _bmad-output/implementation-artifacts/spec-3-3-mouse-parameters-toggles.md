---
title: '3-3 Mouse parameters toggles'
type: 'feature'
created: '2026-08-11'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/src/rapoo_vt7/performance.py'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/src/rapoo_vt7/settings.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/gui.py'
  - '{project-root}/tools/probe.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app exposes performance mode and RF state but none of the
Section-C mouse parameters (motion sync, linear/wave correction, sensor angle,
glass tracking, press/release debounce, lift-off height, DC switch, sleep time,
low power). Several of those bytes have unconfirmed semantics, and a toggle
must never guess at them.

**Approach:** Expose the Section-C parameters in the Desempenho tab as state +
toggles following the read → show → write → re-read pattern, and confirm each
byte's semantics with a safe on-device write-test (read → write → re-read →
restore) during implementation. Fields that cannot be confirmed are gated
(read-only or hidden) and recorded as deferred work — never shipped as
guesswork toggles.

## Boundaries & Constraints

**Always:**
- Every §C write targets bank 0, is ≤24 bytes, and is confirmed by an immediate
  re-read (`write_eeprom_verify`); a readback mismatch rejects the change and
  surfaces an error — the new value is never accepted.
- Golden rule: no write before the baseline exists (`~/.cache/rapoo-vt7/eeprom_baseline.json`);
  every on-device write-test must restore the original byte when done.
- Do not conflate §C "low power" with the low-power-warning bit of the shared
  `0x08D8` byte (RF feature, story 3-2). If a §C byte proves bit-packed, use the
  masked-write pattern (read-modify-write preserving unrelated bits + verify).
- GUI-only surface. All user strings live in `i18n.LANGS` (pt_BR/en/es) and new
  labels must be re-translated on language change (`_on_lang_changed`).
- User-initiated toggles are attempted even when the mouse is asleep
  (`submit(..., wake=True)`); background reads while asleep are rejected, not
  queued. On error/asleep the last known values are retained, never nulled.
- A toggle is shipped only for a field whose byte semantics the on-device
  write-test confirmed (value meaning, bit positions). `mouse_scan` (`0x0881`)
  stays out of the UI. `python3 -m unittest discover -s tests` must pass.

**Ask First:**
- If the write-test contradicts a planned toggle (e.g. linear ripple reads `0x03`
  → numeric, not bool), HALT and ask whether to present that field as a numeric
  control, read-only state, or gate it.
- If wave correction cannot be mapped to a confirmed address after probing, ask
  whether to leave it out of 3-3 (recommended) or gate it.

**Never:**
- Do not change performance-mode slot semantics (story 3-1) or the RF shared-byte
  semantics (story 3-2).
- Do not implement DPI or button-remap behavior.
- Do not write any byte without a confirmed field plus readback verify.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Parameter state read | device available | read each §C byte and expose its current state in the tab | read failure → section error text, last values retained |
| Toggle write | user flips a checkbox | masked/single-byte write, confirmed by re-read; new state shown | readback mismatch → reject, error surfaced, change not accepted |
| Unconfirmed field | semantics not confirmed by write-test | no toggle shipped; field read-only or hidden; defer entry appended | N/A |
| Mouse asleep | background read / user toggle | read rejected, last values kept; toggle attempted with wake | device timeout → monitor back to "asleep", localized message |
| Bit-packed byte | a §C byte shares bits | masked write preserves unrelated bits, verified by re-read | mismatch → reject |
| Language switch | user changes language | new §C labels re-translated | N/A |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/protocol.py:116-141` -- §C address constants (`MOUSE_*`),
  offsets; `eeprom_bank0` at `:152-158`. Addresses confirmed 1B.
- `src/rapoo_vt7/settings.py:21-69` -- `Field` codec (encode/decode, size/type);
  `:76-123` -- `FIELDS` registry incl. §C entries (all `size=1, type="uint"`,
  no ranges). New fields require updating `tests/test_settings.py` pins.
- `src/rapoo_vt7/performance.py` -- the pattern a new `parameters.py` mirrors:
  `_read` `:70-76`, `_write_shared_byte` `:108-121`, `read_perf_state` `:136-150`
  (isolated section error), `set_mode` `:189-201` (write+verify).
- `src/rapoo_vt7/device.py:259-267` -- `write_eeprom_verify` (write then readback,
  raises `ValueError` on mismatch).
- `src/rapoo_vt7/main.py:287-304` -- `_on_set_rf` toggle template (submit wake);
  `:339-360` -- `_refresh_perf`/`_maybe_refresh_perf` (refresh + empty-tab retry);
  `:24-34` -- `_perf_slot_from_monitor`.
- `src/rapoo_vt7/gui.py:247-385` -- Desempenho tab build/render (radios, RF
  checkboxes, `_perf_loading` guard, error isolation); `:586-609` --
  `_on_lang_changed` (re-translate labels — pitfall: 3-1 radios weren't).
- `src/rapoo_vt7/i18n.py:31-51` -- pt_BR perf/rf keys (en `:101-121`, es
  `:171-191`) — add §C keys to all three locales.
- `tools/probe.py:128-135` -- `TOGGLE_FIELDS` hypothesis list; `:196-239` --
  hypothesis decode; extend to confirm §C semantics on-device.
- `docs/FEATURES.md:59-72` -- §C table (addresses ✅, values 🔶); update to
  confirmed semantics after the write-test.
- `tests/test_performance.py:8-43` -- `FakeDev`/`FakeMonitor` test doubles to
  reuse; `tests/test_i18n.py` key-parity tests; `tests/test_settings.py` registry
  address pins.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/parameters.py` (new) -- §C read/set primitives following
  `performance.py`: per-field read, write+verify, masked write for bit-packed
  bytes; section read bundling reads with isolated per-field errors.
- [x] `src/rapoo_vt7/main.py` -- toggle handlers (submit `wake=True`) + section
  refresh/error callbacks wired like `_on_set_rf`/`_refresh_perf`.
- [x] `src/rapoo_vt7/gui.py` -- §C section in the Desempenho tab: checkbox per
  confirmed toggle, read-only state for numeric/unconfirmed fields; render +
  `_perf_loading` guard + error isolation + re-translation in `_on_lang_changed`.
- [x] `src/rapoo_vt7/i18n.py` -- §C label/status strings in pt_BR/en/es.
- [x] `tools/probe.py` -- extend `--status`/hypothesis decode to the §C fields
  and record confirmed value semantics.
- [x] `tests/test_parameters.py` (new) -- FakeDev tests: read, write+verify,
  masked write preserves unrelated bits, readback mismatch rejected, isolated
  section error, asleep behavior; extend `tests/test_i18n.py` parity.
- [x] On-device write-test -- for each intended toggle: read → write → re-read →
  restore on the live device; confirm semantics; gate unconfirmed fields
  (read-only + defer entry).
- [x] `docs/FEATURES.md` -- update §2.C with confirmed value semantics and mark
  the Phase-3 roadmap item done.

**Acceptance Criteria:**
- Given a live device, each confirmed §C toggle shows its current state and
  flipping it writes → re-reads → updates the shown state without touching other
  fields.
- Given a readback mismatch, the change is rejected and an error is surfaced —
  never accepted.
- Given a slider write, only values on the parameter's A Hub grid are written
  (off-grid/off-range refused) and a drag coalesces into one write, not one
  per tick.
- Given an unconfirmed field, no toggle is shipped for it (read-only/hidden +
  defer entry).
- Given a language change, the new §C labels re-translate.
- Given the test suite, `python3 -m unittest discover -s tests` passes.

## Spec Change Log

- 2026-08-11 (implement): new `parameters.py` (§C read/set with `write_eeprom_verify`;
  toggles only for write-test-confirmed bools `motion_sync`/`glass_track`/`dc_switch`,
  rest read-only), Desempenho tab section (`gui.py`), `main.py` wiring (submit
  wake=True + refresh/error), `probe.py --status` §C decode, 18 §C i18n keys × 3
  locales, `tests/test_parameters.py` (18 tests) + i18n parity. On-device
  write-test (read→write→re-read→restore, all 11 §C bytes) confirmed motion/
  glass/DC as 0/1 bools and that **no §C byte is bit-packed** — so the matrix's
  "bit-packed masked write" row is N/A (no masked write needed; the shared
  `0x08D8` masks belong to story 3-2). Ask First items resolved with the spec's
  documented defaults (the human pre-approved gating unconfirmed fields):
  `linear_ripple` numeric → read-only, `sensor_angle` scale unconfirmed →
  read-only, `low_power` two addresses unresolved → read-only, wave correction →
  not exposed; 4 defer entries appended. Suite 139→158, all pass.
- 2026-08-12 (review): slider UI added after the 2026-08-11 story shipped
  (human renegotiation; see Design Notes below): `parameters.SELECTABLE`
  (debounce 0–32 ms step 2, sleep 2–120 min, angle −30°..30° signed, lift-off
  1.0–2.0 mm byte 1..11) + `set_param_choice` (A-Hub grid enforced,
  readback-verified) and Gtk.Scale sliders in the Parâmetros tab. The
  debounce/sleep/angle/lift-off byte maps are OUR inference (A Hub defaults
  agree) — definitive = diff an A Hub write (P9). Review patches applied:
  slider drags coalesced to a 150 ms debounce + step-grid snap (no per-tick
  EEPROM writes, no off-grid refusals from drags); off-range/off-grid raw
  bytes disable the slider instead of leaving a stale enabled value;
  `PARAM_UNITS` removed (all three entries became SELECTABLE); low_power
  tooltip moved onto the read-only row (the checkbox branch was dead code);
  module docstring, CONTEXT.md §8.B3 and FEATURES.md §2.C header de-contradicted.
  New tests: decode boundaries (lift_off 0/12, angle ±30 span, non-numeric
  reject), off-grid snap/off-range disable, error retains slider values,
  `_on_set_param_choice` wake+choice and `_param_changed` option/toggle
  formatting. Suite 204→211, all pass.

## Design Notes

The on-device write-test is part of the implementation and mirrors how 3-1/3-2
validated: baseline exists → write the candidate byte → re-read → restore →
log. That is what confirms each field's value semantics (bool 0/1 vs numeric,
bit positions) before its toggle is enabled, and feeds `docs/FEATURES.md` §2.C.

Numeric fields (debounce ms, sleep minutes, sensor angle, lift-off mm) were
later human-renegotiated into **selectable sliders**: when a field's A Hub
range/step is known (`parameters.SELECTABLE`) it renders as a Gtk.Scale, and
a write only happens for values on that grid (`set_param_choice`, readback
verified). Unconfirmed ones (linear_ripple, low power, wave correction) stay
read-only/gated with defer entries unless the live probing resolves them.

Toggle UI clones the RF checkboxes (Gtk.CheckButton + `_perf_loading` guard);
per-field read errors are isolated like `read_perf_state` so one broken field
never blanks the whole tab.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass.
- `python3 tools/probe.py --status` -- expected: §C fields decoded with the
  confirmed value semantics from the write-test.
- On-device (manual): run the app, flip each confirmed toggle, confirm the state
  sticks and re-reads back; confirm unconfirmed fields are disabled.

## Suggested Review Order

**Slider write path**

- Entry point: the drag handler coalesces per-tick writes into one verified write.
  [`gui.py:567`](../../src/rapoo_vt7/gui.py#L567)

- One-shot flush keeps the coalesced write out of the render guard.
  [`gui.py:583`](../../src/rapoo_vt7/gui.py#L583)

- Grid + range enforcement: only A Hub values ever reach the device.
  [`parameters.py:224`](../../src/rapoo_vt7/parameters.py#L224)

- Byte encoding with the same grid/range guard (`signed`, `mm` tags).
  [`parameters.py:106`](../../src/rapoo_vt7/parameters.py#L106)

**Render plan (pure function)**

- Off-range/off-grid raw bytes snap to the grid or disable the slider.
  [`gui.py:62`](../../src/rapoo_vt7/gui.py#L62)

- Read-only rows are unit-less now that all units moved into SELECTABLE.
  [`gui.py:103`](../../src/rapoo_vt7/gui.py#L103)

- The declared slider ranges and byte maps (inference, P9 pending).
  [`parameters.py:57`](../../src/rapoo_vt7/parameters.py#L57)

**GUI binding + notifications**

- Slider construction, tooltips, and low_power tooltip on the read-only row.
  [`gui.py:497`](../../src/rapoo_vt7/gui.py#L497)

- Re-translate on language change (slider labels + low_power tooltip).
  [`gui.py:932`](../../src/rapoo_vt7/gui.py#L932)

- Fixed `{param}` placeholder — the pre-review code raised KeyError at runtime.
  [`main.py:379`](../../src/rapoo_vt7/main.py#L379)

**Docs**

- §2.C header now separates confirmed writability from inferred byte maps.
  [`FEATURES.md:63`](../../docs/FEATURES.md#L63)

- §8.B3 no longer contradicts the sliders paragraph.
  [`CONTEXT.md:294`](../../CONTEXT.md#L294)

**Tests**

- Slider wiring (wake + choice), notification formatting, decode boundaries.
  [`test_parameters.py:364`](../../tests/test_parameters.py#L364)

- Render-plan grid snap, off-range disable, error value retention.
  [`test_gui_units.py:42`](../../tests/test_gui_units.py#L42)

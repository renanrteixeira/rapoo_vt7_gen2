---
title: '3-2 RF + polling rate'
type: 'feature'
created: '2026-08-11'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/src/rapoo_vt7/performance.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/src/rapoo_vt7/settings.py'
  - '{project-root}/tools/probe.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The application requires a secure RF and polling rate feature that treats byte `0x08D8` as a shared byte for RF and low-battery warnings, and determines the active performance slot based on the confirmed rate-code mapping, without compromising existing performance mode behavior. Note that the polling rate affects performance profiles. This functionality exists in the Windows application. Could you please confirm this via the website or manual?

**Approach:** Expose the RF strategy and polling rate state within the application, preserve the shared-byte semantics for `0x08D8`, and base polling rate behavior on the validated rate-code-to-slot mapping derived from `rpt_usb` (Report 7) and `0x0880`.

## Boundaries & Constraints

**Always:**
- Treat `0x08D8` as a shared byte: `protocol.RF_STRENGTHEN_SWITCH` and `protocol.LOW_POWE_WARN_SWITCH` are the same EEPROM address, and writes must preserve unrelated bits.
- Use `protocol.R7_RPT_USB` as the trusted active rate code source for slot detection; `R7_RPT_24G` is not a rate code and must not be used for active slot selection.
- Map polling-rate codes exactly as validated in `performance.py`: `125→8`, `250→4`, `500→2`, `1000→1`, `2000→132`, `4000→130`, `8000→129`; slot indices are `0..6` respectively.
- Any polling-rate or RF write must be confirmed by a read-back and must not write other performance or sensor fields.
- Do not change current performance-mode writes or mode-selection semantics from story 3-1.

**Ask First:**
- If the implementation requires a separate polling-rate selector UI instead of exposing state only, or if the existing active-slot detection semantics need to be changed beyond using `rpt_usb` / `perf.SLOT_DEFAULT`.

**Never:**
- Do not modify `src/rapoo_vt7/performance.py` to change performance-mode-slot semantics.
- Do not implement DPI or button-remap behavior in this story.
- Do not treat `0x08D8` as two independent bytes; maintain the shared-bit-mask behavior.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| RF strategy read | device available | read `0x08D8`, expose `rf_strengthen_switch` and `low_power_warn_switch` state consistently | if read fails, show a clear RF status error |
| RF strategy write | user toggles RF mode | write masked byte to `0x08D8`, verify by re-reading, preserve unrelated bits | if readback differs, do not accept the change and surface error |
| Shared byte masking | `0x08D8` contains both RF and low-power bits | preserve the low-power warning bits when changing RF strategy and vice versa | avoid writes that zero unrelated bits |
| Polling-rate state | report 7 includes `rpt_usb` | derive active slot from rate code and keep performance-mode slot semantics consistent | fallback to default slot if `rpt_usb` unavailable |
| Polling-rate UI | active device | show current polling rate in Hz or poll state in UI | do not allow a polling-rate change path that bypasses slot mapping |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/protocol.py` -- defines `RF_STRENGTHEN_SWITCH`, `LOW_POWE_WARN_SWITCH`, `MOUSE_REPORT`, `R7_RPT_USB`, `R7_RPT_24G`, and EEPROM bank/offset conventions.
- `src/rapoo_vt7/settings.py` -- registers the RF and low-power warning fields at the shared `0x08D8` address.
- `src/rapoo_vt7/main.py` -- active slot detection via report 7, device refresh lifecycle, and the performance-mode tab integration surface.
- `src/rapoo_vt7/performance.py` -- validated polling-rate code map and active slot semantics for performance mode.
- `tools/probe.py` -- existing shared-byte read logic and polling-rate reporting probes.
- `docs/FEATURES.md` -- confirmed RF/polling-rate behavior and the shared-byte semantics for the VT7.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/settings.py` -- ensure the shared `0x08D8` fields are registered and comment their shared-byte relationship clearly.
- [x] `src/rapoo_vt7/main.py` -- preserve active-slot detection from `rpt_usb`, and surface RF/polling-rate state in the app without changing performance-mode write semantics.
- [x] `src/rapoo_vt7/protocol.py` -- keep `R7_RPT_USB` as the polling-rate source and document that `R7_RPT_24G` is not a rate code.
- [x] `tools/probe.py` -- use or extend its existing 0x08D8 shared-byte probe to confirm RF strategy and low-power warning bits.
- [x] `docs/FEATURES.md` -- record the validated rate-code-to-slot mapping and the RF shared-byte semantics in the feature inventory.

**Acceptance Criteria:**
- Given a live device and report 7 `rpt_usb`, the RF/polling-rate state is exposed consistently and does not alter performance-mode slot semantics.
- Given a write to `0x08D8`, the implementation preserves unrelated bits and verifies the write by read-back.
- Given `rpt_usb` is unavailable, the app continues to use `perf.SLOT_DEFAULT` for performance-mode slot detection and does not crash.
- Given the feature is implemented, it does not touch DPI behavior, button-remap flows, or performance mode write semantics from story 3-1.
- Given the current test suite, `python3 -m unittest discover -s tests` should pass.

## Spec Change Log

- 2026-08-11 (implement): added `RF_STRENGTHEN_MASK`/`LOW_POWE_WARN_MASK`
  (`protocol.py`), shared-byte comment for both fields registered at `0x08D8`
  (`settings.py`), masked `read_rf`/`write_rf_strengthen`/`write_low_power_warn`
  with readback verify (`performance.py`), `rate_hz()` exposure, RF/polling-rate
  state + toggles in the Desempenho tab (`gui.py`/`main.py`), `0x08D8` decode in
  `tools/probe.py`, and the rate-code→slot mapping + shared-byte semantics in
  `docs/FEATURES.md` §2.B. 15 new tests; suite 117→132, all pass.
- 2026-08-11 (review loop, no spec amendments — code-only patches): isolated
  `read_rf` errors from `_refresh_perf` via `perf.read_perf_state` (an RF read
  failure now errors only the RF section, never the mode radios), guarded
  `rate_index_from_code` against unhashable inputs, re-translated the RF labels
  on language change, softened the `docs/FEATURES.md` §2 RF row to mark the
  shared byte confirmed-by-read while the bit positions stay a ⚠️ hypothesis
  pending a device write-diff, and added `tests/test_i18n.py` (locale key parity)
  + RF error-render/unhashable-input tests. Suite 132→139, all pass.

## Design Notes

The RF/polling-rate story is intentionally a state/exposure story: it should make the shared `0x08D8` behavior explicit and align the app with the validated polling-rate slot mapping while leaving the performance-mode write flow intact. The work should not expand the performance tab beyond status/state visibility for this story.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass.

## Suggested Review Order

**Shared-byte write semantics (design intent)**

- Entry point: masked write + readback verify on the shared 0x08D8 byte, with RF errors isolated from the mode read.
  [`performance.py:108`](../../src/rapoo_vt7/performance.py#L108)

- Bit masks that keep the two fields on one byte from clobbering each other.
  [`protocol.py:123`](../../src/rapoo_vt7/protocol.py#L123)

- Both fields registered at the same EEPROM address with the shared-byte contract documented.
  [`settings.py:91`](../../src/rapoo_vt7/settings.py#L91)

- User toggles submit the masked write (wake=True) and surface readback errors.
  [`main.py:287`](../../src/rapoo_vt7/main.py#L287)

**Rate-code → slot mapping**

- Code map + unhashable-safe lookup with SLOT_DEFAULT fallback; new `read_perf_state` keeps mode/RF errors independent.
  [`performance.py:136`](../../src/rapoo_vt7/performance.py#L136)

- Active slot derives from rpt_usb only (rpt_24g ignored).
  [`main.py:24`](../../src/rapoo_vt7/main.py#L24)

- Perf refresh now bundles mode + RF state without coupling their failures.
  [`main.py:339`](../../src/rapoo_vt7/main.py#L339)

**UI exposure**

- RF section: status label + masked-write toggles in the Desempenho tab.
  [`gui.py:275`](../../src/rapoo_vt7/gui.py#L275)

- Render path: Hz line, RF/low status, checkbox sync and per-section error state.
  [`gui.py:318`](../../src/rapoo_vt7/gui.py#L318)

- Language switch re-translates the new RF labels.
  [`gui.py:586`](../../src/rapoo_vt7/gui.py#L586)

- New rf_* strings across pt_BR/en/es.
  [`i18n.py:42`](../../src/rapoo_vt7/i18n.py#L42)

**Diagnostics & docs**

- probe decodes the shared 0x08D8 byte into both switch bits.
  [`probe.py:222`](../../tools/probe.py#L222)

- Feature table records the shared byte (confirmed read) and bit layout (hypothesis, pending device write-diff).
  [`FEATURES.md:56`](../../docs/FEATURES.md#L56)

**Tests (supporting, last)**

- RF state read + write isolation (mode kept when RF read fails).
  [`test_performance.py:144`](../../tests/test_performance.py#L144)

- Masked writes preserve the sibling bit; verify mismatch rejected.
  [`test_performance.py:260`](../../tests/test_performance.py#L260)

- rpt_usb slot detection, default fallback, rpt_24g ignored.
  [`test_performance.py:212`](../../tests/test_performance.py#L212)

- Locale key parity incl. rf_* keys and format placeholders.
  [`test_i18n.py:7`](../../tests/test_i18n.py#L7)

- probe shared-byte hypothesis decoding.
  [`test_probe.py:213`](../../tests/test_probe.py#L213)

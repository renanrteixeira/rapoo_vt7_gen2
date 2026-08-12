---
title: '3-1 Performance modes'
type: 'feature'
created: '2026-08-11'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/src/rapoo_vt7/performance.py'
  - '{project-root}/src/rapoo_vt7/gui.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/tests/test_performance.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app needs a safe, user-facing performance mode control when the active polling rate changes, but the feature must write the currently active slot only and verify the device state before claiming success.

**Approach:** Implement the performance mode tab as a radio-based selector that writes a one-byte mode id to `0x08DC + slot` for the active polling rate slot, verifies the write by re-reading the same slot, and displays the active mode based on the live rate reported by the mouse.

## Boundaries & Constraints

**Always:**
- The active performance slot is derived from report 7's `rpt_usb` byte and mapped to slot 0..6 via `perf.rate_index_from_code()`. If `rpt_usb` is unavailable, fall back to the default slot `perf.SLOT_DEFAULT`.
- Mode ids are integers `0..5` and map to `perf.PERF_MODES` labels. The UI should expose exactly these six modes.
- Writes are one-byte writes to `0x08DC + slot` and must be verified immediately by re-reading the same slot via `perf.read_mode()`.
- The performance tab radio buttons must only be sensitive if `perf.selectable_modes(slot)` allows the mode for the current active slot.
- If the device is asleep, timed out, or the active slot cannot be determined, do not change the mode and surface a clear error status in the performance tab.
- The feature is limited to performance mode selection. It must not include DPI list editing, polling-rate selection, button remap, or any other EEPROM field changes.

**Ask First:**
- If resolving the active rate slot requires adding a new polling-rate selector or changing the already-implemented rate detection semantics beyond report 7 / `perf.SLOT_DEFAULT` behavior.

**Never:**
- Do not write any EEPROM field outside the active performance mode slot (`0x08DC + slot`).
- Do not implement a separate polling-rate UI in this story.
- Do not change DPI behavior, button remap, or system-operation flows.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | active device, report 7 provides `rpt_usb` | write mode id to `0x08DC + slot`, verify by re-read, UI shows selected mode | n/a |
| Fallback slot | report 7 missing or `rpt_usb` unavailable | use `perf.SLOT_DEFAULT`; allow mode selection and verify the write | UI should indicate fallback if helpful |
| Verify mismatch | write succeeds but re-read returns a different id | preserve previous mode, do not update UI, surface a verification error | raise `ValueError` in `perf.set_mode`, show error text |
| Disallowed mode | user attempts a mode not in `perf.selectable_modes(slot)` | UI disables that mode | no write attempted |
| Device asleep / timeout | write or read times out | no mode change | show error status, do not retry automatically |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/performance.py` -- active slot mapping (`rate_index_from_code`), mode table read/write, verification behavior, and selectable mode rules.
- `src/rapoo_vt7/gui.py` -- performance tab radio construction, mode toggles, status rendering, and error display.
- `src/rapoo_vt7/main.py` -- `_current_perf_slot()`, `_on_set_perf()`, `_refresh_perf()`, and mode write callback wiring through the monitor.
- `src/rapoo_vt7/protocol.py` -- `SENSOR_MODE`, `R7_RPT_USB`, `R7_RPT_24G`, and bank-0 offset conventions.
- `docs/FEATURES.md` §2 B -- performance mode semantics, confirmed slot/rate mapping, and `0x08DC` write contract.
- `tests/test_performance.py` -- existing unit coverage for read/write mode behavior, rate index mapping, and verify mismatch.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/performance.py` -- ensure `perf.set_mode()` writes the selected mode id to `0x08DC + slot`, re-reads the same slot, and raises on mismatch. Confirm `perf.read_mode()` and `perf.rate_index_from_code()` match the expected `rpt_usb` mapping.
- [x] `src/rapoo_vt7/gui.py` -- ensure the performance radio buttons reflect `perf.PERF_MODES`, call `_on_set_perf(mode)`, and render active mode / error state correctly in the tab.
- [x] `src/rapoo_vt7/main.py` -- use `_current_perf_slot()` based on `rpt_usb` with `perf.SLOT_DEFAULT` fallback, preserve existing report-7 based slot detection, and refresh the active mode after writes.
- [x] `tests/test_performance.py` -- verify the mode table read/write behavior, slot mapping, selectable-mode filtering, and verify-mismatch error path.

**Acceptance Criteria:**
- Given an awake device and `rpt_usb` indicating the active rate code, when the user selects a mode, then the app writes the mode id to `0x08DC + slot` and the subsequent read returns the same id.
- Given the device has no `rpt_usb` value available, when the performance tab refreshes, then it uses `perf.SLOT_DEFAULT` and remains functional without crashing.
- Given the device returns a different mode id after write, when `perf.set_mode()` is called, then it raises `ValueError` and the app surfaces a verification error instead of accepting the new mode.
- Given a mode that is not allowed for the current slot, when the user views the performance tab, then that mode is disabled in the radio group.
- Given the test suite, when `python3 -m unittest discover -s tests` runs, then all tests pass.

## Spec Change Log


## Design Notes

The performance mode feature is intentionally bounded to the active polling-rate slot. The mode table is slot-based: the active mode is stored at `0x08DC + slot` and the slot is derived from `rpt_usb` rather than from a separate UI selector. This keeps the feature aligned with the existing A Hub semantics and prevents the user from making a mode write that does not match the currently active rate.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass.

## Suggested Review Order

**Active slot and write verification**

- Verify the mode write callback and its slot resolution logic.
  [`main.py:276`](../../src/rapoo_vt7/main.py#L276)

- Confirm refresh logic reads the active slot and updates the UI.
  [`main.py:300`](../../src/rapoo_vt7/main.py#L300)

- Inspect the device write/verify contract for the selected slot.
  [`performance.py:98`](../../src/rapoo_vt7/performance.py#L98)

**UI binding and status rendering**

- Review the performance radio button construction and callback wiring.
  [`gui.py:245`](../../src/rapoo_vt7/gui.py#L245)

- Review performance status rendering and mode sensitivity rules.
  [`gui.py:285`](../../src/rapoo_vt7/gui.py#L285)

**Tests**

- Confirm write-and-verify behavior for the active slot.
  [`test_performance.py:102`](../../tests/test_performance.py#L102)

- Confirm mismatch verification raises and surfaces errors.
  [`test_performance.py:124`](../../tests/test_performance.py#L124)

- Confirm selectable modes are disabled correctly by slot.
  [`test_performance.py:133`](../../tests/test_performance.py#L133)

**Manual checks:**
- Open the performance tab, select each enabled mode, and confirm the device returns the same mode id on the active slot re-read.
- If report 7 is unavailable, confirm the tab still renders and uses the fallback slot.

---
title: '2-1 DPI systray menu'
type: 'feature'
created: '2026-08-11'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/src/rapoo_vt7/dpi.py'
  - '{project-root}/src/rapoo_vt7/gui.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/src/rapoo_vt7/settings.py'
  - '{project-root}/tests/test_dpi.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app lacks a tray-based DPI status and control surface, so users cannot see the current gear/DPI or switch gears from the systray window.

**Approach:** Add DPI status and control widgets to the existing app UI, showing the current gear, the current DPI value, the active button-cycle count, and allowing gear switches and in-place DPI edits through the existing `dpi` device APIs.

## Boundaries & Constraints

**Always:**
- The DPI data comes from passive report 7 and EEPROM reads of the DPI tables, not from a hardcoded list.
- Gear switching uses `dpi.set_gear(dev, gear)` and DPI edits use `dpi.set_value(dev, info, gear, x)`.
- The UI is limited to DPI status and editing; it must not introduce unrelated performance mode, button remap, or system operation controls.
- All table writes are verified by `write_eeprom_verify` and reflected back to the UI.

**Never:**
- Do not write any non-DPI EEPROM fields.
- Do not implement a separate polling-rate UI or performance mode controls in this story.

## Code Map

- `src/rapoo_vt7/dpi.py` — read/write DPI device operations, active gear calculation, and compact list management.
- `src/rapoo_vt7/gui.py` — DPI tab UI construction, status rendering, gear controls, and error handling.
- `src/rapoo_vt7/main.py` — monitor callbacks, refresh logic, and DPI device task submission.
- `src/rapoo_vt7/settings.py` — field registry for DPI EEPROM addresses and value codecs.
- `docs/FEATURES.md` — DPI field definitions and valid ranges.
- `tests/test_dpi.py` — unit coverage for DPI read/write flows and gear logic.

## Tasks & Acceptance

**Execution:**
- [x] Implement tray-window DPI status and current gear display.
- [x] Add gear-switch controls that call `dpi.set_gear` and refresh the UI on completion.
- [x] Add DPI value editing for the current gear, writing with `dpi.set_value` and verifying the new value.
- [x] Ensure all DPI changes are verified and error conditions surface in the DPI tab.
- [x] Cover the DPI behavior with unit tests in `tests/test_dpi.py`.

**Acceptance Criteria:**
- Given a connected device, the DPI tab shows the current gear and DPI values, including the active button cycle count.
- Given a gear switch, the UI calls `dpi.set_gear`, the device is updated, and the new gear is reflected after refresh.
- Given a DPI edit, the UI writes the value for the selected gear, verifies it, and preserves the current DPI if the edited gear is current.
- Given the test suite, `python3 -m unittest discover -s tests` passes.

## Spec Change Log

- 2026-08-11 — created spec file after confirming the feature is implemented and the epic is marked done.
- 2026-08-20 (retro reconciliation, epic-2 retro F4 — doc-only): records three
  drifts between this frozen text and the shipped feature, none a defect:
  1. **AC3 sentence was inverted.** As written ("preserves the current DPI if
     the edited gear is current") it reads backwards. The as-built semantics
     (`dpi.set_value`): editing the CURRENT gear applies in place (its slot
     holds the DPI in use, so the change takes effect immediately); editing
     any OTHER gear only stores the value (`dpi_stored` vs `dpi_edited`
     notifications). No reorder, no re-select either way.
  2. **Surface moved from tray to window.** The title says "systray menu";
     as built, DPI status/control lives in the window's "DPI" tab (the tray
     DPI submenu was removed when the tab shipped).
  3. **Scope grew beyond status + switch + edit.** The story also delivered
     add/delete from the button cycle with A Hub `setDeviceGears` semantics
     (`set_gears`/`add_gear`/`delete_gear`, sorted-on-add, current gear
     follows its value across reorders) — validated on device 2026-08-12.

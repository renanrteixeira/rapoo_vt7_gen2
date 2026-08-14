---
title: '5-1 Factory reset with confirmation'
type: 'feature'
created: '2026-08-13'
status: 'done'
baseline_commit: '570654bf3b70eda8c359d38950b43767b100b747'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/src/rapoo_vt7/device.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/gui.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The mouse has a factory-reset command (0xAD), but the app offers
no way to invoke it. This is a destructive operation — it must be guarded by
an explicit confirmation dialog to prevent accidental data loss.

**Approach:** Add a "System" menu or tab to the window with a factory-reset
button. When clicked, show a confirmation dialog stating the operation wipes
all settings (localized). On user confirm, send the 0xAD command via
`submit(..., wake=True)`, then verify the device has returned to factory
state by re-reading the settings (e.g. DPI gear should reset to default, RF
should reset to default). Display non-blocking feedback (success/error).

## Boundaries & Constraints

**Always:**
- The factory-reset confirmation dialog must be explicit and blocking — never
  a silent/background operation.
- Factory reset is user-initiated and uses `submit(..., wake=True)` so it is
  attempted even if the mouse just fell asleep.
- Post-reset verification reads key EEPROM fields to confirm the device has
  returned to factory defaults (e.g. `MOUSE_DPI_CUR`, `SENSOR_MODE`,
  `RF_STRENGTHEN_SWITCH`); a failure to verify surfaces an error.
- All user strings live in `i18n.LANGS` (pt_BR/en/es); the reset button,
  confirmation dialog, and result messages must re-translate on language
  change.
- The operation must never touch or corrupt the baseline file
  (`~/.cache/rapoo-vt7/eeprom_baseline.json`).
- `python3 -m unittest discover -s tests` must pass.

**Ask First:**
- If the live device's factory-reset response (0xAD reply) is not a simple ACK
  (data[1]==0x01), HALT and ask how to interpret the response.
- If post-reset verification fails to detect a change (device reports the same
  settings as before), HALT and ask whether to accept the reset anyway or
  reject it.

**Never:**
- Do not write EEPROM before calling 0xAD — the command itself resets all
  settings, so a pre-reset write is lost and redundant.
- Do not expose factory reset outside the window GUI — probe.py is a
  diagnostics tool, never a user surface.
- Do not gate the feature behind a "baseline exists" check — factory reset is
  a destructive operation, not a write, and does not use `write_eeprom`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Reset button visible | app started, system menu/tab shown | button labeled "Factory reset" (localized) | N/A |
| User clicks reset | confirmation dialog shown | dialog states "wipes all settings" (localized) with Cancel/OK buttons | N/A |
| User cancels | dialog open | dialog closes, no reset is sent | N/A |
| User confirms reset | dialog open, device available | 0xAD command sent, device reboots; post-reset DPI/RF fields re-read to confirm default state; success message shown non-blocking | verification failure → error message, previous values retained |
| Mouse asleep | user clicks reset | dialog shown, reset attempted with wake=True | device timeout → "asleep" message, no change to device state |
| Language change | reset button/dialog visible | reset button label + dialog text re-translated | N/A |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/protocol.py:27` -- `RETURN_FACTORY_SETTINGS = 0xAD` already defined.
- `src/rapoo_vt7/device.py:200-216` -- `query()` method (command send + response read); `get_battery()`, `get_work_mode()` are simple query examples.
- `src/rapoo_vt7/main.py:287-304` -- `_on_set_rf()` + submit(wake=True) template; `:339-360` -- `_refresh_perf()` (section read + error handling).
- `src/rapoo_vt7/gui.py:310-383` -- window tabs structure; a new "Sistema" / "System" tab or a menu button in the battery tab can host the reset button.
- `src/rapoo_vt7/i18n.py` -- language strings; new keys needed: reset button label, confirmation dialog title/text, success/error messages.
- `tests/test_device.py` -- query patterns already tested; new test for factory reset response ACK.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/system.py` (new) -- factory-reset primitive: send 0xAD command, verify response ACK, read post-reset DPI/RF/mode fields to confirm defaults.
- [x] `src/rapoo_vt7/main.py` -- add `_on_factory_reset()` handler (confirmation dialog, submit wake=True, on_done/on_error callbacks).
- [x] `src/rapoo_vt7/gui.py` -- add "Sistema" / "System" tab (or button in existing tab) with factory-reset button; implement the confirmation dialog (Gtk.MessageDialog with CANCEL/OK); wire language re-translation.
- [x] `src/rapoo_vt7/i18n.py` -- add reset strings in pt_BR/en/es: button label, dialog title, dialog message, success message, error message.
- [x] `tests/test_system.py` (new) -- FakeDev tests: factory reset ACK, post-reset field verification, failed verification rejected, asleep behavior.
- [x] `docs/FEATURES.md` -- note system operations phase (CAP-8) and factory reset availability.

**Acceptance Criteria:**
- Given the app window, a factory-reset button or menu item is visible (localized).
- Given a click on the reset button, a confirmation dialog appears stating "This will wipe all settings" (localized) with Cancel and OK buttons.
- Given the user clicks OK, the 0xAD command is sent and the device reboots; post-reset EEPROM fields (DPI, RF, mode) are re-read and compared to factory defaults.
- Given a successful reset, a non-blocking success message is shown (e.g. "Factory reset complete").
- Given a verification failure (post-reset fields do not match factory defaults), an error is shown and no state is changed.
- Given the mouse is asleep, the reset is attempted with wake=True; if it times out, an "asleep" message is shown.
- Given a language change, the reset button, dialog, and messages are re-translated.

## Spec Change Log

- 2026-08-13: Implemented. `system.py` factory_reset (0xAD ACK + post-reset verify of
  MOUSE_DPI_CUR=0, RF byte 0x08D8=0x00, SENSOR_MODE [0,0,1,1,3,3,3]); "Sistema" tab with
  blocking Gtk.MessageDialog (Cancel default); main.py handler with submit(wake=True);
  i18n keys pt_BR/en/es; 300 tests OK (23 in tests/test_system.py). Device not yet
  validated live (see risks).
- 2026-08-13 (review loop 1): applied review patches — (1) post-reset verification
  exhaustion now raises `FactoryResetVerifyError` instead of leaking a raw
  `CommandTimeout` ("no response / mouse asleep") after the reset was ACKed; (2) busy
  guard: the reset button disables while a reset is in flight (`_system_busy`) and
  re-enables in `set_system_message`, so two resets cannot queue back to back; (3) headless
  dialog/tab tests added (FakeDialog/FakeButton stubs). 303 tests OK. Deferred items
  recorded in deferred-work.md (narrow verification, near-default false failure, stale
  tabs on verify failure, `_lang` monitor-thread race, unguarded Notify, whole-byte RF
  compare).

## Suggested Review Order

**Command + verification (core design)**

- 0xAD is command-only, never a write; verifies three device-validated factory markers
  [system.py:133](../../src/rapoo_vt7/system.py#L133)

- Post-reset reads survive the reboot window, and exhaustion is a verify error, not a raw timeout
  [system.py:111](../../src/rapoo_vt7/system.py#L111)

- Factory-state predicate the verification compares against
  [system.py:103](../../src/rapoo_vt7/system.py#L103)

**Confirmation dialog (destructive gate)**

- Blocking modal dialog, Cancel default, re-reads localized labels at show time
  [gui.py:688](../../src/rapoo_vt7/gui.py#L688)

- Busy guard: one reset in flight, button disabled until `set_system_message`
  [gui.py:715](../../src/rapoo_vt7/gui.py#L715)

- System tab construction: localized reset button + hint
  [gui.py:666](../../src/rapoo_vt7/gui.py#L666)

**App wiring (submit + refresh)**

- Confirmation handler: submit with wake=True, so it runs even while asleep
  [main.py:485](../../src/rapoo_vt7/main.py#L485)

- Success: notify + refresh every config tab (device is now at defaults)
  [main.py:500](../../src/rapoo_vt7/main.py#L500)

- Failure: maps typed errors to localized strings
  [main.py:515](../../src/rapoo_vt7/main.py#L515)

**Localization**

- 10 new keys in all three locales (pt_BR/en/es)
  [i18n.py:163](../../src/rapoo_vt7/i18n.py#L163)

**Peripherals (tests + docs)**

- Core flow: ACK, verify, no-change/non-default rejection, reboot retry
  [test_system.py:239](../../tests/test_system.py#L239)

- App-level submit(wake=True), localized errors, tab refresh on success
  [test_system.py:300](../../tests/test_system.py#L300)

- Headless dialog/tab tests (FakeDialog/FakeButton stubs, busy guard)
  [test_system.py:430](../../tests/test_system.py#L430)

- Phase 5 marked done, §E factory-reset row
  [FEATURES.md](../../docs/FEATURES.md)


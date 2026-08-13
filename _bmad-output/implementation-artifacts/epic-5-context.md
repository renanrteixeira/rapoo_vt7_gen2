# Epic 5 Context: Phase 5 — System operations (CAP-8)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the user three system-level operations in the app's window: factory reset
(`0xAD` `return_factory_settings`) that restores the mouse to factory
configuration — destructive, so it must require an explicit confirmation dialog;
device name read/rename (`0x09EC`, 16-byte string, reads "CFG1" on the real
device); and receiver pairing via a guided 3-step physical flow. Each operation
must be performed and verified on the real device without corrupting on-board
state. This completes CAP-8, the last pending capability.

## Stories

- Story 9: System operations

## Requirements & Constraints

- Factory reset wipes everything: it must be guarded by a confirmation dialog
  (spec checkpoint for this story) and triggered only by explicit user intent —
  never from a passive path.
- Receiver pairing is a 3-step physical flow — connect wired, position the
  mouse, press L+M+R — driven by the app's flow. The underlying pairing commands
  are **not mapped yet** (FEATURES.md §E, ⚠️): they must be reverse-mapped from
  the A Hub `deviceMatcher` logic and validated on the device before the flow
  writes anything.
- Device name is a 16-byte string field (`0x09EC`); encode/pad user input to the
  fixed 16-byte field and validate length before writing.
- Golden rule applies to every EEPROM write, including the name (baseline exists
  → write ≤ 24 B bank-0 → verify by immediate re-read). Factory reset is a
  command, not an EEPROM write, but still needs on-device verification.
- GUI-only user surface: all three operations reachable from the window/menu;
  `probe.py` is a diagnostics harness, never a user surface. All user strings
  via `i18n.LANGS` (pt_BR/en/es) with re-translation on language change.
- Errors surface non-blocking (status text / dialogs); user-initiated operations
  use the `wake=True` submit path so they are attempted even if the mouse just
  fell asleep; a device timeout flips the monitor back to "asleep" with a
  localized message.
- Never write before the baseline exists.

## Technical Decisions

- Follow the per-feature module pattern established in this project: a `system.py`
  (or equivalent) module with read/write primitives + immediate readback verify;
  `protocol.py` owns wire constants (0xAD, 0x09EC already declared);
  `settings.py` already registers `config_name` (16 B string); the worker owns
  the fd, the command queue, and sole golden-rule execution — GUI never touches
  hidraw.
- Factory reset uses the existing `RETURN_FACTORY_SETTINGS` (0xAD) command path;
  device name write goes through `write_eeprom` (0xA5) + verify. Both are
  user-initiated and enqueued via the monitor's submit (wake semantics).
- Pairing commands are unknown until reverse-mapped from the A Hub
  `deviceMatcher` flow; follow the "Ask First" gating precedent from button
  remap (gated functions are not offered until device-validated).
- CAP-8 lives in `device.py`/`settings.py`, `session.py`, and `gui.py` dialogs,
  governed by AD-6/AD-7/AD-8 (pure registry + golden rule, GUI-only + i18n +
  absolute icon path, typed errors + sleep discipline).
- Config persistence (atomic `config.json` read-modify-write, AD-10) is
  unaffected unless pairing state is stored — if so, the single-owner atomic
  replace convention applies.

## UX & Interaction Patterns

- Destructive factory reset: confirmation dialog stating the operation wipes all
  settings; never a single-click action without confirmation.
- Device name: read → show → edit → write → re-read, result surfaced non-blocking.
- Receiver pairing: a guided 3-step flow (connect wired, position, press L+M+R)
  with per-step instructions and status, all localized.

## Cross-Story Dependencies

- Depends on the Phase 0 EEPROM write+verify infrastructure (Story 1) and the
  settings registry (Story 2); reuses the `submit(..., wake=True)` plumbing and
  the window-tabs pattern established in Phases 2–4 (`buttons.py` is the closest
  sibling for gated/Ask-First features).
- No other story depends on this epic; it is the last pending capability (CAP-8).
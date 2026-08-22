# Epic 4 Context: Phase 4 — Button remap (CAP-7)

<!-- Compiled from planning artifacts + retrospective evidence. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Let the user remap the mouse's 13 physical buttons from the app, replacing the A Hub as the only remap tool. Each button's function lives in a bank-0 EEPROM field (`0x0600`–`0x0638`) storing a **4-byte method** `<type><p1><p2><p3>` — confirmed on device byte-for-byte against the A Hub `keyPosition` table (12/12 readable) plus reversible write-tests on `0x0634`. Story 4-1 (done) shipped the "Botões" tab with a per-button picker dialog; a second wave (2026-08-19) added keyboard keys, combos and macros to the picker.

## Stories

- Story 8 (4-1): Button remap — done (wave 1: 2026-08-12 base; wave 2: 2026-08-19 keyboard/combo/macro)

## Requirements & Constraints

- Method type bytes: `0x03` mouse button, `0x08` DPI, `0x09` fire/sniper, `0x0a` config/DIY, `0x0b` scroll (direction contextual per button), `0x0c` h-scroll, `0x07` disable, `0x04` media, `0x02` combo, `0x05` macro; keyboard keys are a single HID usage byte.
- Write formats (device-validated): keyboard `00 00 <HID> 00`; combo `02 <key1> <modifier> <key2>` (single key pads key2=00; modifier = plain bitmask Ctrl L=01 Shift L=02 Alt L=04 Win L=08 Ctrl R=10 Shift R=20 Alt R=40 Win R=80); macro `05 00 <slot> 00` (12 slots).
- Every remap write targets bank 0, is ≤24 bytes, and is confirmed by immediate re-read (`write_eeprom_verify`); mismatch rejects the change.
- **≥1-left-click rule** (A Hub `atLeastOneLeftButton`/`logicCheckLeftKey`): the last left-click-capable button (left + BLE variant `03 00 01 01`) can never be set away from left-click. Enforced twice: pre-submit in `main.py` (window state, skipped when field errors exist) and authoritatively in-module (`_other_is_left` → `NoLeftClickError`, localized to `button_no_left`).
- `_DECODE_ONLY` functions (BLE left variant) render as labelled non-writable rows — decoded read-back labels only, never offered/written.
- Unknown method bytes show as raw hex, never a fake label; picker stays enabled.
- User-initiated remaps use `submit(..., wake=True)`; on error/asleep last-known values are retained, never nulled.
- GUI-only surface; all strings in `i18n.LANGS` (pt_BR/en/es), re-translated on language change (`_rebuild_buttons`).

## Technical Decisions

- `buttons.py` owns the vocabularies and operations: `METHODS` (30 picker-offered confirmed methods), `KEYBOARD` (104 HID usages) + `KEYBOARD_LABEL`, `COMBO` (10 A Hub presets), `MODIFIER` bitmask, `MACRO_SLOTS = 12`, `_DECODE_ONLY`; `keyboard_method`/`combo_method`/`macro_method` build raw methods, `function_method` resolves every category for the write path; `method_name(method, button=None)` decodes with contextual scroll direction; `read_button`/`read_section` isolate per-field errors; `set_function` validates + enforces the rule + writes with verify.
- Button fields registered `size=4` in `settings.py` (was 1B before device confirmation); cross-registry drift guard tests pin this.
- The picker is a modal `Gtk.Dialog`+`Gtk.Notebook` per button (tabs Funções | Teclado searchable | Combos | Macros) — diverged from the spec's original combo-per-button design; the legacy ComboBoxText path survives only as a test fixture.
- Function table source: A Hub lazy chunk `keyPosition-D9HhW_CA.js` (+ `changeKey-uvZcd8Zo.js` for kb/combo/macro formats) — chunk-download route replaced an on-device configure-diff.
- Known open items (epic-4 retro): spec/comment reconciliation of the 2026-08-19 wave (F1), legacy pre-dialog path decision (F2), wave test debt — set_function with kb/combo/macro ids, picker-dialog coverage, probe decode integration, i18n placeholder parity (F3), `_other_is_left` docstring vs fail-closed behavior (F4).

## UX & Interaction Patterns

- "Botões" tab: one row per physical button showing the current function; "Choose function…" opens the picker dialog; decode-only currents render disabled with a label; status line shows dynamic count (`{n}`) and localized errors (`button_no_left`, `button_unknown_fn`, `buttons_more_errors`).

## Cross-Story Dependencies

- Builds on Phase 0 infrastructure: `settings.py` registry (button fields), `write_eeprom_verify`, `submit(wake=...)`, section-read error isolation pattern shared with parameters/performance.
- Probe (`tools/probe.py`) decodes buttons via `method_name(method, name)` — keep `button_fields()` consistent with the registry.
- No dependency on DPI/performance/system epics; the System tab's factory reset restores button defaults (debounce 8/16 etc. per D3 baseline).

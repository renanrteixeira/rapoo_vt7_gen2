---
title: '4-1 Button remap'
type: 'feature'
created: '2026-08-12'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context:
  - '{project-root}/docs/FEATURES.md'
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
  - '{project-root}/src/rapoo_vt7/protocol.py'
  - '{project-root}/src/rapoo_vt7/settings.py'
  - '{project-root}/src/rapoo_vt7/main.py'
  - '{project-root}/src/rapoo_vt7/gui.py'
  - '{project-root}/tools/probe.py'
  - '{project-root}/docs/rapoo_hub_app.js'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The mouse has 13 physical buttons whose function each lives in a
bank-0 EEPROM field (`0x0600`–`0x0638`), but the app offers no way to remap
them — the official A Hub web app is the only remap tool.

**Approach:** Each button field stores a **4-byte method** (`<type><p1><p2><p3>`)
— confirmed on the real device (read back byte-for-byte against the A Hub
`keyPosition` table for all 12 readable buttons, and a reversible write test
on 0x0634). The full function→method table was extracted from the A Hub
chunk files (`keyPosition-D9HhW_CA.js`). Register the button fields with
`size=4`, and expose a per-key remap UI in a new window tab ("Botões")
following the established read → show → write → re-read pattern. Enforce the
A Hub business rule that at least one left-click button stays functional.

## Boundaries & Constraints

**Always:**
- Every remap write targets bank 0, is ≤24 bytes, and is confirmed by an
  immediate re-read (`write_eeprom_verify`); a readback mismatch rejects the
  change and surfaces an error — the new code is never accepted.
- Golden rule: no write before the baseline exists
  (`~/.cache/rapoo-vt7/eeprom_baseline.json`); every on-device code-extraction
  diff restores the original byte when done.
- The function code table is the **`method` of 4 bytes** (`<type><p1><p2><p3>`),
  e.g. left=`03 00 01 00`, DPI+=`08 00 05 00`, scroll fwd=`0b ff 00 ff`,
  disable=`07 00 00 00`, media=`04 00 00 b6`…, keyboard key=single HID usage
  byte, combo=`02 <modmask> <k1> <k2>`, macro=`05 00 0N 00`. **CONFIRMED ON
  DEVICE (2026-08-12)**: all 12 readable buttons read back the exact bundle
  `method`; write-test on 0x0634 (bottom) wrote `07 00 00 00`, re-read
  verified, restored `0a 00 00 00` (MATCH). Keyboard/combos/macros write
  formats derive from the bundle (single-byte HID usage, `02` combo prefix)
  and are validated on the device before the UI offers them.
- GUI-only user surface. All user strings live in `i18n.LANGS`
  (pt_BR/en/es) and new labels must re-translate on language change
  (`_on_lang_changed`).
- User-initiated remaps are attempted even when the mouse is asleep
  (`submit(..., wake=True)`); background reads while asleep are rejected, not
  queued. On error/asleep the last known values are retained, never nulled.
- **≥ 1 left button rule** (A Hub `atLeastOneLeftButton`): the UI never allows
  the last left-click-capable button (left + BLE, per A Hub `logicCheckLeftKey`)
  to be set to anything that removes left-click; the A Hub toasts
  "at least one left click key must be assigned".
- `python3 -m unittest discover -s tests` must pass.

**Ask First:**
- If a keyboard/combo/macro write-test on the device contradicts the bundle
  format (e.g. a keyboard key does not write as its single HID usage byte),
  HALT and gate that category (read-only) until resolved.
- If the physical left button cannot be verified as remappable (the A Hub may
  lock it), HALT and ask how to expose it.

**Never:**
- Do not change performance-mode, RF, DPI, or §C parameter semantics (stories
  3-1/3-2/3-3).
- Do not ship a function code that the on-device diff did not confirm.
- Do not write any byte without a confirmed field size plus readback verify.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Button state read | device available | read each 4-byte button field, decode its `method` to a function, show in the tab | read failure → section error text, last values retained |
| Remap write | user picks a function for a key | 4-byte method write, confirmed by re-read; new function shown | readback mismatch → reject, error surfaced, change not accepted |
| Last left-click key | user tries to set the last left button away from left-click | write refused, error/toast "keep ≥ 1 left button" | non-blocking error, previous value kept |
| Unknown method in a field | field decodes to no known function | shown as raw hex, not a fake label | N/A |
| Mouse asleep | background read / user remap | read rejected, last values kept; remap attempted with wake | device timeout → monitor back to "asleep", localized message |
| Language switch | user changes language | new button labels re-translated | N/A |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/protocol.py:101-114` -- button offsets already defined
  (`MOUSE_LEFT` 0x0000 … `MOUSE_BLE` 0x0038 → absolute 0x0600…0x0638).
- `src/rapoo_vt7/settings.py:108-121` -- 13 button `Field`s already registered
  (default `size=1`); this story changes them to **`size=4`** (the confirmed
  `method` field).
- `src/rapoo_vt7/parameters.py` -- the pattern a new `buttons.py` mirrors:
  section read with isolated per-field errors, write+verify.
- `src/rapoo_vt7/main.py:287-304` -- `_on_set_rf` toggle template (submit
  wake=True); `:339-360` -- `_refresh_perf`/`_maybe_refresh_perf`
  (refresh + empty-tab retry); new button handlers + section refresh follow
  these.
- `src/rapoo_vt7/gui.py:310-383` -- window tabs (Bateria | DPI | Desempenho |
  Parâmetros); a fifth "Botões" tab follows `_tab_params` (`:382-383`), and
  `_on_lang_changed` (`:970-973`) re-translates the tab labels.
- `tools/probe.py:145-154` -- `button_fields()` (from `settings.FIELDS`);
  `build_hypothesis` (`:203-269`) emits the 2B-button 1B-vs-2B hypothesis;
  replace with **method decode** (4B → function name / raw hex) after the
  field size change.
- `docs/FEATURES.md:96-119` -- §2.D button table: addresses ✅, current device
  reads recorded, codes ⚠️; update to confirmed `method` codes + 4B size.
- `/tmp/opencode/ahub-chunks/keyPosition-D9HhW_CA.js` -- the A Hub chunk with
  the full `method` table (161 functions: mouse, scroll, DPI, fire/sniper,
  config, disable, keyboard HID usages, media, combos, macros) — the
  authoritative code source for `buttons.py`.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/buttons.py` (new) -- button read/set primitives following
      `parameters.py`: per-button read, 4-byte method write+verify, section
      read bundling reads with isolated per-field errors; the confirmed
      method table (method bytes → function id) + category sets.
- [x] `src/rapoo_vt7/settings.py` -- button `Field`s to `size=4`.
- [x] `src/rapoo_vt7/main.py` -- remap handler (submit `wake=True`) + section
      refresh/error callbacks wired like `_on_set_rf`/`_refresh_perf`;
      enforce the ≥1-left-button rule before submitting.
- [x] `src/rapoo_vt7/gui.py` -- "Botões" tab: picker per button with the
      confirmed functions; render + error isolation + re-translation in
      `_on_lang_changed`; the last-left-button row refuses non-left functions.
- [x] `src/rapoo_vt7/i18n.py` -- button/function label strings in pt_BR/en/es.
- [x] `tools/probe.py` -- replace the 1B-vs-2B button hypothesis with the
      confirmed method decode (4B → function); keep `button_fields` consistent.
- [x] `tests/test_buttons.py` (new) -- FakeDev tests: read, method write+verify,
      readback mismatch rejected, isolated section error, asleep behavior,
      ≥1-left-button rule; extend `tests/test_i18n.py` parity.
- [x] `docs/FEATURES.md` -- update §2.D with confirmed 4B method codes and mark
      the Phase-4 roadmap item done.

**Acceptance Criteria:**
- Given a live device, each confirmed button shows its current function and
  picking a new one writes the 4-byte method → re-reads → updates the shown
  function without touching other fields.
- Given a readback mismatch, the change is rejected and an error is surfaced —
  never accepted.
- Given the last left-click-capable button, the UI refuses any non-left-click
  function (error + previous value kept).
- Given a language change, the new button labels re-translate.
- Given the test suite, `python3 -m unittest discover -s tests` passes.

## Spec Change Log

- 2026-08-12 (spec): created from stories.yaml story 8 (CAP-7, Phase 4).
  **Field size + code table CONFIRMED ON DEVICE before implementation** (the
  spec's Ask First gate fired): the button fields are **4-byte `method`**
  values, not 1B — every readable button (12/12) read back the exact bundle
  `method` byte-for-byte, and a reversible write-test on 0x0634 (bottom)
  wrote `07 00 00 00` → re-read verified → restored `0a 00 00 00` (MATCH).
  The full function→method table was extracted from the A Hub chunk
  `keyPosition-D9HhW_CA.js` (161 entries: mouse, scroll, DPI, fire/sniper,
  config, disable, keyboard HID usages, media, combos, macros) instead of the
  on-device A-Hub-configure diff — the chunk download route (Design Notes
  route 2) worked. Open question 4 of SPEC-rapoo-vt7 resolved. Keyboard/
  combo/macro write formats still derive from the bundle and are gated until
  device-validated.
- 2026-08-12 (implemented): `buttons.py` shipped (method table, per-button
  read, `set_function` write+verify with the ≥1-left rule), `settings.py`
  button fields → `size=4`, `probe.py` hypothesis → method decode, "Botões"
  tab (picker per button, error isolation, re-translation), `main.py` handler
  (`submit wake=True`, rule enforced before submit + inside the module),
  i18n labels pt_BR/en/es, `tests/test_buttons.py` + pure
  `gui.buttons_render_plan` headless tests (suite 224 → 253 OK). Live
  device verified 2026-08-12: `probe --status` decodes all 13 buttons; a
  reversible write-test on 0x0634 (bottom) wrote fire → re-read verified →
  restored; the ≥1-left rule allowed remapping left away only while BLE kept
  left-click and restored exactly.
- 2026-08-12 (step-03 audit): Matrix Test Audit passed — every row of the I/O
  & Edge-Case Matrix has a covering test that ran green: read/decode/raw-hex
  (`ReadButtonTest`), write+verify+mismatch-reject (`SetFunctionTest`),
  ≥1-left rule pre-submit + in-module (`MainButtonTest` +
  `test_keeps_last_left_click`), asleep read-reject + wake remap
  (`test_device_error_propagates` + `test_on_set_button_submits_write_with_wake`),
  language re-translation (`I18nLabelBindingTest` + `test_i18n` parity). Added
  `MainButtonTest` (FakeMonitor + FakeWindow, `_sync_idle` helper) and
  `I18nLabelBindingTest` → suite **253 → 260 OK**. `main.py` refusal message
  now uses `LANGS[window._lang]` directly instead of the GUI `_t()` helper
  (decoupling the handler for headless testing).
- 2026-08-12 (review fixes): triaged 3 reviewer reports (blind hunter, edge
  case, verification gap) — **no intent_gap/bad_spec findings; all were
  code-level**. Applied: `buttons.py` picker now offers **30 confirmed
  methods** (`METHODS`); combo/Keyboard/macro and BLE left-click moved to a
  `_DECODE_ONLY` map (read-back labels only, never offered/written — Ask First
  gate), scroll direction is **contextual per button** (`_SCROLL_BY_BUTTON`,
  `method_name(method, button=None)`), `set_function` validates the name and
  uses `_other_is_left` (read failure → False, no aborted remap),
  `NoLeftClickError` (localized to `button_no_left`); `gui.py` pickers were
  permanently disabled by the `_buttons_loading` flag — sensitivity now keys
  only on `_buttons_error`, and decode-only currents (BLE) render as a
  **labelled non-writable row**; `main.py` `_button_error` translates
  `NoLeftClickError`/"unknown function" → localized (`button_unknown_fn`),
  `_maybe_refresh_buttons` re-checks `has_buttons()` + per-field errors;
  `buttons_status` count is **dynamic** (`{n}`, i18n all 3 locales); probe
  decodes via `method_name(method, name)`. New tests (scroll context, decode-
  only i18n, recovery, per-field isolation, dynamic count, probe unknown-
  method) → suite **260 → 273 OK**. Defers recorded in deferred-work.md
  (story 3-2 `_on_set_rf` English "unknown RF field" string).

## Design Notes

Each button field stores a **4-byte `method`**: `<type><p1><p2><p3>`. The type
byte groups the function (0x03 mouse button, 0x08 DPI, 0x09 fire/sniper,
0x0a config/DIY, 0x0b scroll, 0x0c horizontal scroll, 0x07 disable, 0x04
media, 0x02 combo, 0x05 macro); keyboard keys are a single HID usage byte
(the field still holds 4 bytes). This was confirmed on-device (2026-08-12):
all 12 readable button fields matched the bundle `method` exactly, e.g.
left=`03 00 01 00`, middle=`03 00 04 00`, right=`03 00 02 00`, DPI+=`08 00 05 00`,
DPI-=`08 00 06 00`, fwd=`03 00 10 00`, back=`03 00 08 00`, scroll fwd/back=
`0b ff 00 ff`, scroll L/R=`ff ff ff ff` (off), bottom/DIY=`0a 00 00 00`,
BLE=`03 00 01 01`. The earlier "0xFF inconsistent" read at 0x0624/0x0628 is the
2nd byte `ff` of the scroll method, not an anomaly.

Extraction method: the minified main bundle holds only i18n names; the actual
`method` table lives in lazy chunks. **Route 2 (download chunks) worked** —
`keyPosition-D9HhW_CA.js` (and `changeKey`, `keyPositionUtils`) were fetched
from the A Hub host and contain the full function table with `method`,
`keyType`, `address` per bank. Route 1 (on-device A-Hub-configure diff) is no
longer needed.

The ≥1-left-button rule comes from the bundle: `logicCheckLeftKey` names the
left key and the toasts enforce `atLeastOneLeftButton` ("at least one left
click key must be assigned"). The UI mirrors this: the last
left-click-capable button (left, and BLE if the diff shows it maps to
left-click) cannot be reassigned away from left-click.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass.
- `python3 tools/probe.py --status` -- expected: button fields decoded with
  the confirmed code table + size.
- On-device (manual): run the app, remap a button in the "Botões" tab, confirm
  the new function works on click and re-reads back; confirm the last-left
  button refuses reassignment; confirm unconfirmed functions are absent.

## Suggested Review Order

**The confirmed method table — entry point (the story's anchor)**

- The 4-byte method table, confirmed on-device (0x03000100 left etc.), is the
  single source of truth for decode, picker, and the Ask First gate.
  [`buttons.py:52`](../../src/rapoo_vt7/buttons.py#L52)

- Functions gated out of the picker (combos, Keyboard, macros, BLE left) are
  decoded read-back labels only — never offered or written.
  [`buttons.py:96`](../../src/rapoo_vt7/buttons.py#L96)

- Scroll direction is contextual per button (both share `0bff00ff`).
  [`buttons.py:113`](../../src/rapoo_vt7/buttons.py#L113)

**Decode + the ≥1-left-click rule**

- `method_name`/`is_left_click`: method → id (with the BLE variant), and the
  left-click predicate the rule is built on.
  [`buttons.py:143`](../../src/rapoo_vt7/buttons.py#L143)

- `read_button` verifies the section read and isolates per-button errors.
  [`buttons.py:169`](../../src/rapoo_vt7/buttons.py#L169)

- `_other_is_left` treats a failed read as "not left" so a remap never aborts;
  `NoLeftClickError` is the rule's authoritative raise.
  [`buttons.py:205`](../../src/rapoo_vt7/buttons.py#L205)

- `set_function`: name validation, ≥1-left enforcement from live state.
  [`buttons.py:220`](../../src/rapoo_vt7/buttons.py#L220)

**Error localization + refresh policy**

- `_button_error` maps `NoLeftClickError`/"unknown function" to localized text.
  [`main.py:474`](../../src/rapoo_vt7/main.py#L474)

- `_maybe_refresh_buttons` re-checks `has_buttons()` and per-field errors so an
  asleep-at-startup window recovers the tab.
  [`main.py:493`](../../src/rapoo_vt7/main.py#L493)

**UI binding**

- `buttons_render_plan` (pure) computes current/raw/sensitive + status `{n}`.
  [`gui.py:129`](../../src/rapoo_vt7/gui.py#L129)

- Picker sensitivity keys only on `_buttons_error` (fixes the load-lock bug);
  decode-only currents render as a labelled non-writable row.
  [`gui.py:675`](../../src/rapoo_vt7/gui.py#L675)

- `_on_button_changed` ignores `__raw__` and decode-only re-selection.
  [`gui.py:705`](../../src/rapoo_vt7/gui.py#L705)

- `update_buttons`/`has_buttons`/`set_buttons_error`: the section's lifecycle.
  [`gui.py:722`](../../src/rapoo_vt7/gui.py#L722)

**i18n**

- All new strings (`button_no_left`, `button_unknown_fn`, BLE label, dynamic
  `{n}` status) exist in pt_BR/en/es.
  [`i18n.py:82`](../../src/rapoo_vt7/i18n.py#L82)

**Diagnostics**

- `build_hypothesis` decodes with `method_name(method, name)` so probe output
  shows the contextual scroll direction.
  [`probe.py:211`](../../tools/probe.py#L211)

**Tests (supporting, last)**

- `ReadButtonTest`/`SetFunctionTest`/`MainButtonTest`: read, write+verify,
  mismatch-reject, ≥1-left, asleep wake, refresh recovery.
  [`test_buttons.py:220`](../../tests/test_buttons.py#L220)

- `ButtonsRenderPlanTest`: render-plan decisions + scroll direction + count.
  [`test_gui_units.py:203`](../../tests/test_gui_units.py#L203)

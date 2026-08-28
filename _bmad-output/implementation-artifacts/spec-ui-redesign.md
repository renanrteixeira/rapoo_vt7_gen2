---
title: 'UI visual redesign: light/dark theme + modern card presentation'
type: 'feature'
created: '2026-08-27'
status: 'done'
baseline_commit: '4938cd3'
review_loop_iteration: 0
context: ["{project-root}/_bmad-output/planning-artifacts/ux-redesign-rapoo-vt7-2026-08-27.md"]
---

## Intent

**Problem:** The GTK3 window and tray use the default widget look (bare
`Gtk.Notebook` tabs, plain `Label`/`Button`, no styling). The user wants a
modern, Rapoo-Hub-like presentation with light and dark themes.

**Approach:** Drive the visual redesign through a GTK CSS theme: a new theme
token table, a light/dark/system preference persisted in `config.json`, a CSS
provider applied to the window, and CSS classes + non-breaking wrapper widgets
that present sections as cards and add a persistent device header. The tray
menu is restyled to match. All frozen `BatteryWindow`/pure-function/test
contracts (see Code Map) are preserved — this is a presentation-layer change,
not a state/logic rewrite.

## Boundaries & Constraints

**Always:**
- Keep every module-level pure function signature/return shape in
  `gui.py` (`params_render_plan`, `params_status_text`, `perf_rate_state`,
  `rf_radio_state`, `perf_mode_name`, `dpi_render_plan`, `dpi_status_text`,
  `pairing_render_plan`, `buttons_render_plan`) and `_PAIRING_TERMINAL`/
  `STATUS_*` — `tests/test_gui_units.py` imports them.
- Keep `BatteryWindow` widget attribute names (`_perf_radio`, `_rate_radio`,
  `_rf_radio`, `_tab_*`, `_pair_steps`, `_dpi_radio/_spin/_del`, `_param_check`,
  `_param_state`, `_system_page`, …), public methods and frozen handlers
  (`update_*`, `set_*_error`, `has_*`, `get_*_info`, `_on_lang_changed`,
  `_filter_keys` static, `_button_fn_label`).
- Widget construction must go through `gui.Gtk.<Class>(...)` (test stubs swap
  `gui.Gtk.*`); `gui.GLib` stays the timer source; dialogs via
  `gui.Gtk.MessageDialog(text=..., transient_for=self._win, ...)`.
- Keep `i18n.LANGS` = 3 locales with identical key sets; `tab_*` keys stay.
- `Tray` keeps `set_language/set_unknown/update/set_asleep` (main.py contract).

**Ask First:**
- Removing/replacing the `Gtk.Notebook` with a `Gtk.Stack`+rail nav (breaks
  `_on_tab_switch`/`_system_page`/`_tab_*` tests) — do NOT do this in this spec.
- Changing `_on_lang_changed` render call order (tests assert it).

**Never:**
- No change to device protocol, DPI/perf/params/buttons/system/app logic in
  `main.py` beyond theme plumbing.
- No new i18n key required in all 3 locales unless added in this spec; do not
  alter existing keys.
- Do not move to GTK4; do not reimplement pure functions.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| THEME_SET | user picks light/dark/system | CSS selector toggles `theme-light`/`theme-dark` on window root; `config.json` saved | invalid value in config -> fall back to "system" |
| THEME_LOAD | config has no theme key | default "system" (follow GTK dark detection) | N/A |
| LANG_CHANGE | `_on_lang_changed` fires | re-labels all existing widgets (existing behavior) AND refreshes CSS-dependent labels if any | unchanged |
| TRAY_STATE | `update/set_asleep/set_unknown` | menu info rows render muted via CSS class; battery icon unchanged | N/A |

## Code Map

- `src/rapoo_vt7/gui.py` — `BatteryWindow` window builds `Gtk.Notebook` + 6
  tabs (`_tab_battery/_dpi/_perf/_params/_buttons/_system`) and section builders
  `_build_*_section`. `_on_lang_changed` (gui.py:1786) re-labels all widgets;
  `_render` (gui.py:1898) writes status/detail; `_on_draw` paints the mouse card
  background. Add a `theme_*` class to the window root + a header bar widget;
  wrap section vboxes in card `Gtk.Frame`/`Gtk.Box` with CSS classes. Default
  window size 380x520 (gui.py:484) — may grow for the header.
- `src/rapoo_vt7/tray.py` — `Tray` builds `Gtk.Menu` with open/status/detail/
  refresh/quit items. `update` (tray.py:83) and `_render` (tray.py:92) set
  status/detail text; add CSS class to info items (via `Gtk.MenuItem` +
  provider on the app). Only `main.py`'s 4 calls constrain it.
- `src/rapoo_vt7/main.py` — `RapooApp.do_startup` (main.py:89) builds tray +
  window; add CSS provider load + theme resolution, and pass initial theme into
  `BatteryWindow`. `_apply_update` (main.py:165) already feeds tray+window.
- `src/rapoo_vt7/config.py` — `load_language/save_language` only. Add
  `load_theme/save_theme` reading/writing the same `config.json` (`"theme"`).
- `src/rapoo_vt7/i18n.py` — add transient keys only if needed (e.g.
  `theme_label`); must be added to ALL 3 locales or `test_i18n` fails.
- `tests/test_gui_units.py`, `tests/test_system.py` — frozen; must stay green.
- `tests/test_i18n.py` — asserts 3-locale key parity; new keys must be in all.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/theme.py` (NEW) -- token table + `apply_theme(window_root,
      theme)` mapping light/dark/system to a root class; pure, no GTK
      construction beyond class toggling.
- [x] `src/rapoo_vt7/config.py` -- add `load_theme/save_theme` (`"theme"`
      key), default `"system"`, bad value -> `"system"`.
- [x] `src/rapoo_vt7/gui.py` -- in `__init__` add root window class via
      `Gtk.StyleContext.add_class`, a device header bar (battery/mode/DPI/rate
      from `_last` + monitor via new setter on the app), wrap each section
      vbox in a card `Gtk.Frame` with a CSS class; keep every frozen attribute/
      method and `_on_lang_changed` behavior.
- [x] `src/rapoo_vt7/main.py` -- load CSS provider from a bundled `.css`, call
      `apply_theme` before `show_all`, wire theme toggle callback through a new
      `on_theme_change` (persist + re-apply), pass DPI/rate into header.
- [x] `assets/rapoo-vt7.css` (NEW) -- card/header/tab/button styling from the
      CSS token table for both `theme-light` and `theme-dark`; battery-color
      accents.
- [x] `src/rapoo_vt7/tray.py` -- add CSS class to info menu items (muted);
      optionally add DPI/rate detail row fed by `update`.
- [x] `src/rapoo_vt7/i18n.py` -- add `theme_label`/toggle tooltip + tray DPI
      row to all 3 locales (only if needed).

**Acceptance Criteria:**
- Given existing suites, when the window/tray/files above change, then
  `python3 -m unittest discover -s tests` stays fully green.
- Given a window with a root, when theme is light/dark, then the CSS provider
  applies the matching token set and the user can toggle light/dark/system,
  persisted across restarts.
- Given the header, when monitor updates battery/DPI/rate, then the header
  reflects them without touching `_render`/`_on_lang_changed` behavior.
- Given the tray, when state updates, then info rows render with the muted
  style and the DPI/rate detail row stays consistent with the window.

## Design Notes

GTK3 dark: use `Gtk.Settings.get_default().props.gtk_application_prefer_dark_theme`
or detect `prefer-dark`, and set the root class from the effective theme so a
single stylesheet branches on `window.theme-light`/`window.theme-dark`.

Golden example of card wrapper (keeps widget tree test-safe — a plain
`Gtk.Frame`/`Gtk.Box` with a class, children unchanged):
```
card = Gtk.Frame(); card.get_style_context().add_class("card")
inner = Gtk.Box(VERTICAL, spacing=10); card.add(inner)
# existing _build_*_section(vbox=inner) logic untouched
```

CSS tokens as class variables on the theme module, injected as `@define-color`
in the provider so both themes share one source:

```
@define-color card_bg @color-scheme-card-bg;   /* per theme */
.card { background: @card_bg; border-radius: 12px; }
```

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all pass (no regressions).
- `./run.sh` -- expected: window opens, light/dark/system toggle in header
  re-themes the cards/header instantly; tray menu shows muted info + DPI row.

**Manual checks (if no CLI):**
- Toggle each theme in the window; confirm cards, header, tabs and tray render
  with the token palette and battery-color accents in both light and dark.
- Restart the app; confirm the theme preference and language persist.

## Suggested Review Order

**Theme engine & resolution**

- Single token table injected as `@define-color` so both themes share one stylesheet; `system` follows the GTK dark preference.
  [`theme.py:88`](../../src/rapoo_vt7/theme.py#L88)
- `apply_theme` toggles one `theme-light`/`theme-dark` root class — the branch the whole sheet hangs off.
  [`theme.py:108`](../../src/rapoo_vt7/theme.py#L108)
- `build_css`+`new_provider` assemble tokens + base sheet into the `CssProvider`; failures degrade to the default GTK look.
  [`theme.py:125`](../../src/rapoo_vt7/theme.py#L125)
- `base_css` reads/caches the static stylesheet once.
  [`theme.py:69`](../../src/rapoo_vt7/theme.py#L69)

**Device header + cards (window)**

- Persistent header chip row (battery/mode/DPI/rate + theme combo), visible on every tab.
  [`gui.py:634`](../../src/rapoo_vt7/gui.py#L634)
- `_render_header` degrades each field to "--" independently; label widgets are distinct from value state (crash-regression).
  [`gui.py:705`](../../src/rapoo_vt7/gui.py#L705)
- `update_header` feeds DPI/rate without touching `_render`/`_on_lang_changed` behavior.
  [`gui.py:697`](../../src/rapoo_vt7/gui.py#L697)
- Theme-select change: guards same-code rebuild (P1), applies theme and notifies the app.
  [`gui.py:688`](../../src/rapoo_vt7/gui.py#L688)
- `_card_wrap` re-parents each section vbox into a styled card Frame, children preserved.
  [`gui.py:622`](../../src/rapoo_vt7/gui.py#L622)

**App wiring & rate feed**

- CSS provider created at application priority; `_retheme` removes the prior provider first (P2 patch).
  [`main.py:149`](../../src/rapoo_vt7/main.py#L149)
- `_refresh_header` pushes DPI/rate into the window header + tray row and never raises on partial state.
  [`main.py:165`](../../src/rapoo_vt7/main.py#L165)
- `_window_rate_hz` returns None until a rate is reported (no fabricated 1000 Hz, P3 patch).
  [`main.py:195`](../../src/rapoo_vt7/main.py#L195)

**Config persistence**

- `load_theme`/`save_theme` + merge-preserving `_save_setting` keep `language`/`theme` side by side; invalid value -> "system".
  [`config.py:31`](../../src/rapoo_vt7/config.py#L31)

**Tray**

- DPI/rate info row (`set_dpi`/`_render_dpi`) with muted style, fed from the same values as the header.
  [`tray.py:135`](../../src/rapoo_vt7/tray.py#L135)

**Localization**

- New `theme_*`/`header_*`/`tray_dpi` keys present in all 3 locales (parity enforced by test_i18n).
  [`i18n.py:25`](../../src/rapoo_vt7/i18n.py#L25)

**Tests / edges**

- Headless suite: theme resolution, config round-trip, header render path and the label-vs-value crash regression.
  [`test_theme.py:131`](../../tests/test_theme.py#L131)
- build_css token emission, apply_theme toggling, and the `_on_theme_changed` wiring + noop guard (P1).
  [`test_theme.py:247`](../../tests/test_theme.py#L247)

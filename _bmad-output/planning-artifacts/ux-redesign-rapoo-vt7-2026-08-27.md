# Rapoo VT7 — UI Redesign Design Specification

**Author:** Sally (UX Designer)
**Date:** 2026-08-27
**Scope:** From-scratch redesign of `src/rapoo_vt7/gui.py` (GTK3) **and** the
system-tray surface in `src/rapoo_vt7/tray.py`, keeping the existing pure
decision functions and all functional behavior.
**Status:** Design proposal — no code written yet.

---

## 1. Goal

Replace the current default-GTK "tabs of widgets" look with a modern,
Rapoo-Hub-inspired interface that:

- Feels current and polished (cards, hierarchy, spacing, rounded corners).
- Supports **both light and dark themes** (follow the system, with an
  explicit user override persisted in `config.json`).
- Keeps **every feature** (Battery/DPI/Performance/Parameters/Buttons/System)
  reachable and discoverable.
- Preserves the **headless-testable contracts** so the rewrite does not
  invalidate the existing 500+ test suite.

## 2. Design principles

1. **Device-first.** The connection/state of the mouse is the hero — not a
   stack of settings. Top of the window always shows the device's live state
   (battery, connection mode, DPI, rate) in a persistent header.
2. **Cards, not lists.** Each logical unit (DPI editors, performance modes,
   polling rate, RF, §C parameters, versions, naming, pairing, reset) becomes
   a rounded card with a clear title + divider, instead of a vertical soup of
   widgets.
3. **Color = meaning.** The battery color language already in place
   (green/yellow/red) extends to status accents across the app. Never use
   color as the *only* signal (accessibility).
4. **Dark + light from one token set.** All colors come from CSS custom
   variables / a single theme token table so both themes stay in sync.

## 3. Information architecture

Keep six features, but restructure *how* they're presented.

### Option A (recommended): left rail navigation, single content pane

A fixed left rail (like the web Hub side-nav) replaces the `Gtk.Notebook`.
Each item = icon + label. This gives the "app" feel and room for a persistent
header above the content area.

```
+--------------------------------------------------------------+
| [logo]  Device name · battery · mode            [theme toggle]|
+--------+-----------------------------------------------------+
|  Home  |                                                     |
|  DPI   |             <single content card>                   |
|  Perf  |                                                     |
| Params |                                                     |
| Botões |                                                     |
| Sistema|                                                     |
+--------+-----------------------------------------------------+
```

- Static content area swapped via `Gtk.Stack` + `Gtk.StackSwitcher` (the
  modern GTK idiom, plays well with CSS).
- Rail collapses gracefully at narrow widths (labels hidden, icons only).

### Option B (lighter): vertical cards on one scrollable column

No nav — one scrollable page of stacked cards in reading order
(Device → DPI → Performance → Parameters → Buttons → System). Simpler, but
less "app-like"; System and Button lists stretch the scroll far.

**Recommendation:** Option A. It scales with the growing feature set and
matches the Hub mental model the user referenced.

## 4. Header (persistent, all screens)

The device state bar from `_render`/`update` currently lives only on the
battery tab. Promote it to a **global header** so the user sees battery/mode
on every screen:

- Left: app mark (`assets/rapoo-vt7.svg`) + device name (from
  `system.read_name`).
- Center/right: live chip showing **battery % + charging bolt** (reuse the
  `icons.py` color logic), connection mode (USB/2.4G/BT), current DPI +
  polling rate (from the passive report-7 fields the app already tracks).
- Far right: theme toggle (light/dark/system) + language selector (moved up
  from the battery tab).

The header must remain **non-editable** and degrade to "--" per field
(reuse the version-row philosophy; no error banners).

## 5. Card pattern (shared component)

Every content block becomes a **Card**:

```
+-------------------------------------------+
| <Title>            <optional trailing btn> |
|-------------------------------------------|
|  ...content widgets...                    |
+-------------------------------------------+
```

CSS-driven: rounded corners, background `-var(--card-bg)`, 1px border
`-var(--border)`, margin/padding from a single spacing token. Sections that
were separate `<b>` headings (DPI / Performance / RF / Params / Versions /
Device name / Pairing) map 1:1 to cards — identical internal widget logic.

Destructive zones (Pairing, Factory Reset) render inside a **danger-styled
card** (accent border/tint) so their weight is clear without words.

## 6. Screen-by-screen card layout

### 6.1 Home / Device
- **Device card:** big stylized mouse (reuse `draw_mouse`) on a soft
  gradient background + live battery ring or percentage. The status line
  (`asleep` / `battery` / `charging`) from `_render`.
- **Connection card:** USB/2.4G/BT mode chip (+ tooltip with last-read time).
- Language + theme live in the header (removed from here).

### 6.2 DPI
- **Gear list card:** the existing active-gear rows (radio + spin + ✕) as a
  compact table inside the card. The current gear row is highlighted with the
  accent color (not just the radio dot).
- **Footer row:** "Add DPI" ghost button (disabled at 7) + status line.
- Keep 100% of `dpi_render_plan`/`dpi_status_text`/`_update_dpi_sensitivity`
  behavior.

### 6.3 Performance
- **Mode card:** 6 radio rows → render as a **segmented select / grid of
  pills** (each mode a tappable chip, the active one filled with accent).
- **Rate card:** 125–8000 Hz as a **horizontal segmented control** (still a
  radio group underneath, so `_on_rate_toggled` is unchanged).
- **RF card:** radio pair (Adaptive | Full) + low-power toggle.
- **Params card:** §C toggles as **switch rows** (GTK `Gtk.Switch` fil van de
  standard checkbox look), sliders for the selectable params, read-only rows.
  Reuse `params_render_plan` / `params_status_text`.

### 6.4 Buttons
- **Buttons card:** per-button rows (label + current function + pick) — same
  data flow, restyled. The picker dialog gets the same theme tokens.

### 6.5 System
- **Versions card** (mouse / receiver / software).
- **Device-name card** (entry + rename).
- **Pairing card** (danger): steps + status + start/cancel.
- **Factory-reset card** (danger): button + hint.

## 7. Theme system (light + dark)

### 7.1 Token table (single source of truth, CSS variables)

| Token            | Light             | Dark                  |
|------------------|-------------------|-----------------------|
| `--bg`           | `#f4f5f7`         | `#1b1c1f`             |
| `--fg`           | `#1f2328`         | `#e6e6e6`             |
| `--muted`        | `#6b7280`         | `#9ca3af`             |
| `--card-bg`      | `#ffffff`         | `#24262b`             |
| `--card-border`  | `#e2e5e9`         | `#33363c`             |
| `--accent`       | `#2c8e3a`         | `#4cc25a`             |
| `--accent-soft`  | `#e8f5e9`         | `#1f3323`             |
| `--danger`       | `#d93025`         | `#f28b82`             |
| `--danger-soft`  | `#fdecea`         | `#3a2323`             |
| battery green/yellow/red | reuse `icons.color_for` | same across themes |

### 7.2 Resolution order
1. Follow system theme by default (`gtk-application-prefer-dark-theme` /
   `GTK_THEME` detection).
2. Explicit user override stored in `config.json` (`"theme": "light"|"dark"|"system"`),
   alongside the existing `language` key.
3. CSS applied via `Gtk.CssProvider` + a root style class (`theme-light` /
   `theme-dark`) so a single stylesheet covers both.

### 7.3 Accessibility
- Color never sole indicator: charging uses bolt icon + "Carregando" text;
  low battery also text-based.
- Contrast ratio ≥ 4.5:1 for body text in both themes.
- Theme toggle animates (crossfade optional via CSS transition).

## 8. System tray (tray.py)

The tray is a **second rendering of the same device state**. Today it
duplicates the window's state (`_known`, `_asleep`, `_last`, `_lang`) and
re-derives the same labels — a source of drift. Keep the icon generation
(`icons.py`, Material mouse + %) unchanged; restyle/structure only the menu.

### 8.1 Current menu map (as-is)
```
Ouvir a janela...    ) -> on_open_window
─────────────────────────
<status: battery % ou 'asleep'>   (disabled)
<detail: "2.4G · 12:34">          (disabled)
─────────────────────────
Refresh now          ) -> on_refresh
─────────────────────────
Quit                 ) -> on_quit
```
The icon itself already encodes battery% + color + charging bolt — good. The
menu is flat and mixes an informational block with actions.

### 8.2 Target tray menu
Keep it **short and glanceable** (native menu favors compactness), but
sharpen the hierarchy:

```
Open window          ) -> on_open_window
─────────────────────────
→ Battery 82%  ⚡     (disabled status row, colored dot/bolt)
  2.4G · 12:34        (disabled, muted style)
  DPI 5000 · 8000Hz   (new optional row, from report 7)
─────────────────────────
Refresh now          ) -> on_refresh
─────────────────────────
Quit                 ) -> on_quit
```
- **Status + detail rows:** styled as muted/informational (CSS class
  `tray-muted`), visually distinct from actionable items.
- **Optional DPI/rate row:** the data already flows into the monitor
  (report 7); expose it here too since the window now shows it in the header
  — consistency across both surfaces.
- **Theme:** the tray inherits the panel theme by nature (AppIndicator); no
  theme toggle here. Only ensure text is set via the same i18n keys.

### 8.3 De-duplicate state
Prefer a single source of live device state (the monitor) feeding both
`Tray` and `BatteryWindow` through their existing `update(...)` /
`set_asleep()` / `set_language()` public methods. Do **not** change those
method signatures (they are frozen contracts); only stop independent
re-derivation where practical.

## 9. What is kept (frozen contracts)

- `params_render_plan`, `params_status_text` (test_gui_units)
- `perf_rate_state`, `rf_radio_state`, `perf_mode_name`
- `dpi_render_plan`, `dpi_status_text`
- `pairing_render_plan`, `_PAIRING_TERMINAL`, `update_pairing_state`
- `buttons_render_plan`, `_button_fn_label`, `_filter_keys`, picker flow
- All callbacks (`on_switch_gear`, `on_set_value`, `on_set_param`, …) and the
  busy/sensitivity guards (F2/F5/F6), `_invalidate_pending_edits`, timers.
- State fields (`_dpi`, `_perf`, `_params`, `_buttons`, `_last`, `_asleep`, …)
  and public methods `update`, `set_asleep`, `update_dpi`, `update_perf`,
  `update_params`, `update_buttons`, `update_versions`, `update_device_name`,
  `set_system_message`, `set_*_error`, `has_*`, `get_*_info`.

The architectural trick to preserve: **pure decision functions** stay exactly
as-is; only the *widget tree* + CSS are replaced. `__new__`-based headless
tests (sub-section construction) must keep working — so the card/window
constructor should still be constructible without a display where tests
require it, or tests are migrated to call the new sub-section builder through
the same public surface.

## 10. Migration & risk

### 10.1 Phased, keep tests green at each step
1. **Theme plumbing only:** add CSS provider + token table, apply `theme-*`
   class to the existing window. No layout change. (Low risk; suite must pass.)
2. **Header extraction:** promote the battery/state line into a persisting
   header across tabs (still `Gtk.Notebook`). (Low-medium.)
3. **Cardify:** wrap existing sections in styled `Gtk.Frame`/`Gtk.Box` "cards".
   (Medium — touches `_build_*_section`, but keeps every callback/widget.)
4. **Nav restructure:** replace `Gtk.Notebook` with
   `Gtk.Stack` + `Gtk.StackSwitcher` (left rail). (Medium-high — biggest change.)
5. **Per-feature polish:** segmented selects, switches, pills, danger cards.
6. **Tray menu:** restructure to target §8.2; add DPI/rate row (data already
   available), muted styling for info rows.
7. Re-run full suite + manual smoke on light/dark + language switch +
   tray menu.

### 10.2 Risk register
| Risk | Mitigation |
|---|---|
| Nav restructure breaks `_on_tab_switch` reads | Abstract "tab open" as a `page-activated` signal on the Stack; keep behavior identical |
| Switches/pills change widget signals | Keep radio/check/switch *underneath* (radio groups unchanged) so handlers fire the same way |
| Theme flicker at startup | Load CSS in `main.py` before `show_all`; default to system until user override |
| Headless tests build old widget tree | Preserve public surface; move sub-section builders behind the same methods; update `__new__` fixtures if the tree shape changes |
| Two-theme contrast drift | Single token table + automated contrast check on tokens |
| Tray state drifts from window | Single source of live state (monitor) feeding both via the frozen public methods; no new state fields |

### 10.3 Out of scope (this pass)
- GTK4 port (kept GTK3 — same as current stack, no framework change).
- Icon redesign (already Material-style; can refresh after the window).
- New hardware features (DPI/performance logic untouched).

## 11. Acceptance checklist
- [ ] Battery %/mode/DPI/rate visible on every screen (header).
- [ ] Light and dark themes both readable; CSS token table single-sourced.
- [ ] Theme + language preferences persisted and honored at startup.
- [ ] All six feature areas reachable + functionally identical to today.
- [ ] Full test suite green; no pure decision function altered.
- [ ] Danger zones (pairing, reset) visually distinct.
- [ ] Tray menu matches target §8.2 (status rows muted, DPI/rate row, same
      i18n keys); tray state does not drift from the window.
- [ ] Manual smoke on both themes and both languages (pt_BR/en) — window
      and tray.

---

*This is the design proposal. Implementation (if approved) will be a separate
engineering task, executed against the frozen contracts in §9.*

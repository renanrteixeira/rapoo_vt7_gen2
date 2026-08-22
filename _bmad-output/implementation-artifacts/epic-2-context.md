# Epic 2 Context: Phase 2 — DPI control (CAP-5)

<!-- Compiled from planning artifacts + retrospective evidence. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the user full control of the mouse's DPI configuration from the app: see the active gear, the per-gear X/Y values and the active button-cycle count, switch gears, edit a gear's value in place, add and remove gears from the cycle — mirroring the official A Hub semantics. Story 2-1 (done) shipped this as the window's "DPI" tab (the original "systray menu" framing evolved into the tabbed window during implementation).

## Stories

- Story 4 (2-1): DPI status + gear switch + value edit + add/delete — done

## Requirements & Constraints

- DPI data comes from EEPROM reads (`MOUSE_DPI_X_LIST` `0x0888`, `MOUSE_DPI_Y_LIST` `0x08C8`, `MOUSE_DPI_ENABLE_GEAR` `0x0896`, `MOUSE_DPI_CUR` `0x0898`) cross-checked with passive report 7 — never a hardcoded list.
- **The enable byte `0x0896` is a COUNT−1, not a bitmask**: the physical DPI button cycles the first (enable+1) slots of the X/Y tables. "Disabling" a gear = removing it from the compact list (A Hub `setDeviceGears` semantics).
- Every table write goes through `write_eeprom_verify` (≤24 B, bank 0); a readback mismatch rejects the change and surfaces an error — never accepted.
- The active list is kept sorted ascending by value on ADD; the current gear follows its DPI VALUE across the reorder (the DPI in use never changes).
- Spin edits change the value IN PLACE (no reorder, no re-select) and apply only when the edited gear's radio is marked (current gear) — editing another gear just stores the value (`dpi_stored` vs `dpi_edited` notifications).
- Cannot delete the last gear (list of 1); add is disabled when the cycle is full (7); add/delete re-select the current gear like the A Hub (first remaining when the current was deleted).
- User actions use `submit(..., wake=True)` — attempted even if the mouse just fell asleep; only a device timeout flips the monitor back to "asleep" with a localized message. Background reads while asleep are rejected.
- The physical DPI button stays in sync: report 7 mirrors gear+X/Y (`BatteryMonitor.on_report`) and the app re-reads the config and rebuilds the tab when it changes. Empty-tab recovery: every connected/open event re-checks `window.has_dpi()`.
- GUI-only user surface; all strings in `i18n.LANGS` (pt_BR/en/es), re-translated on language change.

## Technical Decisions

- `dpi.py` owns the device operations: `read_dpi`, `set_gear`, `set_value`, `set_gears` (compact-list rewrite), `add_gear`, `delete_gear` — following the read → show → write → re-read pattern established by Phase 0/1.
- Snapshots carry raw device values; presentation maps them to labels. On asleep/disconnected the last-known values are retained, never nulled.
- Errors are typed and surfaced non-blocking (status text / localized notification), never blocking dialogs.
- Known open items (epic-2 retro): clamp device-provided gear byte (F1), staleness token for pending edits vs the 600 ms timer across list mutations (F2), pure render plan extraction (F3), in-flight guard on DPI actions (F6), partial-failure fakes (F7).

## UX & Interaction Patterns

- "DPI" tab: radio per ACTIVE gear (selects current), X-value spin per gear, "✕" per gear (delete/compact), "Add DPI" button (appends 800, disabled when full). Status line shows gear/DPI/cycle-count; errors localize inline.
- No tray DPI submenu — DPI features live in the window only (removed when the tab shipped).

## Cross-Story Dependencies

- Builds on Phase 0/1 infrastructure: `settings.py` registry, `write_eeprom_verify`, report-7 listening, `submit(wake=...)`.
- Report-7 DPI mirror is shared with the battery monitor loop (same passive channel).
- Later epics reuse the same plumbing but have no dependency on this epic's specifics.

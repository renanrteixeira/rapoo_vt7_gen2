# Deferred Work

Entries appended by review loops (defer findings) and scope splits. Do not
modify existing entries; only append.

- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-eeprom-write-verify.md`
  summary: Late/stale ACK from a prior timed-out command can be misattributed to a new write because `read_response` ignores its `cmd_id` argument.
  evidence: `read_response` (device.py:189) never uses `cmd_id`; any rid-6 ACK completes the write. AD-2 (one command in flight, uncorrelated ACK dropped) resolves this at the session layer; for now the read-back verify is the safety net.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-eeprom-write-verify.md`
  summary: The 1.0 s write timeout is copied from the read path and never tuned against real EEPROM write latency.
  evidence: Writes are hardware-untestable before the S2 baseline exists (golden rule); timeout tuning belongs to the on-device validation phase (S2/S3).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-eeprom-write-verify.md`
  summary: `write_eeprom_verify` raises plain `ValueError` on read-back mismatch, indistinguishable from the pre-send guards — callers cannot tell "rejected before send" from "write applied but wrong".
  evidence: The dangerous case (EEPROM already modified) is the mismatch path; AD-8 mandates typed exceptions at the session layer, where this should be mapped.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-eeprom-write-verify.md`
  summary: CONTEXT.md §3.1 does not yet document the write reply format and verify semantics.
  evidence: Protocol documentation lag; no wire format changed this story (validated against the A Hub `sa` wrapper). Update alongside S2, which touches the EEPROM infrastructure docs.
- source_spec: `_bmad-output/implementation-artifacts/spec-1-1-eeprom-write-verify.md`
  summary: The real device's write-ACK reply shape is inferred from the read path, never hardware-validated.
  evidence: Every test mocks the ACK as `06 01 …`; if the firmware ACKs writes differently, `write_eeprom` would raise `CommandTimeout` on every success. Validation is only possible after the S2 baseline exists (golden rule).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-baseline-dump-settings-module.md`
  summary: `rf_strengthen_switch` and `low_power_warn_switch` both map to the full byte 0x08D8 as independent uint fields; writing either would silently clobber the other.
  evidence: The shared byte is a bit mask per docs/FEATURES.md §2.B. Before any Phase 2 write, S3 must model it as masked sub-fields (or the app must refuse whole-byte writes on 0x08D8).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-baseline-dump-settings-module.md`
  summary: DPI X/Y are registered as scalar 2-byte fields but are 7-gear arrays (`MOUSE_DPI_GEAR_LENGTH=7`); per-gear access is not modeled.
  evidence: docs/FEATURES.md §2.A lists them as arrays; the registry has no indexing. S4 (DPI menu) needs indexed access; formats are intentionally not validated in S2 (AD-6 keeps them as data edits).
- source_spec: `_bmad-output/implementation-artifacts/spec-1-2-baseline-dump-settings-module.md`
  summary: The baseline JSON records only the device path, not firmware version or VID/PID, so baselines from different firmware can't be distinguished for drift comparison.
  evidence: `build_baseline` (probe.py) stamps `device` only; firmware (`get_firmware`) is available on the same device and could be added when S3 needs drift/restore comparisons.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-rf-polling-rate.md`
  summary: `tools/probe.py` never cross-validates the story's central invariant that report-7 `rpt_usb` mirrors the `0x0880` rateCode.
  evidence: story 3-2 elevated `rpt_usb` to the trusted rate-code source; probe's `build_checks` only prints rpt_24g/rpt_usb as INFO and never compares `mouse_report` (0x0880) against report-7 `rpt_usb`, so the "validated on device" claim has no automated check.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-rf-polling-rate.md`
  summary: `battery._handle_report` indexes report-7 `data[10]`/`data[11]` guarded only by `len(data) <= 8`, so a short 9-11 byte passive report raises IndexError inside the poll loop.
  evidence: pre-existing in battery.py (untouched by this story); story 3-2 made `rpt_usb` (`data[11]`) the trusted rate source, so a malformed short report would crash the listener.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-2-rf-polling-rate.md`
  summary: Changing the app language re-translates battery/DPI labels but not the Desempenho tab's mode radios and titles (pre-existing from story 3-1; the RF labels were fixed this story).
  evidence: `_on_lang_changed` (gui.py) re-renders battery and DPI only; `_perf_title` and the six mode radios keep their construction-time language until a device refresh.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: `mouse_linear_ripple` (0x08C3) is numeric, not a bool toggle: the on-device write-test (2026-08-11) showed values 0/1/2/3 all written and read back exactly (factory read 0x03). Its scale (straight-line-correction level vs bit flags) was not confirmed, so no toggle is shipped — read-only state.
  evidence: `writetest_c.py` run on the live device 2026-08-11; `parameters.PARAMS` registers it `editable=False`.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: `mouse_sensorangle` (0x08C4) scale/meaning was not confirmed: it accepts 0/1 (write-test) but is a numeric "sensor angle" parameter (A Hub also offers manual/automatic), so an on/off toggle would be guesswork — read-only state.
  evidence: on-device write-test 2026-08-11; A Hub `parameters.sensorAngle` UI has manual/automatic modes.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: "Low power" has two candidate addresses resolved only to "both writable": `MOUSE_LOWPOWER` 0x08C6 and `MOUSE_POWERSAVE` 0x08AC each accept 0/1 and stick, but which one is the functional §C low-power control (and how it differs from the low-battery-warning bit at 0x08D8, story 3-2) is unresolved — both are read-only state with defer entries instead of guesswork toggles.
  evidence: on-device write-test 2026-08-11 (both bytes write/restore); FEATURES.md §2.C records both as read-only pending functional probing.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: Wave correction has no confirmed EEPROM address: the A Hub exposes `rippleCorrection`/`waveformCorrection` parameters but no §C byte is bound to it. Left out of the UI (not even read-only) and recorded here as deferred until the bundle/device probing maps it.
  evidence: docs/FEATURES.md §2.C "Wave correction" row stays ⚠️ without an EEPROM address; no settings.FIELDS entry exists.
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: The RF radio pair (`_on_rf_toggled`, story 3-2 widget committed alongside the 3-3 sliders) has no `btn.get_active()` guard, so one click emits `toggled` on both radios and submits `_on_set_rf` twice (potentially conflicting values + two notifications).
  evidence: gui.py `_on_rf_toggled` reads `self._rf_radio[1].get_active()` unconditionally; `_on_rate_toggled`/`_on_perf_toggled` in the same file do guard on `btn.get_active()`. Surfaced by the 3-3 review; out of 3-3 scope (RF is story 3-2).
- source_spec: `_bmad-output/implementation-artifacts/spec-3-3-mouse-parameters-toggles.md`
  summary: The battery-tab product image (`assets/mouse2.png`, `gui.py` `_MOUSE_IMAGE_PATH`/`_mouse_pixbuf`/`_draw_image_fit`) overclaims install safety (the three-dirname-up path resolves into site-packages, where assets are never installed), falls back to `draw_mouse` silently with no log, leaves `scale_simple`'s None return unguarded, and has no headless test coverage; it is also undocumented in CONTEXT.md/FEATURES.md.
  evidence: gui.py:18-49 comment says "so it also works from an install"; installed packages have no `assets/` dir; introduced with the mouse2.png change, surfaced by the 3-3 review (not this story's scope).

## Deferred from: code review of spec-3-1-performance-modes (08-12-2026)

- Spec-3-1 frozen text contradicts the shipped app: the polling-rate UI (story 3-2) and §C params (story 3-3) are implemented in this file set but owned by their own specs; spec-3-1's "Never" clauses and empty change log were never reconciled. Record the cross-story split in spec-3-1's change log.
- External rate/mode/RF changes (e.g. via the A Hub) are never detected — `_on_report` (main.py:118) only watches DPI; rate/mode/RF refresh happens only on state events or app actions. Report-7 driven re-read is a future enhancement.
- Production `print()` debug noise in `_on_report`/`_on_state`/`_refresh_dpi` (main.py:125,167,467-470) — cosmetic; convert to `logging` in a cleanup pass.
- Rate/mode tables are duplicated constants with no single source of truth — `RATE_HZ`/`RATE_INDEX_BY_CODE`/`PERF_SELECTABLE` and the `perf_mode_*` i18n keys must be manually kept in sync; a missing key raises KeyError at render (performance.py:40).
- `_on_param_scale` grid-snap duplicates `params_render_plan` snapping untested in the GUI (gui.py:567 vs gui.py:62) — the two could drift (round vs floor).
- `rate_index_from_code(0)` returns slot 0 instead of `SLOT_DEFAULT` when a stray `_rpt_usb` value of 0 arrives — the raw-index fallback overlaps the valid code space (performance.py:159).

## Deferred from: code review of spec-3-2-rf-polling-rate (08-12-2026)

- Default `main()` probe path has no try/except — battery/firmware probes raise a raw traceback when the mouse is asleep; `dump_main`/`status_main` handle it, the default flow does not. (probe.py:516)
- `battery_probe`/`firmware_probe` index the reply without a length guard — a short/empty reply (`06 00…` heartbeat) raises `IndexError`; `firmware_probe` also hard-codes PID bytes 6/7 instead of `protocol` offsets. (probe.py:27,45)
- `Field.encode` string branch truncates without re-appending NUL and can split a multi-byte UTF-8 char at `size` — `config_name` (16 B) could be written unterminated. (settings.py:37)
- Address `0x0884` is registered twice with conflicting meanings — `settings.mouse_slight` (sensor param, "do not edit") vs `parameters.lift_off` (1.0–2.0 mm slider); `probe --status` prints the same byte under two names and FEATURES.md §2.B ("don't edit") contradicts §2.C (editable slider). Same tension for `0x0885` (motion sync). Cross-story (3-3) registry/doc tension. (settings.py:89)
- `dpi_x_list`/`dpi_y_list` are 7-slot × 2-byte tables but modeled as scalar 2-byte fields — `--status` decodes only slot 0; the registry cannot read/write whole tables. (settings.py:81)
- `probe.py` default flow uses the private `dev._read_report(0.5)` while `capture_report7` uses the public `dev.read_report(...)` — inconsistent device API. (probe.py:524)
- `dump_main`/`status_main` do no device-identity check (PID `0x4613`/config interface/prefix) before reading EEPROM and writing the baseline — a wrong device that answers `0xA4` yields a garbage baseline; the JSON records only `dev.path`. (probe.py:446)
- `dpi_enable_gear` (validated as count-1 0..6) is classified as a generic bit-toggle field — `--status` prints a bit breakdown contradicting the count semantics in the registry comment. (probe.py:132)
- `Field.encode` bool coerces `1 if value else 0` before the `isinstance(int)` check — any truthy non-int (e.g. `"yes"`, `2`) is silently encoded as 1 rather than rejected. (settings.py:44)
- `test_status_button_hypothesis_1b_vs_2b` asserts `as_2b_le == (as_1b & 0xFF) | 0x0100`, a tautology of the `FakeDev` address-derived bytes — it does not exercise the 1B-vs-2B interpretation. (test_probe.py:211)
- `query()`, `battery_probe`, `firmware_probe`, `work_mode_probe`, `eeprom_probe` and the default `main()` path have zero test coverage — exactly where the unsafe reply indexing lives. (test_probe.py)
- Default `main()` prints `"\nOK"` and returns 0 unconditionally — a partial non-raising failure still exits 0, misleading scripts that check the exit code. (probe.py:529)
- `Field.range` on DPI fields does not enforce the 50-step grid — an off-grid DPI value passes the settings codec (the `dpi.py` write path does enforce it; latent only). (settings.py:81)
- `write_baseline` leaks the mkstemp fd if `os.fdopen` raises before the `with` block. (probe.py:115)
- `build_hypothesis` does `raw_by_addr[shared_addr]` unguarded — a `KeyError` if the RF fields are ever dropped from `settings.FIELDS`; safe today (both registered). (probe.py:223)
- FEATURES.md §2.C header claims the whole block "✅ writable (write-test 2026-08-11)" while Low power `0x08C6/0x08AC` is "function unresolved → read-only" and Wave correction has "no confirmed address" — the doc does not separate byte-writability from resolved semantics. (FEATURES.md §2.C)
- Rate-selector UI + `set_rate` write path go beyond the spec's "state/exposure only" Design Note (Ask First trigger) — already shipped, readback-verified, slot-mapped and validated on device; a retrospective scope note, not a defect.

## Deferred from: code review of spec-4-1-button-remap (08-12-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-4-1-button-remap.md`
  summary: `_on_set_rf` surfaces the hardcoded English `"unknown RF field %r"` via `_perf_error`/`_rf_error` instead of a localized i18n string (all other user strings in this story were localized; this one lives in story 3-2's RF handler).
  evidence: main.py `_on_set_rf` raises `ValueError("unknown RF field %r" % name)`; surfaced by the 4-1 blind-hunter review; out of 4-1 scope (RF is story 3-2).
- source_spec: `_bmad-output/implementation-artifacts/spec-4-1-button-remap.md`
  summary: The RF/desempenho code swept into the 4-1 diff (`_on_rf_toggled` double-submit guard, `update_perf` RF last-known retention, `_maybe_refresh_perf` RF-error retry, `perf_mode_name` fallback) ships with no test pinning the guards — ownership is stories 3-2/3-3, which own their own review/fix loops.
  evidence: verification-gap reviewer found zero references to `_on_rf_toggled`/`update_perf`/`perf_mode_name` in tests/; these behaviors belong to the 3-2/3-3 change logs already recorded in this same diff.
- source_spec: `_bmad-output/implementation-artifacts/spec-4-1-button-remap.md`
  summary: `set_function` does not enforce the "no write before the baseline exists" golden rule before writing EEPROM — a codebase-wide gap shared by every write path (dpi/parameters/performance), not a 4-1 regression.
  evidence: buttons.py `set_function` calls `write_eeprom_verify` with no baseline-existence guard; the only baseline reference in the tree is a comment in settings.py:15.
- source_spec: `_bmad-output/implementation-artifacts/spec-4-1-button-remap.md`
  summary: `probe.py build_checks` rate-mirror reads `fields["mouse_report"]["value"]` unguarded — a KeyError if the field were dropped/renamed kills the whole `--status` diagnostic (story 1-3 probe code).
  evidence: probe.py:352 `fields["mouse_report"]["value"]`; same pattern as the previously-flagged `raw_by_addr[shared_addr]` at probe.py:225.
- source_spec: `_bmad-output/implementation-artifacts/spec-4-1-button-remap.md`
  summary: A `write_eeprom_verify` read-back timeout after the write has landed surfaces an error although the button was already remapped on-device — inherent to the verify-after-write pattern used across the app (device.py), not 4-1-specific.
  evidence: buttons.py:247 `dev.write_eeprom_verify`; device.py:259-267 raises on mismatch or returns the readback; a timeout in `query` raises CommandTimeout before the mismatch check can run.

## Deferred from: code review of spec-5-1-factory-reset-with-confirmation (08-13-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: Factory-reset verification is intentionally narrow — only `MOUSE_DPI_CUR`, the RF byte `0x08D8` and the 7-slot `SENSOR_MODE` table are checked, so a partial reset that restores those markers but leaves DPI X/Y lists, gear-enable count, buttons or §C params untouched would still be reported as verified, while the dialog/hint text claims "ALL settings".
  evidence: spec's frozen intent names exactly these three markers (and "Always" scopes verification to "key EEPROM fields"); system.py `FACTORY_*` + `_is_factory_state`; the UI overclaim is a deliberate spec wording.
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: A near-default device whose three markers already match factory defaults reports a successful reset as `FactoryResetVerifyError` (the `after == before` change check fails), even though the reset wiped the non-verified settings — the Ask First "no change detected" case is surfaced as an error instead of a human question.
  evidence: system.py `factory_reset` raises when `after == before`; spec frozen text says to HALT and ask whether to accept — needs a live-device decision.
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: On a verification failure the mouse was very likely reset anyway (e.g. post-read timeout), but the app keeps showing the pre-reset cached DPI/buttons/params as editable — the user could write stale values back to the now-reset hardware; the "no state is changed" claim only holds for the status label.
  evidence: `_factory_reset_error` (main.py) only sets the system message and never refreshes the config tabs; only `_factory_reset_done` refreshes.
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: `_factory_reset_error` reads `self._window._lang` on the monitor thread (race with a concurrent language change) and hops only the resolved message to GTK, unlike `_factory_reset_done` which reads the language after the idle_add hop.
  evidence: main.py `_factory_reset_error` vs `_factory_reset_done`; same pattern as the pre-existing `_button_error`/`_param_error` handlers — codebase-wide, not 5-1-specific.
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: `Notify.Notification.new(...).show()` in `_factory_reset_done` is unguarded — if the notification daemon is unavailable, the raise aborts the success path and skips all four tab refreshes (same pattern as every other `_*_changed` handler).
  evidence: main.py `_factory_reset_done` calls `.show()` before `_refresh_*`; pre-existing pattern across `_param_changed`/`_button_changed`/`_perf_changed`.
- source_spec: `_bmad-output/implementation-artifacts/spec-5-1-factory-reset-with-confirmation.md`
  summary: The RF verification compares the whole shared byte `0x08D8` against `0x00`, so a factory state that preserves the low-power-warning bit (bit1) while clearing RF-strengthen (bit0) would report a false verification failure — needs a live-device read of the post-reset byte to confirm the full-byte default.
  evidence: system.py `FACTORY_RF_BYTE = 0x00` vs FEATURES.md §2.B describing `0x08D8` as a shared bit-mask byte (bit0 RF strengthen, bit1 low-power warning).

## Deferred from: scope split of spec-5-2-device-name-read-and-rename (08-13-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-5-2-device-name-read-and-rename.md`
  summary: Edge-case hardening of the device-name flow is deferred: asleep/wake behavior tests, the verify-mismatch Ask First retry flow, and the extended I/O-matrix unit tests.
  evidence: The full spec exceeded 1600 tokens (~1900); user chose `[S] Split`. Main goal = end-to-end read + rename (primitive + tab section + wiring + i18n + core tests). The re-translation row and busy-guard interaction items originally listed here shipped in the 5-2 review patches (op-scoped `set_system_message`, focus-guarded `update_device_name`, `_on_tab_switch` busy skip, `NameRowRetranslateTest`) and are no longer deferred.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-2-device-name-read-and-rename.md`
  summary: `write_device_name` does not enforce the "no write before the baseline exists" golden rule before calling `write_eeprom_verify` — the same codebase-wide gap already recorded for `set_function` in the 4-1 deferrals.
  evidence: system.py `write_device_name` calls `dev.write_eeprom_verify` with no baseline-existence guard; the only baseline reference in the tree is a comment in settings.py:15.

- source_spec: `_bmad-output/implementation-artifacts/spec-5-2-device-name-read-and-rename.md`
  summary: `_rename_error` and `_refresh_name.err` read `self._window._lang` on the monitor thread (race with a concurrent language change), the same pre-existing pattern as `_factory_reset_error` (recorded in the 5-1 deferrals) and the `_button_error`/`_param_error` handlers.
  evidence: main.py `_rename_error`/`_refresh_name.err` vs `_rename_done`/`_factory_reset_done`, which read the language after the idle_add hop; codebase-wide pattern, not 5-2-specific.

## Deferred from: code review of spec-5-3-receiver-pairing-protocol-discovery (08-17-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-5-3-receiver-pairing-protocol-discovery.md`
  summary: `device.py` `find_path` vs `open(prefix)` divergence — `find_path()` (device.py:105) is an unfiltered selection while `open(prefix)` filters `_scan()` candidates by prefix; the two entry points coexist and nothing documents why.
  evidence: device.py `find_path` :105-121 vs `open` :112; `find_path` pre-existed this story (used by the battery hot-swap reconnect); `open(prefix)` was added here. Pre-existing architecture, not a 5-3 regression.

## Deferred from: code review of spec-5-4-guided-receiver-pairing (08-18-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-5-4-guided-receiver-pairing.md`
  summary: No rollback of the receiver's RF address after a failed/cancelled pairing session — `write_rf` (0xA1) changes the receiver's wireless address and a failed run can leave the previously-paired mouse orphaned with no in-app recovery.
  evidence: `pairing_session.py` sends the random `write_rf` frame and never restores a prior address; no read-RF command is mapped in the protocol (the A Hub also never restores it) and the confirmation dialog warns the user; needs a reverse-mapped read-RF command + per-session RF preservation to fix.

## Deferred from: code review of spec-ui-redesign (08-27-2026)

- source_spec: `_bmad-output/implementation-artifacts/spec-ui-redesign.md`
  summary: `assets/rapoo-vt7.css` ships several styling rules whose classes are never applied to widgets — `.card-title`, `.card-title.accent`, `.card-hint`, `.status-label`, `.theme-tab`, `.device-header .header-label`, `button.ghost`, `button.primary`, `button.danger-btn`, `.card.danger`. The core `.card`/`.device-header`/`.header-chip`/`.tray-muted`/`.muted` classes render; the rest is inert.
  evidence: only `window-root`/`card`/`device-header`/`header-chip`/`batt`/`muted`/`tray-muted` are ever `add_class`-ed in `src/`; wiring the remaining classes to their widgets is a visual-polish pass across all six tabs that cannot be verified without a display, so it is not required by the spec ACs and was left for a focused UI pass.

- source_spec: `_bmad-output/implementation-artifacts/spec-ui-redesign.md`
  summary: The persistent header battery chip (`.header-chip.batt`) is hard-pinned to the green `@theme_accent`, so a low battery (5–19%) still renders a green chip instead of yellow/red — the level color-coding that the tray icon and status label provide is not carried into the header chip.
  evidence: `assets/rapoo-vt7.css` `.device-header .header-chip.batt { color: @theme_accent; }` plus `_render_header` in `gui.py` always renders the chip text without a level class; needs threshold logic in the header, out of scope of the theme/AC work.

- source_spec: `_bmad-output/implementation-artifacts/spec-ui-redesign.md`
  summary: Dialogs and secondary windows (per-button picker dialog, pairing dialogs) are never given a `theme-*`/`window-root` class, so in a dark/system session they render with the default light theme — a theme-coherence gap the persistent header advertises.
  evidence: `theme.apply_theme` is only applied to `self._win` plus synthetic `__new__` stubs; `Gtk.Dialog`/pairing dialogs are constructed without the theme classes and are not reachable from a single theme entry point.

- source_spec: `_bmad-output/implementation-artifacts/spec-ui-redesign.md`
  summary: The bundled stylesheet path resolves relative to the source tree (`ASSETS_DIR` from `theme.py`'s location) and `base_css()` permanently caches `""` on the first read failure, and `new_provider` swallows all failures to an empty provider — a missing/malformed `assets/rapoo-vt7.css` silently produces an unthemed app with no warning and no retry.
  evidence: `theme.py` `ASSETS_DIR`/`BASE_CSS_PATH` and `base_css` `_base_css_cache = ""` (never retried); `new_provider` `except Exception: load_from_data(b"")`. The app's deployment model is run-from-repo (`run.sh`), so the repo-relative path works in practice; live OS-scheme tracking for "system" is a separate enhancement also deferred here.

## Resolved: dialog theming + system scheme resolution/tracking (2026-08-28)

- Resolves the spec-ui-redesign deferral *"Dialogs and secondary windows ... never given a theme-\*/window-root class"*: added `theme.style_window(window_root, theme)` (adds `window-root` + the effective `theme-light`/`theme-dark` branch, idempotent) and applied it to the main window (guitui `BatteryWindow.__init__`) and all three secondary dialogs — pairing OK (`_on_pairing_clicked`), factory-reset confirm (`_on_factory_reset_clicked`) and the per-button picker (`_open_picker`). Tests: `StyleWindowTest` (test_theme.py) + `test_dialog_is_themed` (test_system.py); `_FakeDialog` in test_system.py gains `get_style_context`/`add_class`/`remove_class`/`has_class` and both confirm-dialog setups get `window._theme`.
- Resolves the *"live OS-scheme tracking for system"* deferral: `theme.effective_theme("system")` now reads `Gio.Settings` `org.gnome.desktop.interface color-scheme` (correct binding — `GLib.Settings` is absent on Ubuntu 26.04), falls back to `gtk-theme-name` ending in `-dark`, then GTK `gtk-application-prefer-dark-theme`; `RapooApp._start_system_theme_watch`/`_on_system_scheme_change` re-render live on scheme change. Tests: `ThemeResolutionTest` (Gio + gtk-theme-name + no-key fallbacks) and `SystemThemeWatchTest`.
- Note: the *stylesheets / BASE_CSS_PATH / cache-forever-empty* deferral (last bullet above) is NOT resolved — the repo-relative asset path + silent-empty-provider behavior remains as documented.

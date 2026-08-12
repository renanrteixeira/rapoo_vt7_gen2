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

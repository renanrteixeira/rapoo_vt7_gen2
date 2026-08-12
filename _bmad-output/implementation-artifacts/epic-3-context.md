# Epic 3 Context: Phase 3 — Performance / parameters (CAP-6)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Give the user control over the mouse's performance and parameter set from the app's window: performance mode per polling-rate slot (story 3-1, done), RF strategy + polling-rate state (story 3-2, done), and the Section-C mouse-parameter toggles — motion sync, linear/wave correction, sensor angle, glass tracking, press/release debounce, lift-off height, DC switch, sleep time, low power (story 3-3, next). Every parameter flows read → show → write → re-read → confirm persistence, and each change is confirmed on the real device before the story is done. This completes CAP-6 and leaves the window's "Desempenho" (performance) surface as the single home for performance and parameter control.

## Stories

- Story 5 (3-1): Performance modes — done
- Story 6 (3-2): RF + polling rate — done
- Story 7 (3-3): Mouse parameters toggles — next

## Requirements & Constraints

- Every parameter follows the read → show → write → re-read flow and is confirmed on the real device; a readback that differs from the write is rejected and surfaced as an error, never accepted.
- Golden rule applies to every write: baseline exists → write (≤ 24 bytes, bank 0) → verify by immediate re-read. A read-modify-write is one atomic queue entry and must preserve unrelated bits when a byte is shared.
- All Section-C addresses are confirmed 1B; current device reads: motion sync `0x0885`=1, linear correction `0x08C3`=3, sensor angle `0x08C4`=0, glass `0x08C5`=0 (product `enableGlassTracking: true`), press debounce `0x08C0`=2, release debounce `0x08C1`=2, lift-off `0x0884`=1, DC switch `0x08DA`=0, sleep time `0x08C2`=2, low power `0x08C6`/`0x08AC`=0.
- Open field questions must be resolved before presenting that toggle: wave correction has no confirmed field (candidate: sensor angle `0x08C4` or a dedicated address); lift-off value→height scale (product 1.0–2.0, step 0.1) awaits a write test; low power has two candidate addresses. Do not ship a toggle on an unverified field.
- Do not conflate the Section-C "low power" toggle with the low-power-warning bit inside the shared `0x08D8` byte (that belongs to the RF feature, story 3-2).
- User surface is GUI-only (window/menu), never the CLI; all user strings live in `i18n.LANGS` (pt_BR/en/es), including re-translation when the language changes.
- User-initiated writes are attempted even if the mouse just fell asleep (wake the device); a device timeout flips the monitor back to "asleep". Background reads while asleep are rejected, not queued forever.
- Run the suite with `python3 -m unittest discover -s tests` (FakeDev / FakeClock / Collector injection).

## Technical Decisions

- Follow the pattern already proven in this epic: `performance.py` holds the field read/write primitives with immediate readback verify; `protocol.py` owns wire constants and bank-0 offsets; `settings.py` is the pure field registry (raw bytes + size/type as data); the worker owns the fd, the command queue, and sole golden-rule execution. GUI never touches hidraw.
- Masked writes with verify are the established pattern for a shared/bit-level byte (`0x08D8`, story 3-2: `read_rf`/`write_rf_strengthen`/`write_low_power_warn` with `*_MASK` constants) — reuse this approach for any Section-C field that turns out to be bit-packed.
- Active polling-rate slot derives from report 7 `rpt_usb` (the rateCode) with a default-slot fallback; rate→Hz mapping lives in presentation. Reports are indexed on the raw report (byte 0 = report id), offset by 1 vs WebHID.
- Snapshots carry raw device values; presentation maps them to labels/Hz. On asleep/disconnected the last-known values are retained, never nulled.
- Errors are typed and surfaced non-blocking (status text / notifications), never blocking dialogs.

## UX & Interaction Patterns

- Story 3-3 renders the Section-C parameters as toggles in the window (the existing tabs pattern — "Desempenho" is the established home for performance/sensor controls). Each toggle: current state shown from a read, write on change, re-read to confirm, error text on mismatch.
- Every toggle label is localized; a language change must re-translate the new labels (a known pitfall: the mode radios from story 3-1 weren't re-translated on language change).

## Cross-Story Dependencies

- 3-3 builds on the infrastructure from 3-1/3-2: the `performance.py` read/write+verify primitives, `rpt_usb`→slot mapping, the Desempenho tab, and the `settings.py` registry from Phase 0.
- Field-format open questions (wave correction, lift-off scale, low-power address) are resolved the same way earlier phases did — device write-diff / cross-validation feeding `docs/FEATURES.md` §2.C and the registry — before the toggle is enabled.
- Later epics (button remap, system operations) reuse the same read → show → write → verify plumbing, but have no direct dependency on this epic.

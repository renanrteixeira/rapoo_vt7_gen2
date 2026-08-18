---
title: 'Guided receiver pairing (5-4)'
type: 'feature'
created: '08-18-2026'
status: 'done'
review_loop_iteration: 0
baseline_commit: '168616584226736754421aa3091dcb4aa72e919a'
context: ['docs/FEATURES.md', 'docs/index-B0XNTd12.js', 'docs/rapoo_hub_app.js']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Story 5-3 mapped and validated the receiver-pairing commands (`0xA0`
start-match, `0xA1` write-RF, `0xA7` get-match-result) but no app surface ships
the flow — the last CAP-8 gap is a guided UI that performs receiver pairing like
the A Hub's `deviceMatcher`/`MatcherDialog`.

**Approach:** Ship a GUI-only, user-confirmed pairing session in the app window
that mirrors the A Hub sequence — confirmation dialog, then send `start_match` +
`write_rf` (full frames from `pairing_commands()`, random RF bytes) to the
**receiver only** (`RapooDevice().open(prefix=0xA5)`), then run a bounded
matching loop (poll `0xA7`, listen report 7 raw for the `0xB1` pairing-success
sub-command, poll connected VID/PID) while the user follows the localized 3-step
physical flow (wired connect → power-cycle → press L+M+R). The session runs on
its **own thread + own fd**, leaving `BatteryMonitor` untouched. First: a
probe-only `--pair-run` harness (Ask First) validates the success/failure
signals on the real device so the app logic is pinned before shipping.

## Boundaries & Constraints

**Always:**
- Receiver-only access: `RapooDevice().open(prefix=protocol.PREFIX_WIRELESS)`;
  `DeviceNotFound` → localized "receiver not found", nothing sent. Never route
  pairing commands to the USB-cable mouse.
- Sequence = A Hub `MatcherDialog` (docs/index-B0XNTd12.js:5526): `start_match`
  `[0xA5,0xA0,0x81]`, then `write_rf` `[0xA5,0xA1,0x8F,rf0..rf3]` (rf = random 4
  B via `pairing_commands()`), then matching loop until result or window
  (60 s, A Hub default).
- Destructive-write safety: `0xA0`/`0xA1` fire **only** after a blocking,
  localized confirmation dialog warning that the receiver's wireless address
  changes (a failed session may force re-pairing the current mouse); never from
  any passive path. GUI dialog at click time (`_on_factory_reset_clicked`
  pattern, gui.py:762).
- Detection: `0xA7` reply `data[2]==0` → failed (validated 2026-08-17).
  Success candidates (pinned by the on-device validation task below):
  report-7 raw `data[1]==0xB1` (A Hub `VTnrf54LBaseParser`, rap
  oo_hub_app.js:291387), persistent non-zero `0xA7`, connected VID/PID. Until
  validated, treat as candidates and mark FEATURES.md accordingly.
- The monitor's report-7 parser (`battery.py:_handle_report`) is NOT changed:
  the session reads raw reports on its own fd; the validated CONTEXT §3.3
  layout stays authoritative for the app.
- Session is cancellable (stop event), daemon thread, never leaves the receiver
  mid-write on quit; errors surface localized + non-blocking via
  `set_system_message`-style status; all strings via `i18n.LANGS` (pt_BR/en/es)
  with re-translation in `_on_lang_changed`.
- Mirrors `system.py`/`buttons.py`: typed errors, readback where applicable,
  module pattern (`pairing.py` protocol + `pairing_session.py` worker), headless
  tests with FakeDev.

**Ask First:**
- The on-device validation run (`probe.py --pair-run`, real receiver + mouse,
  TTY + `--i-understand-risks` + confirmation) must be executed by the human —
  it changes the receiver's pairing state (the current mouse may need
  re-pairing). The spec's success/failure semantics flip 🔶→✅ only from its
  observed evidence; if it contradicts the A Hub, HALT and reconcile.
- If validation shows the receiver never emits `0xB1`, the success signal is
  re-decided (0xA7 semantics / VID-PID) before the app logic is finalized.

**Never:**
- No pairing commands from the monitor, the tray, or any background path.
- No EEPROM writes / no baseline writes; `0xA0`/`0xA1` are commands, not writes.
- No change to `battery.py` `_handle_report` or to `device.open()` default.
- No multi-device selection UI (the app has one receiver); no 0xB1 decoding
  inside the normal report-7 path.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| PAIR_NO_RECEIVER | no `0xA5` candidate | localized "receiver not found"; nothing sent | non-blocking status |
| PAIR_CANCEL | dialog dismissed | no `0xA0`/`0xA1` sent | N/A |
| PAIR_START | confirmed, receiver open | session thread: steps shown, `start_match` + `write_rf` full frames sent | open errors → localized status |
| PAIR_MATCHING | loop active | step 3 highlighted; 0xA7 polled; report 7 raw listened; stop/cancel honored | per-iteration errors non-fatal |
| PAIR_FAILED | 0xA7 `data[2]==0` | "pairing failed" result | N/A |
| PAIR_SUCCESS | validated signal fires | "pairing successful" result | N/A |
| PAIR_TIMEOUT | window expires, no result | "timeout" result | N/A |
| PAIR_CANCELLED | user cancels mid-loop | loop exits, receiver not written further | N/A |
| PAIR_DEVICE_ERROR | OSError/CommandTimeout mid-session | localized error, session ends | non-blocking |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/protocol.py` -- add `PAIR_SUCCESS_REPORT=0xB1` (report-7 sub-command) + `MATCH_RESULT_OFFSET=2` (hidraw `data[2]`), near the PAIR_* block (protocol.py:33-37).
- `src/rapoo_vt7/pairing.py` -- keep as-is (frames/flow/decode already ship); optional `match_result_byte(resp)` guard helper for the 0xA7 decode (ACK + len, mirrors `_decode_connected_field`).
- `src/rapoo_vt7/pairing_session.py` -- NEW worker: `PairingSession(factory, window=60.0, poll=1.0)` with `start()/cancel()/is_running`; own daemon thread + own `RapooDevice().open(prefix=0xA5)`; sends `pairing_commands()` frames; matching loop (report-7 raw for `0xB1`, `query(PAIR_GET_RESULT)`, `decode_connected_vid_pid`); callbacks `on_step(n)`, `on_result(status)`; typed `PairingSessionError`/`ReceiverNotFound`; factory injectable for tests.
- `src/rapoo_vt7/gui.py` -- `_build_system_section` (:675): append a "pairing" block — title, "Start pairing" button, 3 localized step labels + a status label; `_on_pairing_clicked` confirmation dialog (factory-reset pattern :762); `set_pairing_message(msg, err=False)`, `update_pairing_state(step_n, status)`; busy flag `_pair_busy`; re-translation in `_on_lang_changed` (:1337 block).
- `src/rapoo_vt7/main.py` -- wire `on_start_pairing`/`on_cancel_pairing` callbacks into `BatteryWindow` (:95-112); start/stop the session; callbacks hop `GLib.idle_add`; keep `BatteryMonitor` untouched.
- `src/rapoo_vt7/i18n.py` -- new keys (pairing_*) in all 3 locales (key-set parity enforced by test_i18n.py).
- `tools/probe.py` -- add `--pair-run` (Ask First + TTY gate reusing `_pair_destructive`): open receiver, send start_match + write_rf (echo RF), poll 0xA7 every ~1.5 s for `PROBE_PAIR_WINDOW`, dump report 7 raw + flag `0xB1`; prints result-byte history for the validation evidence.
- `tests/test_pairing_session.py` -- NEW: FakeDev-driven session tests (frames sent, result transitions, cancel, timeout, receiver-not-found, error isolation).
- `tests/test_system.py` / `test_gui_units.py` -- pairing block: dialog gate, busy flags, status updates, pure step-render decisions.
- `tests/test_probe.py` -- `--pair-run` dispatch/refusal/partial headless cases.
- `docs/FEATURES.md` -- §E: flip validated pairing rows ✅ with the 2026-08-18 evidence; document the app flow.

## Tasks & Acceptance

**Execution:**
- [x] `tools/probe.py` -- `--pair-run` harness (Ask First, destructive gate) -- on-device validation of success/failure signals
- [x] `src/rapoo_vt7/protocol.py` -- `PAIR_SUCCESS_REPORT` + `MATCH_RESULT_OFFSET` constants -- wire names for validated offsets
- [x] `src/rapoo_vt7/pairing_session.py` -- session worker (thread + receiver-only fd + frames + matching loop + cancel) -- orchestration
- [x] `src/rapoo_vt7/gui.py` -- pairing block + confirmation dialog + status/step updates + re-translation -- user surface
- [x] `src/rapoo_vt7/main.py` -- session wiring + idle_add callbacks -- glue
- [x] `src/rapoo_vt7/i18n.py` -- pairing_* keys in 3 locales -- localization
- [x] `tests/test_pairing_session.py` + `tests/test_system.py` + `test_gui_units.py` + `tests/test_probe.py` -- I/O matrix + AC coverage -- regression
- [x] `docs/FEATURES.md` -- §E evidence-backed ✅ flip -- tracking

**Acceptance Criteria:**
- Given a fake receiver and a confirmed start, a `PairingSession` sends exactly `[0xA5,0xA0,0x81]` then `[0xA5,0xA1,0x8F,rf0..rf3]` and enters the matching loop.
- Given a fake receiver whose 0xA7 reply has `data[2]==0`, the session reports failed.
- Given a fake receiver emitting report-7 `data[1]==0xB1` during matching, the session reports success.
- Given no `0xA5` candidate, the window shows the localized "receiver not found" message and no command is sent.
- Given a cancelled confirmation dialog, nothing is sent; given cancel during matching, the loop stops and no further pairing command is written.
- Given the full suite, all existing + new tests pass (392 baseline + new).
- Given FEATURES.md, §E pairing rows validated on-device in this story flip to ✅ with the observed byte evidence and an "Ask First, app-gated" note.

## Spec Change Log

_Empty until the first bad_spec loopback._

## Design Notes

Device access: the session owns a separate `RapooDevice` on the receiver (same
pattern as `tools/probe.py:538-540`). hidraw supports multiple open fds in one
process — each fd receives its own copy of every report, so the monitor keeps
parsing normally and the session sees the same reports (incl. a possible `0xB1`)
without contention. `BatteryMonitor` may flip to "asleep" during the session
(mouse power-cycled) and wakes on report 7 afterwards — acceptable, nothing to
change. `0xA0`/`0xA1` never answer on input 6 (feature-report-only, unreadable
on hidraw), so the session must not wait for their ACK (probe precedent,
probe.py:607-612). Success detection is validated on-device first; default order:
`0xB1` report → persistent non-zero `0xA7` → connected VID/PID.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- all pass (392 baseline + new)
- `python3 -m compileall -q src/ tools/` -- no errors
- `python3 tools/probe.py --pair-run` (real receiver + mouse, TTY, Ask First) -- performs the flow, prints 0xA7 result-byte history + report-7 dumps incl. any `0xB1`; exit 0; evidence recorded in FEATURES.md §E

**Manual checks (if no CLI):**
- Window → System tab: pairing block shows the 3 localized steps, live status (matching/success/failed/timeout), busy-guard during a run, and a destructive-warning confirmation dialog before any command fires.

## Suggested Review Order

**Design intent (entry point)**

- Own daemon thread + own receiver-only fd; never touches the monitor
  [`pairing_session.py:112`](../../src/rapoo_vt7/pairing_session.py#L112)

**Destructive-write discipline**

- Readiness gate: no `0xA0`/`0xA1` into a sleeping receiver (3× 0xA7 probe first)
  [`pairing_session.py:118`](../../src/rapoo_vt7/pairing_session.py#L118)

- Blocking confirmation dialog warns the RF address changes before anything fires
  [`gui.py:816`](../../src/rapoo_vt7/gui.py#L816)

- Quit mid-session: `_quitting` flag drops callbacks before teardown
  [`main.py:814`](../../src/rapoo_vt7/main.py#L814)

**Success/failure detection**

- Matching loop: `0xB1` report → streak-2 non-zero `0xA7` → none→attached VID/PID; streak-2 zeros for failure
  [`pairing_session.py:187`](../../src/rapoo_vt7/pairing_session.py#L187)

- Reply-shape guard for the 0xA7 result byte (0 = failed, validated)
  [`pairing.py:97`](../../src/rapoo_vt7/pairing.py#L97)

- Wire constants for the report-7 sub-command and result offset
  [`protocol.py:40`](../../src/rapoo_vt7/protocol.py#L40)

**UI binding**

- Pure render decision + step clamp (early errors highlight step 1, not L+M+R)
  [`gui.py:85`](../../src/rapoo_vt7/gui.py#L85)

- Terminal state stores the localized message + current step for re-render
  [`gui.py:858`](../../src/rapoo_vt7/gui.py#L858)

- Language change re-renders the stored message (never the raw `{error}` placeholder)
  [`gui.py:1476`](../../src/rapoo_vt7/gui.py#L1476)

- Result localization + notification wiring on the GTK thread
  [`main.py:617`](../../src/rapoo_vt7/main.py#L617)

**Validation harness**

- `--pair-run` full flow with inconclusive exit + result-byte history
  [`probe.py:655`](../../src/rapoo_vt7/probe.py#L655)

- Dispatch refuses non-positive `PROBE_PAIR_WINDOW`
  [`probe.py:868`](../../src/rapoo_vt7/probe.py#L868)

**Coverage**

- Session edge cases (readiness gate, baseline attached, streaks, short 0xB1 report)
  [`test_pairing_session.py:143`](../../tests/test_pairing_session.py#L143)

- GUI block: dialog gate, stale-state reset, retranslation with stored message
  [`test_system.py:1291`](../../tests/test_system.py#L1291)

- Probe harness headless cases incl. inconclusive/non-zero branches
  [`test_probe.py:651`](../../tests/test_probe.py#L651)

- i18n key parity + format rendering across locales
  [`test_system.py:1746`](../../tests/test_system.py#L1746)
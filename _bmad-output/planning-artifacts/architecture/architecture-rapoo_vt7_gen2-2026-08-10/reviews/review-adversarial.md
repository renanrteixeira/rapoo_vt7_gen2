# Adversarial Architecture Review — Rapoo VT7 spine

**Review type:** adversarial (conforming-but-incompatible unit pairs)
**Target:** `ARCHITECTURE-SPINE.md` (AD-1..AD-9, 2026-08-10)
**Reviewer:** adversarial architecture subagent
**Date:** 2026-08-10

---

## Verdict

**Conditionally ratifiable — not yet build-substrate-safe.** The nine ADs correctly
ratify the brownfield seams (sole-hidraw `device.py`, push callbacks, `idle_add`
bridge, i18n, pycairo icons, both PIDs). But three of them — AD-2, AD-3, AD-6 —
are *under-specified at exactly the seams where they touch*, and the wire itself
has **no per-command correlation** (no sequence number, no tag in the reply). That
one hardware fact turns "rid 6 ACK completes the oldest pending command" from a
rule into a *prayer*. Every pair below builds strictly inside the letter of the
ADs and lands on incompatible behavior. The spine must be tightened before Phase 0
stories are cut; the riskiest unbound seam is the **command/future lifecycle**
(Findings 1, 2, 4) which Phase 0 (EEPROM write) walks into first.

The spine passes the *ratification* test (it reflects the codebase it describes)
but fails the *build-substrate* test: it does not force two independent one-level-
down units to converge on the same protocol with the device.

---

## Part A — Conforming-but-incompatible unit pairs

Method: for each hole, two one-level-down units (module/story implementations)
are constructed that each cite the ADs as their mandate and still disagree.

### Finding 1 — No wire correlation ⇒ "oldest pending" is ambiguous ⇒ command futures can complete with the wrong result (AD-2 × AD-3)

The protocol reply carries **no echo of the command id, no sequence number** —
a `0xA4 read_eeprom` reply is byte-identical in shape to any other `0xA4` reply,
and an ACK from a timed-out command is indistinguishable from an ACK for the
current one. AD-2 says "rid 6 ACK completes the **oldest pending** command" and
AD-3 says "enqueue a command request returning a future." Neither AD fixes the
pipeline depth, the dedup policy, or the orphan/duplicate-ACK policy.

- **Unit A (depth-1 pipeline):** the queue accepts a new request only while idle;
  a second request returns a "busy" future immediately. While a command is in
  flight, any ACK completes it. Timed-out commands resolve their future and the
  worker *drops* any ACK that arrives afterwards.
- **Unit B (bounded pipeline, depth N):** the worker issues up to N commands,
  matches ACKs oldest-first (it needs the throughput for Phase 3 "set all
  parameters" flows), and buffers an ACK arriving with no pending command to
  match against the *next* command.

Both obey AD-2 and AD-3 to the letter. On the real device: a user clicks "switch
gear" while a battery poll is in flight. Under A the gear command is rejected
("busy") — user sees an error that the device would have accepted. Under B the
gear command is issued; the mouse answers the *battery poll* with an ACK; if any
report is dropped or duplicated by the 2.4G link, the gear future completes with
the battery poll's result — a **silent wrong-success** on a *write* command (the
one class of command that must never be falsely acknowledged).

**Hole:** AD-2's "oldest pending" only names a strategy; it does not bind the
condition under which that strategy is *sound* (exactly one outstanding command
+ defined orphan handling).

**Fix (tighten AD-2/AD-3):** mandate **exactly one command in flight at a time**
(pipeline depth 1; further requests queue, depth 1 is also fine); an ACK with no
pending command is **dropped and counted** (logged, surfaced to state), never
buffered for the next command; a timed-out command **resolves its future once**
(typed `CommandTimeout`) and any late ACK is dropped. Add: "matching is by
ordering only, therefore ordering is total — one in flight, FIFO dequeue."

---

### Finding 2 — Asleep ⇒ futures dangle forever; nobody defines the user-command-while-asleep policy (AD-3 × AD-8)

AD-8 mandates the listen-only discipline ("0xAA only on first connect and after
fallback"; "prevents command flood while the mouse sleeps") and lists
`asleep` as a state. AD-3 promises a future for every user action. The ADs never
say what a *user* command does to a sleeping mouse.

- **Unit A (defer):** while `asleep`, user commands are queued but not sent;
  the queue drains FIFO on the first passive report 7. A queued "set DPI" can sit
  pending for minutes — the GUI's spinner stays up with no timeout.
- **Unit B (send-anyway):** user commands are user intent, not polling; they are
  sent immediately. The empty reply (`06 00`) is treated as a timeout; the future
  resolves with an error and the worker returns to listen-only.

Both obey AD-3 (future returned) and both *claim* AD-8 (A: never floods; B:
floods only on explicit user action). Behavior diverges: A silently ignores a
user's explicit action until the mouse happens to move; B violates the spirit of
"asleep keeps the listen-only discipline" — yet nothing in AD-8 forbids it for
*user* commands, because AD-8 was written around *polling* commands only.

**Hole:** AD-8's discipline is scoped to the internal poll, not to user commands;
no AD defines the future lifecycle (timeout, cancel, wake-and-drain) or the
GUI-facing semantics of a command issued while asleep.

**Fix (new AD or AD-3 clause):** while `asleep`, user commands are **queued but
not sent**; the queue drains in FIFO order on wake (first report 7); every
future resolves **exactly once** within a bounded time — success, `CommandTimeout`,
`Cancelled` (app quit), or `DeviceGone` (disconnect). Add a defined behavior: a
user command issued while asleep is shown as "pending — move the mouse" (non-
blocking), and a manual "Refresh" is the explicit wake path.

---

### Finding 3 — Hot-swap mid-command: replay or not? (AD-2 × AD-3 × AD-9, against brownfield `device.query`)

The brownfield `RapooDevice.query` auto-retries a timed-out command by switching
interface (`_try_next`) — hot swap lives *inside* the transport. The spine moves
fd ownership and routing to the worker (AD-2/AD-3) but never says whether the
worker *replays* a command on the new interface.

- **Unit A (replay):** on interface switch the worker re-issues the pending
  command on the new fd (mirrors today's `query` retry). A DPI write that timed
  out on the 2.4G link may be applied **twice** — once silently on the old
  interface (the write actually landed; the reply was lost) and once on the new.
- **Unit B (fail-don't-replay):** a command that survives an interface switch
  resolves as `DeviceGone`/`CommandTimeout`; the user retries. Never double-
  writes, but "set DPI 1200" now fails on a hot swap that the current app survives.

Both obey the ADs. The difference is the difference between a *harmless failure*
and a *latent double-write to on-device EEPROM* — and the spine is silent on it,
so Phase 0 (write_eeprom, the first write path) inherits the brownfield replay
semantics by default with no decision recorded.

**Fix (AD-3 clause):** the worker owns hot-swap **exactly as the transport's
interface switching is retired** — a command that times out across an interface
switch is **not** replayed automatically; it resolves as a typed error with the
interface-change reason attached. Writes must be single-execution. (Idempotent
re-read verification from AD-6 then doubles as the safety net.)

---

### Finding 4 — Write-verify re-read races the passive report 7 ⇒ snapshot shows stale post-write state (AD-4 × AD-6)

AD-4 makes the worker the sole producer of one immutable snapshot whose fields
include `dpi_gear`, `dpi_x`, `dpi_y`, `config`. AD-6 forces every write to be
verified "by immediate re-read." But two *different push sources* feed the same
fields: the passive report 7 (device-initiated, async, can lag the write) and the
write-verify re-read (worker-initiated, fresh). AD-4 assigns both to the worker
but gives **no precedence, no generation counter, no retention rule**.

- **Unit A (report wins):** report 7 is ground truth; a stale report 7 (old gear)
  that lands after the successful write overwrites the fresh value. The tray
  shows "5000 DPI" for minutes after a successful switch to 1200.
- **Unit B (command wins):** the most recent command result wins and report-7
  updates for that field are ignored until a *newer* report arrives. Tray shows
  1200 immediately — but B also ignores a genuine device-side gear change made via
  the physical DPI buttons (see Deferred "DPI physical-button behavior") if the
  same rule applies, so B can show a value the device disagrees with.

Both are legitimate readings of AD-4 ("consumers render the latest snapshot") +
AD-6 ("verify by re-read"). The user-visible DPI after a change is unbound by the
spine. `mode` is worse: the brownfield sets it from the *prefix* on a 0xAA reply
(`_query_battery`) and from report-7 `data[1]` otherwise — two sources for one
field, already conflated, and the spine ratifies the conflation (see Finding 6).

**Hole:** AD-4 names the fields but not their **sources, precedence, or stale
values on transition**; AD-6's verify-re-read implicitly creates a second writer
to the same fields with no arbitration.

**Fix (AD-4 tightening):** every snapshot field gets a declared **source
(report-7 offset / command-reply offset / derived)** and a **precedence** rule —
"a write-verify re-read supersedes report-7 data for that field until the next
report 7 with a different value is observed" — plus a **retention rule** on state
transition (e.g., `asleep=True` retains the last-known battery/DPI rather than
nulling them). Encode this as an explicit table in AD-4, not prose.

---

### Finding 5 — AD-1 × AD-6 × AD-3 contradiction: `settings.py` cannot both enforce the golden rule and be a pure core module (layering contradiction)

The spine draws `settings.py --> device.py` (mermaid) and AD-1 mandates strict
downward dependency (presentation → session/settings → device/protocol). AD-6
says settings enforces the golden rule and "every write goes through it."
AD-3/AD-9 say the worker is the *only* fd owner and the *only* place device I/O
happens. These three cannot all be literally true: a golden-rule write is a
read→modify→write→re-read *sequence of device I/O*, which cannot live in
`settings.py` (no fd, no queue access from core downward without reaching *up*).

- **Unit A (settings = pure metadata):** `settings.py` exports `Field(addr, size,
  type, range, validator)` plus encode/decode; it imports nothing from `device`.
  The worker (`session.py`) executes the golden-rule sequence using `Field`
  metadata. "Every write goes through settings" reads as "every write is built
  from a settings `Field`."
- **Unit B (settings = orchestrator):** `settings.py` imports `RapooDevice`,
  opens its own device inside `Field.write()`, and performs read→write→re-read
  itself. Unit B *also* "goes through settings," *also* "enforces the golden
  rule," and Unit A literally violates nothing in AD-6 as written — yet B opens a
  second fd (contra AD-3/AD-9 intent), bypasses the worker's queue (contra AD-3),
  and violates AD-1's direction of dependency.

This is the single most dangerous ambiguity for Phase 0, because B *looks*
right per AD-6 and wrong per AD-3, and nothing in the spine says which reading
wins.

**Fix (AD-6 rewrite):** split the concern. AD-6a — `settings.py` is a **pure
registry + codec**, no I/O, no `device` import, the single source of
addr/size/type/range/validator and baseline-format knowledge. AD-6b — the
**worker is the only executor** of the golden rule (baseline existence check →
write → re-read), operating on `Field` metadata through the command queue
(which makes the whole read-modify-write one **atomic queue entry**, killing the
Finding-1 interleave as well). Add the mermaid edge `session --> settings`
(presentation→core) and remove the `settings --> device` edge.

---

### Finding 6 — Snapshot field semantics are ambiguous enough for two incompatible parsers (AD-4)

AD-4's field list reads like a contract but three fields have two readings each:

- `mode`: (a) connection type 0/1/2 (report-7 `data[1]` low nibble, drives the
  tray "2.4G/Bluetooth/USB" label) **or** (b) the 0xA2 `get_work_mode` value
  (raw `data[2]`, observed `0x11`). The brownfield already *conflates* these two
  distinct quantities under one name — `_query_battery` writes connection mode
  from the prefix, `_handle_report` writes it from `data[1]`, and `get_work_mode`
  (a different sensor/performance-mode concept) is probed but never surfaced.
  The spine ratifies one `mode` field for both.
- `rpt_24g`/`rpt_usb`: (a) raw index (the passive-report value, Hz map deferred
  to Phase 3) or (b) Hz, converted at push time. If B converts and the deferred
  "polling index→Hz map" later turns out non-linear, B's stored snapshot is
  wrong *forever*, while A keeps the raw truth.
- `config`: the report-7 `data[12]` byte verbatim, or a parsed struct, or an
  opaque "current settings blob."

- **Unit A** parses `mode` as connection type and stashes 0xA2 under `config`;
- **Unit B** parses `mode` as the 0xA2 value and derives connection type from
  `rpt_usb`/prefix.

Both match AD-4's word list. The tray's mode label, the DPI dialogs' gear
display, and the Phase-3 cross-validation ("does report 7 mirror EEPROM?") all
depend on this choice.

**Fix (AD-4):** add a **field-semantics table** — name, raw source (report-7
offset or command-reply offset), type, allowed range, unit (raw index vs
derived), and a note that snapshot fields carry **raw device values** (indexes/
offsets) with all presentation mapping (Hz, labels) in the GUI layer. Split
`mode` into `connect_mode` (0/1/2, from report 7) and `work_mode` (raw 0xA2),
or state explicitly which one `mode` is and rename the other. Do this now —
it is a ratify-vs-fix moment the spine already owns.

---

## Part B — Feature-altitude coverage audit

| Dimension the feature owns | Covered by | Gap |
|---|---|---|
| **State** | AD-4 snapshot | Field sources/precedence/retention unspecified (Finding 4); `mode`/`config`/`rpt_*` semantics ambiguous (Finding 6) |
| **Errors** | AD-8 typed exceptions → states | No transition *table*; state set misses `reconnecting`/`rescanning`; empty `06 00` report is "ignored" by AD-2, so sleep can only be detected by slow timeout — the fast empty-report path the brownfield *could* use is preempted (Finding 2); future lifecycle uncancelled/unbounded (Finding 2) |
| **Threading** | AD-5 | `config.py`'s `save_language` is a synchronous file write on the GUI thread today, and two threads (GUI + worker) will both want to write `config.json` once baseline path is persisted (Finding 7) |
| **Config persistence** | Consistency table only (path) | No AD binds *who* owns `config.json`, read-modify-write atomicity, or a **shared baseline path** constant. `save_language` rewrites the file with only the `language` key, clobbering any second key (Finding 7) |
| **Diagnostics** | AD-9 (probe separate process) | `probe.py --dump` writes the baseline the app's golden rule requires; the baseline *location* is not a shared constant (FEATURES.md says `~/.cache/rapoo-vt7/`, AD-6 doesn't name it) — two units can check a different file and silently disagree on "baseline exists" (Finding 7) |
| **Deployment/ops envelope** | Stack table (udev, versions) | Autostart + `--hidden` + GApplication single-instance is named in the seed but bound by no AD; the single-instance guarantee is the *only* thing that prevents a second fd from another process — worth one sentence as an AD so a story can't drop it. No logging facility for a daemon whose stdout is `/dev/null` (autostart); `main.py` today prints state to stdout |

## Part C — Deferred items that can still let units diverge

- **"EEPROM field formats (1B vs 2B LE)" → Phase 1 story S3.** Safe *only*
  because AD-6's registry carries per-field `size` as data. Reinforce: the
  registry must store raw bytes + `size`/`type` attributes and per-field
  decode, so a format correction is a **data edit, not a code change** — then
  this deferral is truly harmless. Add one sentence to AD-6.
- **"Polling index→Hz map" → Phase 3.** Safe only if snapshots carry raw
  indexes (Finding 6, (b) reading). Bind it: "snapshot stores raw values;
  mapping lives in presentation."
- **"DPI physical-button behavior" (device-side gear switching).** Not a
  two-unit divergence if AD-4's precedence rule says "device-side change via
  report 7 beats a stale command-derived value" — the finding-4 precedence rule
  and this deferral are the same axis; decide them together.
- **Button-remap function codes, packaging, macros, firmware update.** Genuinely
  story/product-level; no architecture dependency found.

## Part D — Ratification vs. contradiction of the brownfield

**Ratified correctly** (verified against source): protocol.py holds wire
constants only; device.py is the sole hidraw syscall site (os.open/write/read,
ioctl, select); BatteryMonitor is a daemon thread pushing via on_update/on_state;
GUI consumes through GLib.idle_add; states connected/asleep/disconnected/error;
tests via FakeDev/FakeClock/Collector injection; i18n LANGS pt_BR/en/es;
pycairo absolute PNG path via set_icon_full; config.json path; udev both PIDs;
GTK3 stack versions.

**Contradictions or inherited conflicts the spine should either fix or
explicitly ratify:**

1. **`device.query` auto-retry replay** — brownfield behavior that Finding 3
   must neutralize *by name*, or the worker silently inherits double-write risk.
2. **`mode` conflation** (0xA2 work mode vs report-7 connection mode) — the
   brownfield's own wart, ratified verbatim by AD-4. The spine is the right
   altitude to split it (Finding 6).
3. **Icon filename derivation is duplicated** — `tray.py:61` builds the PNG name
   inline (`ICON_PREFIX{percent:03d}_chg`) and `icons.py:21` owns `icon_name`/
   `UNKNOWN_NAME`. Two sources of truth today; AD-7 should bind "icons.py is the
   only owner of icon name derivation." Low risk, cheap to close.
4. **`config.py` clobber** — `save_language` writes `{"language": lang}`,
   dropping every other key. The moment Phase 0 persists a second key, units
   clobber each other (Finding 7). The spine's Consistency table ratifies the
   path but not a write strategy.
5. **`battery.py` → `session.py` migration is implied, not stated.** The seed
   says "evolves battery.py" but nothing binds the migration boundary (does the
   quiet-listen/sleep FSM move verbatim, or does the new command queue change
   it?). AD-8's listen-only discipline implies it moves; state it so a story
   can't drop the 60 s quiet-reopen behavior that P2/P7 depend on.

## Part E — Recommended spine edits (priority order)

1. **AD-2/AD-3 (new clause): command lifecycle.** Exactly one command in flight;
   FIFO queue; ACK with no pending command dropped+counted, never buffered;
   futures resolve exactly once (success / CommandTimeout / Cancelled / DeviceGone);
   timed-out ACKs never complete a future.
2. **AD-8 (new clause): user-command-while-asleep.** Queue but don't send while
   asleep; drain FIFO on wake; empty `06 00` report is a **sleep signal routed to
   the state machine** (fast path), not "ignored" by AD-2; pending user command
   surfaces as non-blocking "pending — move the mouse."
3. **AD-6 (rewrite): pure registry vs. executor split.** `settings.py` is pure
   metadata+codec (no device import, no I/O); the worker is the sole golden-rule
   executor; read-modify-write is one atomic queue entry; registry stores
   raw bytes + size/type so Phase-1 format fixes are data edits. Fix the mermaid
   edge `settings --> device`.
4. **AD-4 (new table): field semantics.** Source (report-7 offset / reply offset /
   derived), type, range, raw-not-derived storage, precedence (write-verify
   re-read beats report 7 until a newer report 7), retention on asleep/
   disconnected, and split `mode` → `connect_mode` + `work_mode`.
5. **AD-3 (clause): hot-swap.** Worker owns interface switching; transport
   auto-retry retired; a command spanning an interface switch is **not replayed**;
   resolves typed with reason.
6. **New/ratified: config ownership.** One owner of `config.json` (single
   read-modify-write with atomic replace; never clobber non-language keys) and a
   **shared baseline-path constant** consumed by both `probe.py --dump` and the
   worker's golden-rule check. Optionally one sentence ratifying single-instance
   + `--hidden` + autostart as the ops envelope.

With edits 1–6 the spine becomes build-substrate: two independent one-level-down
units converge on the same wire discipline, the same snapshot contract, the same
write path, and the same baseline file.

---

*Review complete. Summary returned to the orchestrator separately.*

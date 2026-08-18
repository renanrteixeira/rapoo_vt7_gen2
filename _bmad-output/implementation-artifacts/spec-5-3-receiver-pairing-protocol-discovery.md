---
title: 'Receiver pairing protocol discovery (5-3)'
type: 'feature'
created: '08-16-2026'
status: 'done'
review_loop_iteration: 1
baseline_commit: 'f9643574ba9ccd47ff704bcde9b8b934e7b9eace'
context: ['docs/FEATURES.md', 'docs/index-B0XNTd12.js', 'docs/BaseSetting-CsajUb0l.js', 'docs/rapoo_hub_app.js']
---

## Intent

**Problem:** The A Hub's receiver-pairing flow (`deviceMatcher`) is unmapped — commands marked ⚠️ in FEATURES.md:134. Story 5-4 (guided pairing UI) is gated on this discovery; nothing may ship in a picker or write path before the commands are reverse-mapped and validated.

**Approach:** Reverse-map the pairing commands from the A Hub chunks `index-B0XNTd12.js` (device-matcher route) and `BaseSetting-CsajUb0l.js` (connected-mouse poll) — present at `https://hub.rapoo.cn/assets/` and copied to `docs/` (re-fetched 2026-08-16 after the `/tmp` copy was lost to a reboot) — encode the command table in `protocol.py`, ship a probe-only discovery harness (`--pair-discover`) plus headless tests. On-device validation of the read-only probes belongs to **this story** (Ask First for the destructive commands); no app write path and no UI.

## Boundaries & Constraints

**Always:**
- Commands extracted 2026-08-16 from `docs/index-B0XNTd12.js` (`sendRaw` to the receiver; wire form decided D3a — `pairing_commands()` builds **full frames** `[prefix, cmdId, ...args]`):
  - `sendStartMatch` → payload `[0xA0, 0x81]` → frame `[0xA5, 0xA0, 0x81]` (enter pairing mode)
  - `sendWriteRF` → payload `[0xA1, 0x8F, rf0, rf1, rf2, rf3]` → frame `[0xA5, 0xA1, 0x8F, rf0..rf3]`; RF bytes generated via `os.urandom(4)` when no explicit bytes are supplied (ECH-6)
  - `sendGetMatchResult` → payload `[0xA7]` → frame `[0xA5, 0xA7]`; WebHID reply byte 1 (= hidraw `data[2]`): `0` = failed; non-zero values are 🔶 unvalidated — dump raw, do not interpret (BH-5/ECH-4)
- Connected-mouse poll **confirmed** from `docs/BaseSetting-CsajUb0l.js`: `getConnectedMouseVid` = `read_eeprom` `[0xA5, 0xA4, 2, 0x00, 0x00]` (addr 0x0000, 2 B LE); `getConnectedMousePid` = `[0xA5, 0xA4, 2, 0x04, 0x00]` (addr 0x0004); decode 2 B LE from WebHID bytes 4-5 = raw `data[5]` (existing `EEPROM_DATA_OFFSET`); non-zero = mouse attached
- Report-7 sub-commands **confirmed** in `docs/rapoo_hub_app.js` (`VTnrf54LBaseParser`, byte ~291387): `0xB0`(176) = base data report, `0xB1`(177) = pairing success (VID check `0x24AE`), `0xB3`(179) = disconnect. **Decision D4b:** this story only dumps raw report 7; recognizing/decoding 0xB1 stays in Story 5-4.
- CmdIds `0xA0`/`0xA1`/`0xA7` are in the free 0xA0–0xAF range (protocol.py:21-27); declare as constants.
- Discovery deliverable is 🔶 (static-only) in FEATURES.md; flip to ✅ only after the on-device validation performed in this story (Ask First gate for destructive commands). No write path and no UI in this story.
- **Receiver selection (decision D1a):** `device.py` gains a way to open **only the receiver** (prefix `0xA5`) — e.g. `open(prefix=None)` that filters `_scan()` candidates to the requested prefix and raises `DeviceNotFound` if none matches. `--pair-discover` must use it; `device.open()` default behavior is unchanged (still prefers the USB-cable mouse).
- `tools/probe.py --pair-discover` opens the receiver interface, runs only safe/read-only probes (connected-mouse VID/PID poll, optional `0xA7` result read behind an explicit flag) and dumps raw report 6/7 replies for hex inspection. It must NOT fire `0xA0`/`0xA1` (destructive — changes receiver pairing state) unless an explicit flag + user confirmation (Ask First).
- **Reply-shape guard (BH-3/ECH-1):** every VID/PID and 0xA7 decode must first validate `data[1] == RESP_ACK` **and** minimum length (`len >= EEPROM_DATA_OFFSET + 2`) before slicing; non-ACK/short replies decode to "none attached"/"no result" — never IndexError, never garbage.
- **Destructive-flag safety (ECH-7):** when stdin is not a TTY, destructive flags are refused outright (no prompt, no hang). Confirmation prompt only on a real TTY.
- Follow the module pattern: constants in `protocol.py`, discovery logic + typed errors in a `pairing.py` module (mirror `system.py`), probe subcommand in `tools/probe.py`, headless tests with FakeDev.

**Ask First:**
- Do NOT send the destructive `0xA0` (start match) / `0xA1` (write RF) during automated verification — they alter receiver pairing state on hardware. A human must run them on a real device and confirm. This on-device validation is part of **this** story (D2a), gated by explicit human consent.
- If `--pair-discover` on real hardware shows a reply shape differing from the WebHID parser expectation (e.g. non-ACK on input report 6), HALT and reconcile against the A Hub rather than guessing.

**Never:**
- No pairing UI, no app write path, no `submit(wake=True)` pairing action (that's Story 5-4).
- No guessing at unverified reply offsets — any parser helper must mark the reply shape as unvalidated (🔶) until on-device.
- No EEPROM baseline writes; `--pair-discover` only reads.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| DISCOVER_HAPPY | receiver connected, `--pair-discover` | dumps connected-mouse VID/PID + raw reports over a fixed listen window (e.g. 6 s); prints the 3-step pairing flow; exit 0 | N/A |
| DISCOVER_NO_DEVICE | no receiver/device (no `0xA5` candidate) | clear error naming the missing interface, exit non-zero | no crash |
| DISCOVER_WRONG_IFACE | only USB-cable mouse present, no receiver | clear "receiver not found" error, exit non-zero (never reads the mouse) | no crash |
| DISCOVER_PARTIAL | one probe times out, others succeed | marks the dump "partial", exits non-zero | no silent success |
| DISCOVER_ASLEEP | receiver present, empty replies | prints raw empty reports, notes "asleep" | non-fatal |
| DESTRUCTIVE_GUARD | `--start-match`/`--write-rf` passed | refused (exit non-zero) unless `--i-understand-risks` + TTY confirmation; non-TTY stdin → auto-refuse | Ask First |
| VID_PID_DECODE | readback 2 B LE `24ae`/`4613`, ACK + length valid | decodes to hex string | non-ACK/short → "none attached" |

## Code Map

- `src/rapoo_vt7/protocol.py` -- add `PAIR_START_MATCH=0xA0`, `PAIR_WRITE_RF=0xA1`, `PAIR_GET_RESULT=0xA7`, sub-args `0x81`/`0x8F`, poll addrs `0x0000`/`0x0004` (near line 27). Reuse `READ_EEPROM` (0xA4) for the poll.
- `src/rapoo_vt7/device.py` -- add receiver-only selection: `open(prefix=None)` filters `_scan()` candidates by prefix and raises `DeviceNotFound` if none matches (D1a). Reuse `read_eeprom` (:231), `read_report` (:185). Default `open()` unchanged.
- `src/rapoo_vt7/pairing.py` -- NEW: `PAIRING_FLOW` reference dict, `pairing_commands()` builder returning **full frames** `[prefix, cmdId, ...args]` (D3a; RF bytes `os.urandom(4)` by default), `decode_connected_vid_pid(dev)` (read_eeprom 0x0000/0x0004 → hex, ACK+length guarded), typed `PairingDiscoveryError(ValueError)`; mirrors `system.py` `_read`/typed-error pattern.
- `tools/probe.py` -- add `--pair-discover` (opens receiver via `open(prefix=0xA5)`, safe probes, prints hex + the 3-step flow, fixed listen window, partial-dump handling) + gated destructive flags (TTY confirmation, auto-refuse non-TTY); mirror `status_main` (:428).
- `docs/FEATURES.md` -- §E pairing row (:134) becomes 🔶 + command reference table + "on-device validation pending (this story, Ask First)".
- `tests/test_pairing.py` -- NEW: constants, `pairing_commands` full-frame bytes, `decode_connected_vid_pid` (FakeDev), probe output headless (FakeDev per test_probe.py:17-49), destructive flags refused, reply-shape guards.
- `tests/test_probe.py` -- extend with headless `--pair-discover` cases.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/protocol.py` -- add `PAIR_*` constants + poll addresses -- wire constants in free range
- [x] `src/rapoo_vt7/device.py` -- `open(prefix=None)` receiver-only selection -- D1a
- [x] `src/rapoo_vt7/pairing.py` -- new module: reference flow, full-frame command builder, `decode_connected_vid_pid`, typed error, reply-shape guards -- discovery logic (read-only)
- [x] `tools/probe.py` -- `--pair-discover` subcommand (receiver open, safe reads + hex dump, 3-step print, partial handling, non-TTY-safe destructive flags) -- diagnostics harness
- [x] `docs/FEATURES.md` -- §E pairing row 🔶 + command reference + pending-validation note -- tracking
- [x] `tests/test_pairing.py` -- constants/commands/decode/probe/gate/guard tests with FakeDev -- coverage (I/O matrix + AC)
- [x] `tests/test_probe.py` -- headless `--pair-discover` cases -- coverage

**Acceptance Criteria:**
- Given the repo, `protocol.py` declares `PAIR_*` constants (`0xA0/0xA1/0xA7`, sub `0x81/0x8F`, poll addresses 0x0000/0x0004).
- Given a FakeDev receiver, `pairing_commands()` returns full frames `[0xA5, 0xA0, 0x81]`, `[0xA5, 0xA1, 0x8F, ...]`, `[0xA5, 0xA7]` matching the bundle payloads + prefix.
- Given a FakeDev receiver, `--pair-discover` prints connected-mouse VID/PID and raw reports without sending `0xA0`/`0xA1`; exit 0.
- Given `--pair-discover` with the receiver absent but a USB-cable mouse present, it reports "receiver not found" and exits non-zero without reading the mouse.
- Given `--pair-discover` without explicit confirmation for destructive flags (or non-TTY stdin), no `0xA0`/`0xA1` write is attempted and refusal exits non-zero.
- Given a short/non-ACK EEPROM reply, `decode_connected_vid_pid` returns "none attached" without raising.
- Given the full suite, all existing + new tests pass (392 baseline + new).
- Given FEATURES.md, the pairing row is 🔶 with the command reference and an explicit "on-device validation pending (this story, Ask First)" note; no write path or UI was added.

### Review Findings

1. - [x] [Review][Decision] Receiver-interface selection unspecified — **resolved D1a:** `device.py` gains `open(prefix=None)` receiver-only selection; `--pair-discover` opens the receiver; AC added.
2. - [x] [Review][Decision] On-device validation gate contradicts the epic — **resolved D2a:** on-device validation of read-only probes belongs to this story; destructive commands stay Ask First; FEATURES/AC wording updated (no more "Story 12 gate").
3. - [x] [Review][Decision] Matcher command wire form ambiguous vs "CONFIRMED" — **resolved D3a:** `pairing_commands()` builds full frames `[0xA5, cmdId, ...]`; AC verifies the full frames.
4. - [x] [Review][Decision] Report-7 0xB1 pairing-success recognition unplanned — **resolved D4b:** this story dumps raw report 7 only; 0xB1 decode stays in Story 5-4.
5. - [x] [Review][Patch] Reply-shape guard before VID/PID decode — ACK + min-length guard added to `decode_connected_vid_pid`; AC + I/O row added.
6. - [x] [Review][Patch] 0xA7 result semantics incomplete — non-zero values marked 🔶, dump raw, no interpretation.
7. - [x] [Review][Patch] RF-byte source + CLI contract for `--write-rf` — `os.urandom(4)` default in builder; destructive flag requires explicit bytes otherwise.
8. - [x] [Review][Patch] Partial probe read exits 0 — DISCOVER_PARTIAL row: partial marked + non-zero exit.
9. - [x] [Review][Patch] Non-TTY stdin hang — auto-refuse destructive flags when stdin is not a TTY.
10. - [x] [Review][Patch] Physical pairing steps not surfaced — probe prints the 3-step flow during discovery.
11. - [x] [Review][Patch] Builder output not gated by AC — AC for full-frame bytes added.
12. - [x] [Review][Patch] Listen-termination under-specified — fixed listen window (6 s) added to DISCOVER_HAPPY.
13. - [x] [Review][Patch] `--pair-discover` opens receiver, no 0xA7 firing condition — optional `0xA7` behind an explicit flag.
14. - [x] [Review][Patch] DESTRUCTIVE_GUARD exit code undefined — refusal exits non-zero (I/O row).
15. - [x] [Review][Patch] §E "stays 🔶" wording slip — "becomes 🔶" + pending-validation note corrected.
16. - [x] [Review][Patch] Timeline inconsistency — `created` aligned to 08-16-2026 (re-fetch date); command confirmations dated 2026-08-16.
17. - [x] [Review][Patch] Empty `context: []` frontmatter — deps listed in frontmatter context.
18. - [x] [Review][Patch] Bundle locators incomplete — byte locator added for `rapoo_hub_app.js` (~291387); chunk function names referenced.

**Post-merge code review (2026-08-17):**

- [x] [Review][Patch] Zero-valued VID/PID decodes to "0000" instead of "none attached" — `decode_connected_vid_pid` maps only `None` to "none attached"; a valid ACK with value 0 renders `"0000"`, contradicting the protocol comment "non-zero = attached" (a receiver with no mouse reads 0). `pairing.py:131-132`
- [x] [Review][Patch] Destructive 0xA0/0xA1 no-reply marks the run partial and exits 1 — the replies are feature-report-only (unreadable on hidraw input 6), so a successful on-device destructive discovery always reports failure. No-reply for these commands is the expected outcome; the pairing result arrives via report 7. `probe.py:605-610`
- [x] [Review][Patch] `test_pairing.py` main-dispatch tests duplicated in `test_probe.py` — `PairDiscoverMainDispatchTest` (test_pairing.py:437) and `PairDiscoverMainTest` (test_probe.py:565) both cover `--pair-discover` flag dispatch, refusal and dump-mutual-exclusion. `test_pairing.py:437`, `test_probe.py:565`
- [x] [Review][Patch] 0xA7 reply-byte offset not pinned by a distinguishing fixture — `test_want_result_prints_raw_and_reply_byte` uses an all-zero reply (offset 2 == offset 3), so a wrong slice index would still pass. `test_pairing.py:290-306`
- [x] [Review][Patch] Dispatch tests hardcode `window=6.0` via `main()` — `test_main_pair_discover_flag_runs_discovery` and `test_main_pair_discover_confirmed_runs_destructive` each spin a full 6 s listen loop (~12 s of the suite). `probe.py:763`
- [x] [Review][Patch] `pairing_commands()["get_result"]` never consumed — the probe queries 0xA7 directly (`dev.query(PAIR_GET_RESULT)`) instead of using the builder's `get_result` frame, leaving that frame only unit-tested. `probe.py:579`
- [x] [Review][Patch] OSError branch on VID/PID read has no test — `except OSError` at the connected-mouse poll prints "read failed" and marks partial; no test covers `read_eeprom` raising OSError. `probe.py:565-570`
- [x] [Review][Patch] Listen-window header says "move the mouse" but the pairing action is "press L+M+R" — the printed instruction contradicts the 3-step flow printed above. `probe.py:613`
- [x] [Review][Patch] RF bytes sent are never echoed — the destructive write_rf path prints only the reply, so the operator cannot see which RF was written. `probe.py:592-612`
- [x] [Review][Patch] Stale "345 baseline + new" in spec AC/Verification — current suite is 392 tests. `spec-5-3` AC line 83 / Verification line 118
- [x] [Review][Patch] protocol.py comment "unused 0xA0-0xAF slots" is inaccurate — 0xA2/0xA3/0xA4/0xA5/0xA8/0xAA/0xAD are already used; only 0xA0/0xA1/0xA7 were free. `protocol.py:29`
- [x] [Review][Patch] CONTEXT.md:104 "ACK no input 6" is contradictory wording — the reply IS an ACK on input 6 (`06 01 …`); should read "ACK on input 6" to match FEATURES.md and the observed bytes. `CONTEXT.md:104`
- [x] [Review][Defer] `device.py` `find_path` vs `open(prefix)` divergence — `find_path()` is unfiltered while `open(prefix)` filters by prefix; pre-existing entry point used by the battery hot-swap reconnect, not introduced by this story. `device.py:105-121`

## Spec Change Log

_Empty until the first bad_spec loopback._

## Design Notes

Commands extracted from `docs/index-B0XNTd12.js` (`sendStartMatch=[160,129]`, `sendWriteRF=[161,143,...4 bytes]`, `sendGetMatchResult=[167]`, result = WebHID reply byte 1 → hidraw `data[2]`; wire form = full frames `[0xA5, cmdId, ...]` per D3a) and `docs/BaseSetting-CsajUb0l.js` (`getConnectedMouseVid` = `[165,164,2,0,0]`, `getConnectedMousePid` = `[165,164,2,4,0]`, 2 B LE at WebHID bytes 4-5 = raw `data[5]`). Report-7 sub-commands 0xB0/0xB1/0xB3 confirmed in `docs/rapoo_hub_app.js` (`VTnrf54LBaseParser`, byte ~291387; 0xB1 decode deferred to Story 5-4 per D4b). The 3-step physical flow (receiver + wired mouse → disconnect + power-cycle → L+M+R 3 s) comes from the locale strings. `sendRaw` in WebHID maps to our input-report-6 reply channel; whether the reply is an ACK (`06 01 …`) or raw bytes is unvalidated on hidraw → 🔶, destructive commands never auto-fired. On-device validation of the read-only probes happens in this story (D2a); the 🔶→✅ flip in FEATURES.md follows it.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- all pass (392 tests)
- `python3 -m compileall -q src/ tools/` -- no errors
- `python3 tools/probe.py --pair-discover` (with real receiver, cable unplugged) -- opens the receiver, prints VID/PID + raw reports + 3-step flow; exit 0; NEVER fires 0xA0/0xA1 without the gated flag

**Manual checks (if no CLI):**
- Inspect `docs/FEATURES.md` §E: pairing row 🔶 with the 3 commands + poll addresses and the pending-validation (this story) note.

## Suggested Review Order

**Receiver-only selection (safety boundary)**

- The receiver-only `open(prefix=...)` filter: `--pair-discover` must never touch the cable mouse
  [`device.py:112`](../../src/rapoo_vt7/device.py#L112)

- Filter behavior pinned by real-`_scan`-stub tests (receiver select / missing raise / default ordering)
  [`test_device.py:257`](../../tests/test_device.py#L257)

**Command encoding (protocol constants + frame builder)**

- `PAIR_*` constants and connected-mouse poll addresses in the free 0xA0–0xAF slots
  [`protocol.py:33`](../../src/rapoo_vt7/protocol.py#L33)

- Full-frame builder (decision D3a: `[0xA5, cmdId, ...]`), `os.urandom(4)` RF default + type check
  [`pairing.py:61`](../../src/rapoo_vt7/pairing.py#L61)

- Reply-shape guard + `"none attached"` fallback for the VID/PID decode
  [`pairing.py:97`](../../src/rapoo_vt7/pairing.py#L97)

**Discovery harness (probe CLI)**

- Ask First gate: non-TTY auto-refuse, EOF-safe prompt, `--write-rf` hex/length validation
  [`probe.py:470`](../../tools/probe.py#L470)

- `pair_discover_main`: 3-step flow first, VID/PID poll, optional 0xA7, gated destructive, partial handling
  [`probe.py:525`](../../tools/probe.py#L525)

- `main()` dispatch: `--pair-discover` mutually exclusive with dump, modifiers require the flag
  [`probe.py:691`](../../tools/probe.py#L691)

**Coverage (I/O matrix + regression)**

- Constants / frames / decode / gate / partial / dispatch headless tests
  [`test_pairing.py:61`](../../tests/test_pairing.py#L61)

- Deduped `--pair-discover` main-dispatch cases incl. flow-before-listen ordering
  [`test_probe.py:565`](../../tests/test_probe.py#L565)

**Docs/tracking**

- FEATURES.md §E: 🔶 pairing row + full-frame command reference + pending-validation note
  [`FEATURES.md:134`](../../docs/FEATURES.md#L134)

- CONTEXT.md resume manual: command table + B5 receiver-pairing discovery note
  [`CONTEXT.md:92`](../../CONTEXT.md#L92)
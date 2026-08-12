---
title: '1-1 EEPROM write + verify'
type: 'feature'
created: '2026-08-10'
status: 'done'
baseline_commit: 'NO_VCS'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The app can read EEPROM (`read_eeprom`, 0xA4) but has no write path, so no later phase (DPI, parameters, remap, system) can change device settings.

**Approach:** Add `write_eeprom` (command 0xA5) to `device.py` as a one-shot, single-execution write that returns on the input-6 ACK, plus a `write_eeprom_verify` composition that writes then re-reads and compares the bytes. Unit tests cover both.

## Boundaries & Constraints

**Always:**
- Write payload is output report 6: `[prefix, 0xA5, len, addr_lo, addr_hi, 0x00, 0x00, data…]` — address padded to 4 bytes (matches the A Hub `sa` wrapper); `len` = `len(data)`, max 24 bytes.
- **Single execution, no replay.** Do NOT call `device.query()` for writes — its timeout path replays the command across an interface switch, which would double-write EEPROM. Use `send_command` + `read_response` directly.
- Verify ACK on the input-6 reply: `data[1] == RESP_ACK` (handled by `read_response`).
- Re-read comparison uses the existing `EEPROM_DATA_OFFSET` (5) on the raw reply.
- New unit tests live in a new `tests/test_device.py`; run `python3 -m unittest discover -s tests`.
- All new strings in English (internal errors, like the existing `read_eeprom` ValueError); no new i18n keys needed.

**Ask First:**
- If a real-device write test is requested before the S2 baseline exists (`~/.cache/rapoo-vt7/eeprom_baseline.json`), HALT — the golden rule forbids it.

**Never:**
- No replay across interface switch; no auto-retry after a partial write.
- No changes to `battery.py`/session behavior, GUI, or `probe.py` in this story.
- No writes on the real device outside a verified reversible field after the S2 baseline exists.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Write happy path | awake device, 2-byte LE addr, data ≤ 24 B | write sent; returns after ACK (`06 01 …`) | n/a |
| Oversize data | data > 24 B | nothing sent | `ValueError("write_eeprom: data length max 24")` |
| No ACK / asleep | empty `06 00` reply or timeout | no retry, no interface switch | `CommandTimeout` |
| Verify match | re-read at offset 5 equals written bytes | returns the read-back bytes | n/a |
| Verify mismatch | re-read differs from written bytes | write already applied | `ValueError` on mismatch |

</frozen-after-approval>

## Code Map

- `src/rapoo_vt7/device.py` -- transport; pattern anchors: `send_command` (L160, builds `[REPORT_CMD, prefix, cmd_id, …args]`), `read_response` (L189, waits for input-6 ACK), `read_eeprom` (L231, ValueError guard + `query`). Add `write_eeprom` + `write_eeprom_verify` here.
- `src/rapoo_vt7/protocol.py` -- `WRITE_EEPROM = 0xA5` (L24) already defined; `REPORT_CMD`/`RESP_ACK`/`EEPROM_DATA_OFFSET` (L56) already defined. No changes expected.
- `docs/rapoo_hub_app.js` -- A Hub `sa` wrapper (write_eeprom): payload `[len, ...addr, ...data]` with `addr` zero-padded to 4 bytes; rejects `r.length > 24`; ACK check is byte 0 == 1 on the WebHID payload (= `data[1]` on hidraw). Reference, not modified.
- `tests/test_battery.py` -- existing FakeDev/Collector injection pattern for reference; device-level tests need os-level mocking instead (see below), so they go in a new file.
- `tests/test_device.py` -- new; mock `device.os.write/read` and `device.select.select`; drive `RapooDevice` with `_fd` set to a sentinel.

## Tasks & Acceptance

**Execution:**
- [x] `src/rapoo_vt7/device.py` -- add `write_eeprom(addr, data)`: guard `len(data) > 24` → `ValueError`; build args `bytes([len(data)]) + bytes(addr[:2]) + b"\x00\x00" + bytes(data)` for `send_command` (the cmd id is prepended by `send_command` itself, do NOT include it in args); `read_response(WRITE_EEPROM)` with timeout; `None` → `CommandTimeout`; return the raw reply.
- [x] `src/rapoo_vt7/device.py` -- add `write_eeprom_verify(addr, data)`: call `write_eeprom`, then `read_eeprom(addr, len(data))`; extract `resp[EEPROM_DATA_OFFSET : EEPROM_DATA_OFFSET + len(data)]`; mismatch → `ValueError`; return the read-back bytes.
- [x] `tests/test_device.py` -- new file: FakeFD + `mock.patch` on `device.os.write/read` and `device.select.select`; cover the I/O matrix (happy write ACK, oversize guard, no-ACK → `CommandTimeout` with zero retries, verify match, verify mismatch), plus asserting the exact bytes written (`[6, prefix, 0xA5, len, lo, hi, 0, 0, …data]`).

**Acceptance Criteria:**
- Given a connected awake device, when `write_eeprom(addr, data)` runs, then exactly one output report `06 A5 …` is written and the method returns the ACK reply.
- Given `len(data) > 24`, when `write_eeprom` runs, then `ValueError` is raised and nothing is written.
- Given the device sleeps mid-write, when `write_eeprom` runs, then `CommandTimeout` is raised and the command is never re-sent or replayed on another interface.
- Given a successful write, when `write_eeprom_verify(addr, data)` runs, then the re-read bytes equal `data`; otherwise `ValueError` is raised.
- Given the test suite, when `python3 -m unittest discover -s tests` runs, then all tests pass.

## Spec Change Log

- `2026-08-10` — Implementer deviation, accepted: the original Execution bullet included `WRITE_EEPROM` in the `send_command` args, but `send_command` already prepends the cmd id (payload `[REPORT_CMD, prefix, cmd_id, …args]`), which would have produced a double command byte `06 A5 A5 …`. Amended the bullet to `bytes([len(data)]) + bytes(addr[:2]) + b"\x00\x00" + bytes(data)` and added an exact-bytes assertion. This avoids a broken wire format; the frozen wire layout `06 A5 len addr4 data` (A Hub `sa` wrapper) is authoritative and was satisfied. KEEP: exact-written-bytes assertion in tests; do not re-derive `write_eeprom` args with the cmd id included.

## Design Notes

`device.query()` must not be reused for writes: on `CommandTimeout` it switches interface and re-sends, which for a write is a double-write hazard (AD-3). `write_eeprom` therefore pairs `send_command` + `read_response` directly — one send, one ACK wait, no replay. The policy layer (baseline gate, queueing while asleep) stays worker-side (AD-6/AD-8) and is out of scope here; this story only adds the transport primitive and its read-back composition.

## Verification

**Commands:**
- `python3 -m unittest discover -s tests` -- expected: all tests pass (existing + new `test_device.py`).

## Suggested Review Order

**Write path design**

- Entry point: one-shot write with validation gates — no replay, no interface switch (AD-3)
  [`device.py:240`](../../src/rapoo_vt7/device.py#L240)

- Write + verify composition: re-read at `EEPROM_DATA_OFFSET` and compare
  [`device.py:259`](../../src/rapoo_vt7/device.py#L259)

**Tests**

- Exact wire format for both prefixes (0xA5 wireless, 0xFF USB cable)
  [`test_device.py:59`](../../tests/test_device.py#L59)

- Empty `06 00` (asleep) and silent-device paths → `CommandTimeout`, exactly one write
  [`test_device.py:134`](../../tests/test_device.py#L134)

- Guard rails: oversize, zero-length, bad address — nothing written
  [`test_device.py:83`](../../tests/test_device.py#L83)

- Verify match/mismatch with both writes asserted byte-for-byte
  [`test_device.py:160`](../../tests/test_device.py#L160)

- Boundary: exactly 24 bytes, short read-back
  [`test_device.py:94`](../../tests/test_device.py#L94)

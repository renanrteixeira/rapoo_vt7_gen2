# Epic 1 Context: Phase 0 — EEPROM infrastructure (CAP-4)

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

Build the read/write foundation every later phase (DPI, performance/parameters, button remap, system) depends on: the app can read and write any bank-0 EEPROM field (2-byte LE address, ≤ 24 bytes per call) and produces a JSON baseline of the device before any write, with every write verified by immediate re-read. Phase 0 also runs a full non-destructive read of all configured fields, validates each field's byte format (1B vs 2B LE) against the passive report 7, and feeds corrections back into the field map. This unblocks CAP-5–8 while keeping the mouse's on-board state safe — nothing is ever written without a baseline.

## Stories

- Story 1: EEPROM write + verify
- Story 2: Baseline dump + settings module
- Story 3: Full read + format validation

## Requirements & Constraints

- Golden rule: capture the EEPROM baseline before any write; verify every write by immediate re-read; read in blocks of ≤ 24 bytes (firmware limit).
- Write path: `write_eeprom(addr, data)` sends Output Report 6 payload `[prefix, 0xA5, len, addr_lo, addr_hi, data…]`; the reply arrives on input report 6 with data starting at `EEPROM_DATA_OFFSET`. Addresses are 2-byte LE; always use bank 0 (base `0x0600 + offset`).
- Never write on the real device before Story 2's baseline exists; the first write test must be on a reversible field (e.g. a DPI value) and confirmed by re-read.
- The mouse may sleep or hot-swap mid-operation: empty replies (`06 00…`) and interface switches must be handled without corrupting state; a write-verify re-read supersedes report-7 data for that field until a newer report 7 with a different value arrives.
- Story 1 ships unit tests; run them with `python3 -m unittest discover -s tests` (FakeDev / FakeClock / Collector injection).
- Story 3's findings (open questions 1/3/6/7: 1B-vs-2B formats, lift-off field, 0x08D8 shared bit mask, report-7 mirror coverage) are recorded in `docs/FEATURES.md` §2 (🔶 → ✅) and fed back into the spec memlog.

## Technical Decisions

- `settings.py` is a pure field registry + codec — `Field(addr, size, type, range, validator)` plus encode/decode — with no device I/O, no GTK, no `device`/`protocol` import. It stores raw bytes and `size`/`type` as data, so format corrections found in Story 3 are data edits, not code changes.
- The worker owns the golden rule (baseline exists → write → verify) via the command queue; a read-modify-write is one atomic queue entry; writes are single-execution and never replayed across an interface switch.
- Baseline path is a shared constant: `~/.cache/rapoo-vt7/eeprom_baseline.json`, consumed identically by `probe.py --dump` and the write path.
- `tools/probe.py` is a separate process that opens its own device; it is a diagnostics/validation harness (`--dump`, `--status`), never a user-facing interface.
- Wire constants and EEPROM addresses live only in `protocol.py`; snapshots carry raw device values and all presentation mapping stays in the GUI layer.

## UX & Interaction Patterns

No GUI surface in this epic — EEPROM access is infrastructure. `probe.py` is diagnostics only; per the project rule, every user-manipulable feature must later be reachable from the menu or a dialog, never the CLI.

## Cross-Story Dependencies

- Story 2's baseline capture must precede Story 1's first real-device write (golden rule).
- Story 3 is read-only and depends on Story 2's registry (addresses/names) plus the existing `read_eeprom`; it is the validation pass that corrects the registry and field map.
- Later epics (CAP-5–8) build on this epic's registry and write-verify infrastructure; the architecture binds CAP-4 to `device.py`, `settings.py`, `session.py`, and `tools/probe.py` under AD-3/AD-6/AD-9/AD-10.

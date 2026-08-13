# Phase map — Rapoo VT7

Capability → roadmap phase → status → primary EEPROM addresses / commands. Full
field tables and protocol details live in `../../../CONTEXT.md` and
`../../../docs/FEATURES.md` (authoritative, do not duplicate here).

| Capability | Roadmap phase | Status | Primary addresses / commands |
|---|---|---|---|
| CAP-1 Battery indicator | Phase 1 (done) | ✅ implemented | 0xAA `get_battery_level`, passive report 7 |
| CAP-2 Both connections | Phase 1 (done) | ✅ implemented | PIDs 0x1413 / 0x4613, prefixes 0xA5 / 0xFF |
| CAP-3 Link / sleep handling | Phase 1 (done) | ✅ implemented | input report 6 / 7 |
| CAP-4 EEPROM infrastructure | Phase 0 | ⬜ pending | read 0xA4, write 0xA5; baseline `eeprom_baseline.json` |
| CAP-5 DPI control | Phase 2 | ⬜ pending | 0x0888 / 0x08C8 (X/Y lists), 0x0898 (gear), 0x0896 (enable) |
| CAP-6 Performance / parameters | Phase 3 | ⬜ pending | 0x08DC mode, 0x08D8 RF, §C params (0x0880–0x08C6) |
| CAP-7 Button remap | Phase 4 | ⬜ pending | 0x0600–0x0638 key fields |
| CAP-8 System operations | Phase 5 | ⬜ pending | 0xAD reset, 0x09EC name, receiver pairing discovery then flow |

Bank 0 base = `0x0600 + offset`; always use bank 0. Confidence legend: ✅
validated on hardware, 🔶 high confidence from bundle (needs device check), ⚠️
generic — see `docs/FEATURES.md` §1.

Phase 5 is sequenced as independent stories: factory reset, device rename,
receiver-pairing protocol discovery, then the receiver-pairing UI. The pairing
flow cannot begin until discovery validates its commands on the real device.

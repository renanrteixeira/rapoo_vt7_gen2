# MOUSE FEATURES — Rapoo VT7 (24ae:1413 / 24ae:4613)

> Resume manual of the features (Phase 2+). The **battery is already done**
> (`src/rapoo_vt7/battery.py` + `tray.py` + `icons.py`). This document lists
> **everything the mouse can do** and the **roadmap** to implement on Linux.
> Main sources: A Hub bundle (`docs/rapoo_hub_app.js`), product config
> (`docs/product_info_rapoo.json`, product `17939` = VT7) and the already
> deciphered protocol (see `CONTEXT.md` sections 3 and 4).

---

## 1. Confidence legend

| Mark | Meaning |
|---|---|
| ✅ | Validated on this mouse hardware (or command/address confirmed) |
| 🔶 | High confidence (A Hub bundle / product config), **needs validation on the real device** |
| ⚠️ | Generic A Hub info, applicability to the VT7 **to be confirmed** |

Golden rules for any implementation:
- **Always back up (dump) the EEPROM before writing** any field.
  `read_eeprom` reads up to 24 bytes per call (firmware limit); read in blocks.
- Writing is via **Output Report 6**, payload `[prefix, 0xA5, len, addr_lo,
  addr_hi, data...]` — implemented as `device.write_eeprom` +
  `write_eeprom_verify` (readback-confirmed, Phase 0).
- Every write changes the mouse's on-board state. Test with a reversible field
  (e.g. DPI) and confirm by re-reading.

---

## 2. Feature inventory (besides battery)

### A. DPI — ✅ addresses, ✅ formats
Product: **50 to 26000, step 50**, X/Y axis **independent** (`entity: true`),
with a **gear** system up to 7 gears.

| Item | EEPROM (bank 0) | Notes |
|---|---|---|
| DPI X table (per gear) | `0x0888` | `MOUSE_DPI_X_LIST` `_3(648)` — array, **2B LE ✅** |
| DPI Y table (per gear) | `0x08C8` | `MOUSE_DPI_Y_LIST` `_3(712)` — **2B LE ✅** |
| Current gear (index) | `0x0898` | `MOUSE_DPI_CUR` `_3(664)` — **1B ✅**; report 7 `data[1]` |
| Enable gears | `0x0896` | `MOUSE_DPI_ENABLE_GEAR` `_3(662)` — **1B ✅** |
| Max. gear count | — | `MOUSE_DPI_GEAR_LENGTH = 7` (bundle constant) |

- Passive DPI read: report 7 `data[2..3]`=dpiX LE, `data[4..5]`=dpiY LE
  (already parsed in `CONTEXT.md` §3.3; **validated: 5000 DPI**).
- Cross-validated on device (`probe.py --status`, 2026-08-10): EEPROM
  `dpi_current`=1, gear-1 X/Y=5000 **MATCH** passive report 7 (5000/5000).
- Write DPI: `write_eeprom` at `0x0888`/`0x08C8` + store the index at `0x0898`.

### B. Performance / sensor — ✅ addresses, 🔶 values
| Item | EEPROM | Notes |
|---|---|---|
| Performance mode | `0x08DC` (+6 bytes) | `SENSOR_MODE` `_3(732)` — a **7-slot table** starting at `0x08DC`, one byte per polling-rate index (0=125Hz … 6=8000Hz); value = **mode id 0..5**. ⚠️ id→name is REVERSED vs the A Hub UI card order (bundle `MousePerformanceUtil`: the `mode_0_*` card has `id:5`): **0 Office, 1 Balance (Low Power), 2 Fire (High Performance), 3 Hyper core, 4 Gaming hyper core, 5 Fury gaming** (Corded). "Set mode" writes 1 byte at `0x08DC + rate_index`; read mode reads that slot (A Hub write primitive `x0` = one `0xA5` len-1 write). **✅ VALIDATED ON DEVICE (2026-08-11)**: factory table `[0,0,1,1,3,3,3]` read; write+readback at slot 3 (1→4→1) restored OK; rate change (`0x0880`=8) mirrored in report 7 `rpt_usb` (8) — `rpt_usb` IS the rateCode, `rpt_24g` is not. Slot for the active rate comes from `rpt_usb` (or `0x0880`). A Hub selectable per slot: `{0:[0,1],1:[0,1],2:[0,1,2],3:[1,2,3,4,5],4:[2,3,4,5],5:[3,4,5],6:[3,4,5]}` |
| Internal sensor parameters | `0x0880` `0x0881` `0x0884` `0x0885` | `MOUSE_REPORT`/`MOUSE_SCAN`/`MOUSE_SLIGHT`/`MOUSE_MOTION` — **1B ✅**; change together with the mode; ⚠️ do not edit directly without understanding |
| RF strategy | `0x08D8` | `RF_STRENGTHEN_SWITCH` (smart / full RF). **Shared byte ✅ (read)**: shares one byte with `LOW_POWE_WARN_SWITCH` (read 0x00 = bits 00000000) — a bit mask; per-field writes must use masked values. **Bit layout ⚠️ working hypothesis** (`protocol.RF_STRENGTHEN_MASK`/`LOW_POWE_WARN_MASK`): bit 0 = RF strengthen (0 Adaptive, 1 Maximum RF), bit 1 = low-battery light warning (0 off, 1 on) — not yet confirmed by a device write-diff. Any write must preserve the unrelated bits and be verified by re-reading the whole byte. Implemented + unit-tested in `performance.py` (`read_rf`/`write_rf_strengthen`/`write_low_power_warn`) and exposed in the Desempenho tab (state + toggles) — story 3-2 |
| Polling rate (回报率) | `0x0880` | `MOUSE_REPORT` (the byte IS the **rateCode**): 125→8, 250→4, 500→2, 1000→1, 2000→132, 4000→130, 8000→129 (A Hub `u` list). **Slots 0..6 map to those codes in order** (`performance.RATE_INDEX_BY_CODE`/`rate_hz`): slot 0=125, 1=250, 2=500, 3=1000, 4=2000, 5=4000, 6=8000 Hz. Passive: report 7 `data[11]`=rpt_usb mirrors `0x0880` (**validated**: writing 0x0880=8 → rpt_usb=8; restore → back; the A Hub rate-change listener matches `rateCode === rpt_usb`); `data[10]`=rpt_24g is NOT a rate code (observed constant) and is ignored. `performance.rate_index_from_code` maps the code to the slot 0..6.
      **Changing the rate is implemented** (`performance.set_rate(dev, hz)`:
      writes the rateCode to `0x0880` + readback verify; the Desempenho tab
      shows a radio per slot 125..8000 Hz with the current one marked, and
      the RF strategy is a marked radio pair Adaptative/Maximum) |

### C. Mouse parameters — ✅ addresses + ✅ writable (write-test 2026-08-11); byte maps ⚠️ inferred (P9)
On-device write-test per byte (read → write → re-read → restore, each byte
restored exactly) confirmed writability + stickiness. Inputs shipped:
**toggles** only for the bool-validated bytes, **sliders** for the numeric
bytes whose A Hub range is known, read-only rows for the rest. Every write is
verified by re-reading (mismatch rejects) and only values on the A Hub grid
are written (`set_param_choice`; user-initiated, `wake=True`):
| Item | EEPROM | Input |
|---|---|---|
| Motion sync (移动同步) | `0x0885` | **toggle ✓** (reads 0x01) |
| Press debounce (按下去抖延迟) | `0x08C0` | **slider 0–32 ms step 2** (byte = ms; factory 0x02) |
| Release debounce (抬起去抖延迟) | `0x08C1` | **slider 0–32 ms step 2** (byte = ms; factory 0x02) |
| Sleep time (无线休眠时间) | `0x08C2` | **slider 2–120 min** (byte = min; factory 0x02) |
| Linear correction (直线修正) | `0x08C3` | numeric 0..3, **not** bool → read-only |
| Sensor angle (传感器角度) | `0x08C4` | **slider −30°..30° step 1** (signed byte; factory 0x00 = 0°) |
| Glass tracking (追踪玻璃) | `0x08C5` | **toggle ✓** (reads 0x00) |
| Lift-off height (光学引擎静默高度) | `0x0884` | **slider 1.0–2.0 mm step 0.1** (byte 1..11 ↔ 1.0..2.0, factory 0x01 = 1.0 mm) |
| DC switch | `0x08DA` | **toggle ✓** (reads 0x00) |
| Low power | `0x08C6` / `0x08AC` | two candidate addresses, function unresolved → read-only |
| Wave correction (波浪修正) | ⚠️ | no confirmed address → not exposed |

> **A Hub divergence (kept deliberately)**: the official VT7 product config
> (`docs/enc.data.json` key `17939`, loaded by `assets/MousePerformanceUtil`,
> receiver PID map in `docs/enc-map.data.json` `5139→17939`) sets
> `enableGlassTracking:false` and `dcSwitch:false`, so the A Hub **hides** the
> Glass tracking and DC switch toggles for this product. We keep both because
> the bytes are writable and sticky on the hardware. Debounce/sleep/angle have
> no per-product range in `enc.data` — the ranges above come from the A Hub
> settings page, the byte maps are OUR inference (press/release/sleep: byte =
> displayed value, defaults agree; angle: signed byte; lift-off: byte 1..11 ↔
> 1.0–2.0, factory 0x01 = minimum). Definitive confirmation = observe an A Hub
> write and diff the byte (pending, P9).

### D. Button remap — ✅ addresses, ⚠️ codes
Each key has an EEPROM field (format to validate) with the function code.
On-device read (2026-08-10): left/middle/right=0x03, forward/back=0x03,
DPI±=0x08, scroll fwd/back=0x0B, scroll right/left=0xFF, bottom=0x0A, BLE=0x03.
1B codes are plausible (scroll 0xFF = off); a 2B read showed no consistent
second-byte pattern (0x0624/0x0628 read back 0xFF), so the exact field size
**stays open** until a write test (S8).

| Key | EEPROM | Key | EEPROM |
|---|---|---|---|
| Left | `0x0600` | Scroll fwd | `0x0624` |
| Middle | `0x0604` | Scroll back | `0x0628` |
| Right | `0x0608` | Scroll right | `0x062C` |
| DPI+ | `0x060C` | Scroll left | `0x0630` |
| DPI- | `0x0610` | Bottom button | `0x0634` |
| Forward | `0x0614` | BLE | `0x0638` |
| Back | `0x0618` | | |

Functions available in the A Hub (`basicKeys`/`mediaKeys`): left, right, middle,
scrolls, forward/back, DPI+ / DPI- / DPI+ cycle / DPI- cycle, DIY, **fire**,
**sniper**, config switch, disable, media keys (sound, volume, player,
calculator, copy/paste etc.), keyboard key, **combination of up to 3 keys** and
**macro**. Numeric codes have **not been extracted yet** from the bundle
(extract via minification when configuring in the A Hub and diffing a dump).

### E. System / firmware — ✅ commands, ⚠️ flows
| Item | Mechanism | Notes |
|---|---|---|
| Factory reset | `0xAD` `return_factory_settings` | command ✅; app confirmation is "wipes everything" |
| Firmware update | `0xA8` `factory_update` + download | requires **wired mode**; risky — last phase |
| Receiver pairing | app flow (`deviceMatcher`) | 3 steps (connect wired, position, press L+M+R); commands ⚠️ not mapped |
| Device name | `0x09EC` | `CONFIG_NAME` `_3(1004)` — **16B string ✅**; read "CFG1" on device |
| Connection mode | `0xA2` `get_work_mode` | ✅ implemented in `tools/probe.py` |
| Firmware/version | `0xA3` `get_firmware` | ✅ implemented |

### F. Not applicable to the VT7 (⚠️ confirm before discarding)
- **RGB/lighting**: `MOUSE_LIGHTMOD 0x0899`, `MOUSE_LIGHTRGB 0x08B8`
  exist in the protocol, but product `17939` **has no `lightModes`** → VT7
  probably has no lighting.
- **Screen/OLED**: product has no `hasScreen`; interface 2 (hidraw3, 512 B)
  exists in the descriptor but is not used by the VT7.

---

## 3. Implementation roadmap

Principle: each phase ends **testable** (CLI or menu) with what was learned
recorded here. When resuming, start from the end of the last marked phase.

### Phase 0 — EEPROM infrastructure (needed for everything) ✅ done
- [x] `device.py`: add `write_eeprom(addr, data)` (command `0xA5`, 2B LE addr,
      len≤24 validation) with **immediate re-read to verify**.
- [x] `tools/probe.py`: add a **`--dump`** mode that dumps the EEPROM in
      24 B blocks (e.g. 0x0600–0x0A00) to a JSON file at
      `~/.cache/rapoo-vt7/eeprom_baseline.json`. **Do the baseline NOW**,
      before any write.
- [x] New module `settings.py`: map §2 addresses to Python objects
      (read/write a field by name + range validation).
- [x] Test: dump + re-read; compare with the A Hub state (Windows).

### Phase 1 — Full read (non-destructive) ✅ done (2026-08-10)
- [x] Probe all §2 addresses and build the **real current configuration**:
      DPI X/Y, gear, performance mode, RF, C parameters, button map.
- [x] Validate **the format of each field** (1B vs 2B LE; on/off; ranges).
      Record in the §2 table (change 🔶→✅).
- [x] Confirm in the passive report 7 the fields it already mirrors (dpi, gear,
      rpt_24g, rpt_usb, mode, config) — cross validation.
- [x] Deliverable: `python3 tools/probe.py --status` printing everything readable.

### Phase 2 — DPI (first useful feature)
- [x] `dpi.py`: `read_dpi` (gear + enable + X/Y tables, 2B LE), `set_gear`
      (write `0x0898` + verify), `set_value` (X/Y per gear, 50–26000 step 50,
      write + verify, IN PLACE), `set_gears` (compact list + enable byte),
      `add_gear`/`delete_gear` (append / remove-with-compaction, like the
      A Hub `setDeviceGears`), `active_count`/`active_gears`. The gear list is
      kept **sorted ascending by value** on every ADD (the current DPI
      follows its VALUE across the reorder — the DPI in use never changes).
      Spin edits change the value IN PLACE: no reorder, no re-select.
- [x] Window "DPI" section (the systray submenu was removed — features live in
      the window only): a list of the **ACTIVE** gears (the compact list IS
      the physical-button cycle — the enable byte 0x0896 is a **count-1**, not
      a bitmask): radio per gear selects the current, X spin 50–26000 step 50,
      "✕" per gear removes it from the cycle (compacts + re-selects the
      current like the A Hub), "Add DPI" appends 800 (max 7 — the Add button
      is disabled when the cycle is full; the last gear is protected from
      deletion). Spin edits are debounced (600 ms) and APPLY the value only
      when the edited gear's radio is marked (the current gear) — editing any
      other gear just stores the value, without reordering or switching the
      DPI in use;
      a popup notification confirms each change. All writes go through
      `BatteryMonitor.submit(..., wake=True)` — an explicit user action is
      attempted even while the mouse is asleep (a device timeout flips the
      monitor back to asleep with a localized message).
- [x] Serialized device access: `BatteryMonitor.submit()` runs device tasks
      on the monitor thread (the only hidraw reader/writer); a task is
      rejected with `CommandTimeout` while the mouse sleeps.
- [x] **Gear switch validated on the real device** (2026-08-10): `set_gear`
      wrote `0x0898`, readback verified, `read_dpi` reflected the change and
      passive report 7 mirrored it (gear 1 ↔ 2, 5000 ↔ 800). The mouse
      restores the gear on the next read.
- [x] **Physical DPI button → app**: the window re-reads the DPI config
      whenever report 7 changes the reported gear/X/Y (`BatteryMonitor.on_report`
      → `_refresh_dpi`).
- [x] **Set a DPI value + add/remove gears** in the window editor
      (`dpi.set_value` per gear; `dpi.add_gear`/`dpi.delete_gear` for the
      cycle). **Enable byte = COUNT, not bitmask** — validated on the device:
      `0x0896=1` → the button cycles only slots 0-1 (800↔1200); `0x0896=6` →
      all 7 slots. The A Hub "enable" toggle is an edit lock only; the real
      way to restrict the cycle is removing the gear from the compact list.
- [x] Add/delete validated on the real device (2026-08-11): add 5000 →
      `[800,1200,5000]` enable 2; delete → `[800,1200]` enable 1 with the
      current gear re-selected; user config restored afterwards.
- [ ] Validate persistence (reboot the mouse / unplug-replug).

### Phase 3 — Performance / parameters
- [x] Performance modes (`0x08DC`): window tab with the 6 modes (radio per
      mode; applies to the active polling-rate slot). Implemented + unit-tested
      (`performance.py`, `tests/test_performance.py`, 12 tests). On-device
      validation pending: read the 7 slots, confirm the current rate slot and
      that a write sticks (mouse must be awake).
- [x] RF strategy (`0x08D8`, bits) + polling rate (map index→Hz) — story 3-2.
      The shared byte is exposed consistently (`read_rf`/`rf_state`: RF
      strengthen bit 0, low-power warning bit 1); the Desempenho tab shows the
      RF/low-power state and provides masked-write toggles that preserve the
      unrelated bits and are confirmed by re-reading (a readback mismatch is
      rejected with an error). The active polling rate in Hz follows the
      validated `rpt_usb` → slot mapping (`rate_hz`/`rate_index_from_code`),
      with `perf.SLOT_DEFAULT` fallback when `rpt_usb` is unavailable.
      ⚠️ The exact bit positions (0x01/0x02) are the working hypothesis — the
      device read was 0x00; a write test diffing an A Hub dump should confirm.
- [x] §C parameters as toggle/state (story 3-3): motion sync, glass tracking
      and DC switch shipped as **confirmed bool toggles** (on-device write-test
      validated: read → write → re-read → restore). Linear correction, sensor
      angle, debounce, sleep time and lift-off are numeric → **read-only
      state**; low power (two candidate addresses) and wave correction (no
      address) are **gated** (read-only + defer entries). Added
      `parameters.py` (read/set + verify primitives, isolated section read),
      Desempenho-tab section with re-translated labels, probe `--status`
      decode of the confirmed semantics, `tests/test_parameters.py`. Suite
      passes on the real device.
- [x] §C UX hardening (2026-08-11): **toggles validate strictly** (0/1 only —
      a garbage byte is isolated as a section error instead of silently
      decoding as "on"), the **last known values are retained** during errors
      (never nulled) and **multiple broken bytes aggregate**
      (`+N more` in the status line); **read-only rows show the documented
      unit** (debounce ms, sleep min); the toggle/state list **scrolls**
      (window fits on a small screen); the low-power toggle has a tooltip
      explaining the 125 Hz report-rate link; labels/tooltips **re-translate
      on language change**. Render decisions moved to pure functions
      (`gui.params_render_plan`/`params_status_text`, headless-tested in
      `tests/test_gui_units.py`).
- [x] Each one: read→show→write→re-read→confirm persistence (2026-08-11:
      write-test on the live device for all 11 §C bytes — every byte sticks
      and is restored exactly; bool semantics confirmed for motion/glass/DC).

### Phase 4 — Button remap
- [ ] Extract the **numeric codes** of the functions from the bundle (hard:
      minified bundle; tip: configure 1 key in the A Hub, dump before/after,
      diff).
- [ ] UI: "key → function" dialog (list from §2.D).
- [ ] Write the key field (`0x0600`–`0x0638`) and confirm it works.
- [ ] App business rule: **always keep at least 1 left button**.

### Phase 5 — System
- [ ] Factory reset (`0xAD`) with a confirmation dialog.
- [ ] Device name (`0x09EC`).
- [ ] Receiver pairing (3-step flow) — validate commands.

### Phase 6 — Advanced (caution)
- [ ] Macros: only if the VT7 support is confirmed (the bundle's macro protocol
      is from another generation? check `docs/protocol_api_rapoo.js` = ClickSync,
      do not use).
- [ ] Firmware update (`0xA8`) — only with a factory dump + the A Hub recipe.

---

## 4. Technical notes to continue

- **EEPROM bank 0** = base address `0x0600 + offset`. The `_3(off)` fields
  exist in 8 banks (`0x0600/0x0A00/0x0E00/0x1200/0x1600/0x1A00/0x1E00/0x2200`);
  always use bank 0. `0x08D8` appears 2× in the bundle
  (`RF_STRENGTHEN_SWITCH` and `LOW_POWE_WARN_SWITCH`) → likely a **bit mask**.
- **Read**: `read_eeprom(addr_2B_LE, len≤24)` → data in `data[5]` of the raw
  report (`protocol.EEPROM_DATA_OFFSET`).
- **Write**: implemented since Phase 0 (`device.write_eeprom_verify` re-reads
  after every write). Write-tested on the real device: DPI gear/value/add/
  delete (Phase 2), performance mode + rate-code + RF (Phase 3-1/3-2), §C
  params motion_sync/glass/dc_switch (Phase 3-3) — all read-back verified.
  After writing, **always re-read**.
- The A Hub bundle is the source of names/ranges (i18n `parameters`,
  `performance`, `dpi`, `mouseChangeKey`). To find terms: search the PT/CN
  texts in the JS.
- `docs/protocol_api_rapoo.js` (ClickSync, `A5A5`) is from **another generation**
  — do not use.

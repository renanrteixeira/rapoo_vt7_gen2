# PROJECT CONTEXT — Rapoo VT7 on Linux

> This document is the **resume manual**. If you lose the session/context, start here.

---

## 1. Goal

Linux software in the **systray** (GNOME) that shows the **Rapoo mouse battery
level** in an Android/iOS style icon: the percentage **inside** the icon and
color by level:

- green: 50–100%
- yellow: 20–49%
- red: 0–19%

Phase 2 (future): DPI adjustment from the icon menu.

Language: **Python 3**. Communication via **direct hidraw** (no hidapi — the
cython-hidapi lib cannot open the device; see section 4).

**STATUS: battery working and robust.** The app runs in the systray with: a
0xAA poll every 30 s + **passive listening of report 7** (battery, USB/2.4G/BT
connection mode, DPI, rate — validated: USB/charging/82%), icon with % and
charging bolt, low battery notification (20%/10%), menu with "Refresh now",
last read time and "asleep" state. Supports both connections (2.4G + USB cable).
Autostart (A7) and uninstall (A8) implemented and tested. **Phase 2 DONE**: the
window is organized in **tabs** (Bateria | DPI): tab 1 = elegant mouse image +
battery status + language selection; tab 2 = "DPI" section: a list of the
ACTIVE gears (radio per gear, selects the current; X value spin per gear;
"✕" button per gear removes it from the cycle) + an "Add DPI" button. The
list IS the physical-button cycle — the enable byte 0x0896 is a COUNT
(cycle = first enable+1 slots of the X/Y tables), so "disabling" a gear means
removing it from the compact list (A Hub `setDeviceGears` semantics, validated
on the device: enable=1 → button cycles only slots 0-1). **Gear switching +
value + add + delete validated on the real device** (write `0x0898`/`0x0896` +
readback + report 7 mirror; see `docs/FEATURES.md`). The tray DPI submenu was
**removed** — DPI features live in the window only. The systray **icon is a
Material-style mouse + the percentage with `%` beside it** (colored by level;
prefix `rapoo_mouse_`, 46x24 px). User DPI actions use `submit(..., wake=True)`
so they are attempted even if the mouse just fell asleep. **The physical DPI
button stays in sync**: report 7 mirrors the gear + X/Y
(`BatteryMonitor.on_report`), and the app re-reads the DPI config and rebuilds
the tab when it changes.

---

## 2. Hardware identification (confirmed)

`lsusb`: `ID 24ae:1413 Shenzhen Rapoo Technology Co., Ltd. Rapoo Gaming Device`

- **VID/PID**: `24ae:1413` (2.4G receiver) and `24ae:4613` (mouse via direct USB
  cable). Nordic nRF54L15 MCU, PAW3950 sensor, 800 mAh battery.
- **Device 0x1413 is the 2.4G RECEIVER.** The A Hub (map `Je`) maps
  `0x1413 -> 0x4613` ("VT7" mouse). The mouse actually appears in the firmware
  as PID `0x4613`. A direct USB connection of the mouse has PID `0x4613` and
  prefix `0xFF`.
- **Both connections supported**: `device.py` scans the configuration interfaces
  (report id 6) of both PIDs, **prefers the mouse over the USB cable** (prefix
  `0xFF`) and falls back to the 2.4G receiver (prefix `0xA5`) when there is no
  cable. On timeout, it switches to the other interface (hot swap:
  plug/unplug the cable).
- The udev rule covers both PIDs (`1413|4613`).
- Official software: web "A Hub" at `https://hub.rapoo.cn/` (WebHID). The bundle
  `index-sYS3NwBK.js` was downloaded to `docs/rapoo_hub_app.js` and is the
  authoritative protocol reference (commands, addresses, parser).
- **3 HID interfaces** (the hidrawX number changes after each boot):
  | interface | type | current hidraw |
  |---|---|---|
  | 0 | mouse/keyboard boot (hidraw1) | hidraw1 |
  | 1 | **configuration** (vendor `0xFF00:0x0E`, report ids 2-12) | hidraw2 |
  | 2 | screen/RGB (512 B, vendor `0xFF00:0x01`) | hidraw3 |
- **The configuration interface is interface 1 → hidraw2.** Robust
  identification: hidraw whose report descriptor contains the **Report ID 6**
  (the command report). Automatic detection is in `device.py`.
- `hid-generic` provides the hidraws; the udev rule (section 6) is enough.
  `/dev/hidraw*` are root-only without it.

---

## 3. Mouse protocol (deciphered from the A Hub — MAIN REFERENCE)

⚠️ **Do NOT use** the `A5A5/A5A4` protocol from ClickSync
(`docs/protocol_api_rapoo.js`) — it is from another Rapoo generation and this
firmware does **not** respond to it.

### 3.1 Commands
- Send on the **Output Report ID 6** (32 B report): first byte = report id,
  then the payload `[prefix, cmdId, ...args]`.
- Prefix: wireless receiver = **`0xA5`**; direct USB mouse = `0xFF`.
  (The Telink protocol would add +32 to the cmdId; the VT_nrf54L does not.)
- Command IDs (`VT_nrf54L` protocol):
  | cmdId | name | payload |
  |---|---|---|
  | 0xA2 | get_work_mode | — |
  | 0xA3 | get_firmware | `[type]` (use 0) |
  | 0xA4 | read_eeprom | `[len≤24, addr_lo, addr_hi]` |
  | 0xA5 | write_eeprom | `[len, addr(4B), data...]` |
  | 0xA8 | factory_update | — |
  | 0xAA | **get_battery_level** | — |
  | 0xAD | return_factory_settings | — |

### 3.2 Reply (INPUT Report 6)
On hidraw the reply arrives as an **input report 6** (the feature report 8/9 is
zeroed on Linux — in WebHID the app reads the feature; here we use the input):
```
06 01 <payload...>
└┘ └┘
rid ACK(0x01)
```
- Reports with `data[1] == 0x00` are "empty" (heartbeat / mouse asleep).
- **get_battery_level** (0xAA): `06 01 <status> <battery%>` → status in `data[2]`
  (0 invalid, 1 ok, 2 charging), **battery in `data[3]`**.
  *Validated: `06 01 01 3E` → status=1, battery=62%.*
- **get_firmware** (0xA3): `data[2]`=minor, `data[3]`=major, `data[6..7]`=mouse
  PID (LE) → observed `v0.145`, PID `0x4613`.
- **get_work_mode** (0xA2): mode in `data[2]` (observed `0x11`).
- **read_eeprom** (0xA4): data read starts at `data[5]` (in WebHID, without the
  report id, it would be `data[4]`).
- Indexes above are of the **raw report** (byte 0 = report id).

### 3.3 Battery — passive channel (Input Report 7)
The mouse also periodically sends the **input report 7** (18 B). App parser
(A Hub `parserBaseData`). **Indexes of the raw report** (byte 0 = report id
`0x07`):
- `data[1]`: low nibble = connectType (0 wireless, 1 BT, 2 USB); high nibble = sensorTypeModel
- `data[2]` = DPI gear/index
- `data[3..4]` = dpiX (LE), `data[5..6]` = dpiY (LE)
- `data[7]` = battery status (0/1/2), `data[8]` = **battery %**
- `data[9]` = blMode, `data[10]` = rpt_24g, `data[11]` = rpt_usb, `data[12]` = config

*Validated: `07 10 01 88 13 88 13 01 3E ...` → data[1]=0x10 (wireless, sensor 1),
gear 1, DPI 5000, status=1, battery 62%.*
> ⚠️ In WebHID (without report id) the indexes are 1 less: mode in [0], status
> in [6], battery in [7] etc. On hidraw **add 1** from `data[1]`.

### 3.4 EEPROM addresses (A Hub table `yh`, VT_nrf54L)
2-byte LE addresses. "Double-byte" fields (`_3(e)`) exist in **8 banks**
(0x0600/0x0A00/0x0E00/0x1200/0x1600/0x1A00/0x1E00/0x2200); bank 0 is used.
Relevant (Phase 2):
- `CURRENT_CONNECT_PROTOCOL` = `[0x04, 0x01]` (read: 0 = wireless)
- `CONFIG_CURRENT` = `[0x0C, 0x01]`
- `MOUSE_DPI_CUR` = bank0 `0x0600+0x0298` → `[0x98, 0x08]`
- `MOUSE_DPI_X_LIST` = `0x0600+0x0288` → `[0x88, 0x08]`; `MOUSE_DPI_Y_LIST` = `[0xC8, 0x08]`
- `MOUSE_DPI_ENABLE_GEAR` = `0x0600+0x0296` → `[0x96, 0x08]` — **COUNT-1, not a
  bitmask**: the physical DPI button cycles the first (enable+1) slots of the
  X/Y lists (validated: enable=1 → 800↔1200 only). The A Hub toggle is UI-only.
- `MOUSE_DPI_GEAR_LENGTH`, other fields — see `docs/rapoo_hub_app.js`.

---

## 4. Why direct hidraw (and not python3-hid)

- `python3-hid` (cython-hidapi) is installed, but: the class is `hid.device`;
  `open_path` fails with a relative path and with `/dev/hidraw3`;
  `open(vid,pid)` fails.
- The working solution: **`os.open("/dev/hidraw2", O_RDWR|O_NONBLOCK)`** +
  `os.write`/`os.read` + `select` to wait for the reply. Feature report ioctl
  (HIDIOCGFEATURE) exists but is **not needed** (the reply comes on input 6).
- Useful constants: `HIDIOCGRDESCSIZE = 0x80044801`, `HIDIOCGRDESC = 0x90044802`.

---

## 5. Machine environment

- Ubuntu 26.04 LTS, GNOME **Wayland**, user `renan` (sudo, plugdev).
- `ubuntu-appindicators` extension ACTIVE → AppIndicator works.
- Packages: `python3-hid`, `python3-gi`, `gir1.2-ayatanaappindicator3-0.1`,
  `python3-gi-cairo`, `python3-cairo` (pycairo — used by the icons).
- **Attention**: the icons use **pycairo** (`import cairo`), NOT
  `gi.repository.cairo` (that one does not expose `ImageSurface`).

---

## 6. Project structure

```
rapoo_vt7_gen2/
├── CONTEXT.md                  ← this manual
├── README.md, install.sh, run.sh, uninstall.sh
├── udev/99-rapoo-vt7.rules
├── docs/rapoo_hub_app.js       ← official A Hub bundle (protocol source)
├── docs/protocol_api_rapoo.js  ← ClickSync (other generation — do NOT use)
├── docs/FEATURES.md            ← full map + roadmap (Phase 2+)
├── src/rapoo_vt7/
│   ├── main.py                 ← GTK loop + starts monitor and icon
│   ├── protocol.py             ← CMDs, prefixes, offsets, addresses
│   ├── device.py               ← direct hidraw + interface detection (rid 6)
│   ├── battery.py              ← thread: 0xAA poll + passive report 7 listen
│   ├── dpi.py                  ← Phase 2: read_dpi/set_gear/set_value/set_gears/add_gear/delete_gear
│   ├── gui.py                  ← window in tabs: battery + DPI (active-list radios + editor)
│   ├── icons.py                ← cairo icon: Material mouse + % (46x24) + cache
│   └── tray.py                 ← AppIndicator + menu (battery + window)
tools/probe.py                   ← diagnostics (battery, firmware, eeprom, reports)
```

---

## 7. Installation / execution

```bash
cd /home/renan/workspace/rapoo_vt7_gen2
./install.sh                      # deps + udev (sudo, 1x)
./run.sh                          # icon in the systray
python3 tools/probe.py            # diagnostics
./uninstall.sh                    # removes udev, cache and autostart (sudo, 1x)
```

udev rule: `SUBSYSTEM=="hidraw", ATTRS{idVendor}=="24ae", ATTRS{idProduct}=="1413|4613", MODE="0664", GROUP="plugdev"`.

---

## 8. Task plan

Legend: [x] done | [ ] pending

### PHASE 1 — Battery in the systray
- [x] **A1** Dependencies + udev rule
- [x] **A2** Config interface identified (hidraw2, report id 6) and the real protocol deciphered
- [x] **A3** Battery validated on the real device: **62%** via command 0xAA (data[3]) and via report 7 (data[7])
- [x] **A4** Icons generated (color + percentage)
- [x] **A5** App in the systray updating with the real battery
- [x] **A6** Test disconnect/reconnect (auto-reconnect every 5 s)
      — covered by `tests/test_battery.py::InterfaceChangeTest` (cable plug-in
      while asleep + `test_run_reconnects_after_device_gone`: connected →
      `DeviceNotFound` → reconnected). `_run` retries every `retry` (5 s).
- [x] **A7** Autostart in `~/.config/autostart/rapoo-vt7.desktop`
      (script `tools/autostart.sh`; `uninstall.sh` removes it)
- [x] **A8** Uninstall script (`uninstall.sh`) — remove udev rule,
      cache, theme icons; stops a running app instance and offers the
      **optional** removal of the installed apt packages (prompt, default No)

### PHASE 2 — Remaining features (see `docs/FEATURES.md`)
Full map + roadmap in `docs/FEATURES.md`. Order: Phase 0 (EEPROM infra +
baseline/dump) → Phase 1 (full read) → Phase 2 (DPI) → Phase 3
(performance/parameters) → Phase 4 (button remap) → Phase 5 (system) → Phase 6
(macros/firmware). No EEPROM field has been written yet — the baseline must be
captured before any write.

- [x] **B0** `write_eeprom` in `device.py` (`write_eeprom`/`write_eeprom_verify`,
      0xA5, 2B LE addr, readback verify) + `tools/probe.py --dump` (JSON baseline
      to `~/.cache/rapoo-vt7/eeprom_baseline.json`; 43 blocks 0x0600-0x0A00)
- [x] **B1** Full read of the addresses `docs/FEATURES.md` §2
      — `tools/probe.py --status` reads all 34 registered fields (raw/decoded),
      cross-validates gear/dpiX/dpiY/rpt vs passive report 7 and flips
      🔶→✅ in `FEATURES.md` §2 (formats validated on device, 2026-08-10;
      buttons 0x0600-0x0638 stay ⚠️ open — need a write test, story 8)
- [x] **B2** DPI: switch gear, set value, add/delete from the cycle
      — read, gear-switch, per-gear value, add and delete implemented and
      **validated on the real device** (`dpi.py`, window UI via
      `BatteryMonitor.submit`; write `0x0898`/`0x0896`/list + readback +
      report 7 mirror). **The enable byte 0x0896 is a COUNT, not a bitmask**:
      the physical DPI button cycles the first (enable+1) slots of the X/Y
      tables (validated: enable=1 → button alternates only 800↔1200; enable=6
      → all 7 slots). The A Hub toggle is just an edit lock — the real
      "disable" is **removing the gear from the compact list**. The DPI tab
      shows the ACTIVE list (radio per gear selects the current; X value spin
      per gear; "✕" per gear deletes/compacts like `setDeviceGears`; "Add DPI"
      appends 800 — **the button is disabled when the cycle is full (7)**).
      **The list is kept sorted ascending by value** on ADD (`_sorted_active`);
      the current gear follows its DPI VALUE across the reorder (the DPI in
      use never changes). **Spin edits change the value IN PLACE** (no
      reorder, no re-select) and **apply only when the edited gear's radio is
      marked** (the current gear) — editing any other gear just stores the
      value (notification `dpi_stored` vs `dpi_edited`). **Cannot delete
      the last gear** (list of 1). Add/delete re-select the current gear like
      the A Hub (first remaining when the current was deleted). **User DPI actions use `submit(..., wake=True)`**
      (attempted even if the mouse just fell asleep; a device timeout flips
      the monitor back to "asleep" with a localized message). Add/delete
      confirmed on the real device (add 5000 → `[800,1200,5000]` enable 2;
      delete → `[800,1200]` enable 1; user config restored after the test).
      **Physical DPI button → window sync**: report 7 mirrors gear+X/Y
      (`BatteryMonitor.on_report`) and the app re-reads + rebuilds the tab
      when it changes. **Empty-tab recovery**: if the mouse was asleep at
      startup the DPI tab stays empty — every connected/open event re-checks
      `window.has_dpi()` and reloads when missing (`_maybe_refresh_dpi`).
- [ ] **B3** Performance/parameters: modes, RF, polling, glass, debounce, lift-off, sleep
      — **modes done** (story 5): the sensor mode is a **7-slot table**
      `0x08DC..0x08E2` (one byte per polling-rate index 0..6; value = mode id
      0..5; ⚠️ id→name is the REVERSE of the A Hub UI card order — **0 Office,
      1 Balance, 2 Fire, 3 Hyper core, 4 Gaming hyper core, 5 Fury gaming**).
      `performance.py` reads/writes the slot of the active rate (rate index
      from report 7 **rpt_usb** — validated on device: it mirrors the
      `MOUSE_REPORT` rateCode 8/4/2/1/132/130/129, and the A Hub listener
      matches `rateCode === rpt_usb`; rpt_24g is not a rate code — or from
      `0x0880`); window tab "Desempenho" with 6 radios (A Hub selectable
      rules per slot); `tests/test_performance.py` (12 tests). **VALIDATED on
      the real device 2026-08-11**: factory table `[0,0,1,1,3,3,3]`, rate
      `0x0880`=1→slot 3, write+readback of slot 3 (1→4→1) restored, rate-code
      write mirrored by rpt_usb. **RF strategy + polling rate (story 3-2)
      DONE**: shared byte `0x08D8` (bit0 RF strengthen, bit1 low-power warning)
      with masked writes + readback verify (`read_rf`/`write_rf_*`), rate-code→
      slot map `125→8 … 8000→129` from `rpt_usb` (`rate_index_from_code`),
      RF toggles + state in the Desempenho tab. **§C parameters (story 3-3)
      DONE** (`parameters.py`): confirmed bool toggles motion_sync `0x0885`,
      glass `0x08C5`, DC switch `0x08DA` (write-test 2026-08-11, all 11 §C
      bytes read→write→re-read→restore); debounce 0x08C0/0x08C1, sleep time,
      sensor angle and lift-off render as **sliders** (`parameters.SELECTABLE`,
      A Hub ranges, on-grid writes verified); read-only rows: linear_ripple
      numeric 0..3, low_power/power_save unresolved, wave correction no
      address.
      **Polling-rate UI + RF radios DONE (2026-08-11)**: `performance.set_rate`
      writes the rateCode of a RATE_HZ value to `0x0880` + readback verify;
      the Desempenho tab shows a **radio per slot (125..8000 Hz)** with the
      current one always marked (from report 7 `rpt_usb`), and the **RF
      strategy is a radio pair "RF adaptativo | RF máximo"** with the current
      one marked (0x08D8 read state) instead of the ambiguous single checkbox.
      Pure render decisions (`perf_rate_state`/`rf_radio_state`) tested
      headlessly (`tests/test_gui_units.py`).
      **Story 8 (params UX) DONE**: toggles validate
      strictly (0/1), last-known values retained on error, multiple broken
      bytes aggregate in the status line (`+N more`), read-only rows show
      units (ms/min), the toggle/state list is scrollable, low-power has a
      tooltip (125 Hz link), labels/tooltips re-translate on language
      change; render decisions are pure functions (`params_render_plan`/
      `params_status_text`) tested headlessly (`tests/test_gui_units.py`).
      **Selectable params (sliders) DONE (2026-08-12)**: the §C numeric
      parameters whose A Hub range is known now render as **Gtk.Scale
      sliders** instead of read-only rows — press/release debounce 0–32 ms
      (step 2, byte = ms), sleep time 2–120 min (byte = min), sensor angle
      −30°..30° (signed byte), lift-off 1.0–2.0 mm (byte 1..11 ↔ 1.0..2.0,
      factory 0x01 = 1.0 mm). Written via `parameters.set_param_choice`
      (value must be on the A Hub grid, `display_to_byte` encodes, readback
      verifies; refused off-grid/off-range), slider value from report-driven
      reads via `byte_to_display`, last-known retained on error. Sources:
      `docs/enc.data.json` (VT7 product config, key 17939 — lift-off range +
      `enableGlassTracking:false`/`dcSwitch:false`; receiver map
      `docs/enc-map.data.json` `5139→17939`) and `docs/rapoo_hub_perf.js`
      (rate list + `PERF_SELECTABLE` — matches ours byte-for-byte; mode cards
      `id:5..0` → names already reversed correctly). **A Hub hides Glass/DC
      for the VT7 but we keep both toggles** (bytes writable/sticky on
      hardware; difference annotated in FEATURES.md §2.C). Debounce/sleep/
      angle byte maps are our inference (defaults agree); definitive = diff
      an A Hub write (P9).
- [ ] **B4** Button remap (extract function codes from the bundle)
- [ ] **B5** System: factory reset, device name, receiver pairing

---

## 9. Pending / decisions

- [P1] **Mouse asleep**: commands do not respond (empty reply `06 00...`).
  Current solution: `battery.py` treats it as "asleep" and retries every 5 s; the
  user moves the mouse to wake it. Background tasks (DPI read) are rejected
  while asleep; **user-initiated DPI actions use `submit(..., wake=True)`** and
  are attempted anyway — only a device timeout flips the monitor back to
  "asleep" (localized message in the window). (The A Hub fails the same way in
  this state.)
- [P2] 30 s poll + **passive report 7** (battery/mode/DPI arrive by themselves and
  update immediately; the 0xAA poll is the fallback when report 7 does not come).
  Listening to report 7 also serves as the basis for DPI/rate in Phase 2.
- [P7] **Mouse battery consumption**: the primary source is the passive report 7
  (sent by the mouse firmware, zero cost for the app). 0xAA commands are only
  sent: (a) on the 1st read when connecting, and (b) after `fallback` (300 s)
  without report 7. When the mouse sleeps, the app enters **listen-only mode**
  (`quiet`, 60 s) without sending commands — moving the mouse makes it send
  report 7 itself and the app wakes up. Result: with report 7 active, ~0 extra
  commands.
- [P3] Validate the "charging" display (status=2) when the mouse is on the cable.
- [P6] **Both connections supported**: 2.4G receiver (0x1413, prefix 0xA5) and USB
  cable (0x4613, prefix 0xFF). `device.py` prefers the USB cable and switches on
  timeout (hot swap). udev rule updated to `1413|4613` (run
  `sudo ./install.sh` or reload udev).
- [P4] Icon size/readability. The panel shows the appindicator in a square box;
  the extension's `icon-size` controls the size (0 = automatic 16 px).
  Configured to **24 px** (native 24×24 icons, readable number):
  `gsettings set org.gnome.shell.extensions.appindicator icon-size 24`
  (affects all appindicators; `0` restores the default).
- [P5] **Icon did not appear in the systray** even with the app running. Two causes
  (both fixed):
  1. **`Status: 'Passive'`** — the `ubuntu-appindicators` extension hides passive
     items (`indicatorStatusIcon.js:322`). Fix: `tray.py` calls
     `indicator.set_status(ACTIVE)`.
  2. **Theme icon name did not resolve** — the theme lookup failed in the panel.
     **Final fix**: `tray.py` passes the **absolute PNG path**
     (`~/.cache/rapoo-vt7/icons/rapoo_batt_XXX.png`) in `set_icon_full` — the
     extension detects a path (name starting with `/`) and loads the file
     directly (`Gio.File` → `StTextureCacheSkippingFileIcon`), without relying
     on a theme.

---

## 10. Useful commands

```bash
lsusb | grep -i rapoo
for h in /sys/class/hidraw/hidraw*; do echo "$h"; cat $h/device/uevent | grep HID_ID; done
python3 tools/probe.py
./run.sh
```

---

## 11. Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `PermissionError` on hidraw | udev rule | replug or `sudo chmod 0666 /dev/hidraw2` |
| Battery "--%" / "unknown" | mouse asleep | move the mouse; the app retries every 5 s |
| Commands return empty | mouse asleep | move the mouse (see P1) |
| Icon does not appear | appindicators extension | enable it in Extensions |
| "busy" when opening hidraw | another process on the interface | close other apps (e.g. A Hub) |

---

## 12. Sources

- A Hub web (bundle + products): `https://hub.rapoo.cn/` — `docs/rapoo_hub_app.js`
  and the encrypted files `enc.data`/`enc-map.data` (OpenSSL AES, key
  `your-secret-key-here`, via EVP_BytesToKey/MD5).
- ClickSync (another generation): https://github.com/Nuitfanee/ClickSync (do not use).
- Rapoo driver in the kernel: `drivers/hid/hid-rapoo.c`.

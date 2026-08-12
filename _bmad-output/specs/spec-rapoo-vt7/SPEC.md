---
id: SPEC-rapoo-vt7
companions:
  - phase-map.md
  - ../../planning-artifacts/architecture/architecture-rapoo_vt7_gen2-2026-08-10/ARCHITECTURE-SPINE.md
  - ../../../CONTEXT.md
  - ../../../docs/FEATURES.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# Rapoo VT7 — Linux systray app (battery + full feature set)

## Why

A **pain to solve** plus a **vision to realize**. The Rapoo VT7 gaming mouse has no native Linux software: the only official tool is a web app (Rapoo A Hub) that needs a browser + WebHID and offers no systray battery indicator and no scriptable access. This project gives a single user (on Ubuntu 26.04 + GNOME Wayland) a native systray app that shows the battery level as a color-coded Android/iOS-style icon — implemented and validated — and, beyond that, brings the mouse's full feature set (DPI, performance/sensor parameters, button remap, system operations) to Linux from the same menu, using the protocol deciphered from the A Hub bundle.

## Capabilities

- **CAP-1** Battery indicator *(implemented)*
  - **intent:** The user sees the mouse battery level at a glance in the systray as a color-coded icon with the percentage inside (green 50–100, yellow 20–49, red 0–19), a charging bolt when on the cable, and a low-battery notification at 20% and 10%.
  - **success:** On a live device the icon shows the real battery (validated 62%) in the correct color band; plugging the cable shows charging (status 2) with the bolt; a battery at or below 20% raises the notification.
- **CAP-2** Both connections with hot swap *(implemented)*
  - **intent:** The app keeps working whether the mouse is on the 2.4G receiver (PID 0x1413, prefix 0xA5) or the USB cable (PID 0x4613, prefix 0xFF), preferring the cable and switching interface on timeout.
  - **success:** Plugging or unplugging the cable while running requires no restart and the displayed connection mode always matches reality.
- **CAP-3** Robust link / sleep handling *(implemented)*
  - **intent:** When the mouse sleeps or disconnects, the app recovers automatically, without user action and without flooding the mouse with commands.
  - **success:** An empty reply (`06 00…`) puts the app in listen-only quiet mode; the first passive report 7 after user movement wakes it; disconnects reconnect within ~5 s.
- **CAP-4** EEPROM infrastructure *(pending — Phase 0)*
  - **intent:** The system reads and writes any bank-0 EEPROM field (2-byte LE address, ≤ 24 bytes per call) and produces a JSON baseline before any write, verifying each write by immediate re-read.
  - **success:** `write_eeprom(addr, data)` writes and a re-read returns the new value; `probe.py --dump` writes the baseline JSON; no write path exists without a baseline.
- **CAP-5** DPI control *(pending — Phase 2)*
  - **intent:** The user sees the current DPI (gear + X/Y) and changes gear and value (50–26000, step 50), enabling or disabling gears, from the systray menu.
  - **success:** The menu shows the live DPI (passive report 7 / EEPROM); a gear switch persists across reboot; a set value re-reads identically.
- **CAP-6** Performance / sensor parameters *(pending — Phase 3)*
  - **intent:** The user adjusts performance mode (0x08DC), RF strategy (0x08D8), polling rate, and the mouse-parameter set (motion sync, linear/wave correction, sensor angle, glass tracking, press/release debounce, lift-off, DC switch, sleep time, low power) from the menu.
  - **success:** Each parameter flows read → show → write → re-read → persist and is confirmed on the real device.
- **CAP-7** Button remap *(pending — Phase 4)*
  - **intent:** The user maps each button field (0x0600–0x0638) to a function, always keeping at least one left button functional.
  - **success:** A remap is written, re-reads to the chosen code, and the OS receives the new function on click.
- **CAP-8** System operations *(pending — Phase 5)*
  - **intent:** The user factory-resets the mouse (0xAD, with confirmation), renames the device (0x09EC), and pairs a receiver (3-step flow).
  - **success:** Each operation is performed and verified on the device without corrupting state.

## Constraints

- **Direct hidraw only** — `python3-hid`/hidapi cannot open the device. Use `os.open("/dev/hidrawX", O_RDWR|O_NONBLOCK)` + `select`; the reply arrives on input report 6 (no feature-report ioctl needed).
- **VT_nrf54L protocol only** — Output Report ID 6 (32 B), payload `[prefix, cmdId, …]`, prefix 0xA5 (receiver) / 0xFF (USB), no +32 on cmdId. The ClickSync `A5A5/A5A4` protocol is from another generation and is forbidden.
- **EEPROM golden rule** — dump a JSON baseline before any write; verify every write by immediate re-read; read in blocks of ≤ 24 bytes (firmware limit).
- **Mouse-asleep discipline** — commands may answer empty (`06 00…`); minimize command load: 0xAA only on first connect and after 300 s without report 7; listen-only (60 s quiet) otherwise.
- **Identification** — the configuration interface is the hidraw whose report descriptor contains Report ID 6; udev covers both PIDs `24ae:1413|24ae:4613` with `MODE="0664" GROUP="plugdev"`.
- **GUI-only user surface** — every user-manipulable feature (CAP-5–8) is reachable from the systray menu or a dialog; the CLI (`probe.py`) is a diagnostics/validation harness, never a user-facing interface.
- **Stack** — Python 3, GTK3 + AppIndicator (ubuntu-appindicators extension, status ACTIVE), pycairo icons (not `gi.repository.cairo`), absolute PNG path via `set_icon_full`, panel icon-size 24 px.
- **Linux-only, single user** — Ubuntu 26.04 + GNOME Wayland; lifecycle via `install.sh` / `run.sh` / `uninstall.sh` + autostart desktop file.

## Non-goals

- **RGB/lighting and OLED/screen features** — product config 17939 has no lightModes/hasScreen; interface 2 (hidraw3, 512 B) is unused by the VT7.
- **Firmware update (0xA8)** — deferred; requires wired mode + factory dump and is high risk; only as a last phase.
- **Macros** — out of scope until VT7 macro support is confirmed on device (the bundle macro protocol appears to be from another generation).
- **Other platforms and devices** — no Windows/macOS, no other Rapoo models.
- **No full settings window** — menu + dialogs only.

## Success signal

On a stock Ubuntu 26.04 + GNOME Wayland, plug in a Rapoo VT7 (2.4G or USB cable): the systray shows the color-coded battery percentage. Without touching the official web app, the user can change DPI gear and value, performance mode and sensor parameters, remap a button, and run a system operation from the menu — each verified by re-read, with the EEPROM baseline dumped before any write, and nothing requiring a reboot or app restart.

## Assumptions

- EEPROM addresses/names in `docs/FEATURES.md` §2 come from the A Hub bundle and map to the real VT7; the low-confidence 1B/2B LE formats are assumed correct pending Phase 1 validation.
- The VT7 has no RGB/OLED (product config 17939 lacks lightModes/hasScreen).
- The A Hub bundle (`docs/rapoo_hub_app.js`) is the authoritative protocol reference.
- Single-user personal tool (user renan, intermediate skill); no auth or multiuser concerns.

## Open Questions

- Are the low-confidence field formats (1B vs 2B LE) correct for each `docs/FEATURES.md` §2 field?
- Does switching the DPI gear persist across reboot on this firmware?
- Which EEPROM field maps lift-off height (candidates include `MOUSE_SLIGHT` 0x0884)?
- Are the button-remap function numeric codes extractable from the minified A Hub bundle?
- What is the index-to-Hz map for polling rate (`rpt_24g` / `rpt_usb` in report 7)?
- Is 0x08D8 a shared bit mask between RF strategy and the low-power warning?
- Does the passive report 7 mirror every field Phase 3 needs for cross-validation?

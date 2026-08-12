# Technology Review — ARCHITECTURE-SPINE.md

**Date:** 2026-08-10
**Reviewer:** architecture review subagent
**Method:** three evidence axes — (1) the running machine itself (dpkg/`python3`/GIR), (2) upstream web sources (python.org, gtk.org/GNOME NEWS, GitHub/pygobject, PyPI, Debian tracker), (3) the existing project code (`src/rapoo_vt7/*`). Every pinned version and named technology below was confirmed by at least one axis; none were accepted from training data alone.

---

## Verdict

**PASS.** Every committed decision and named technology in the Stack table and Structural Seed is either (a) verified live on the installed system (primary evidence), or (b) cross-confirmed against current upstream sources. The Stack table's header — *"Seeded from the running install (ratified, not prescribed)"* — is factually accurate. No stale or hallucinated dependency was found. Three minor notes below are clarity/currency observations, not blockers.

---

## 1. Pinned versions (Stack table) — one-by-one

| Pin in spine | Live machine check | Upstream web check | Verdict |
|---|---|---|---|
| Python 3.14.4 (Ubuntu 26.04 LTS) | `python3 --version` → **3.14.4**; `os-release` → **Ubuntu 26.04 LTS** (apt archive codename `resolute`) | python.org: **3.14.4 released 2026-04-07**, real 4th maintenance release. Superseded by 3.14.5/6/7 (latest 3.14.7, 2026-08-05) | **Correct/ratified.** Not the newest upstream patch, but exactly the running install — pin matches. |
| GTK 3.24.52 | `Gtk.get_major/minor/micro_version()` → **3, 24, 52** | gtk.org "Latest old stable **3.24.52**"; GNOME NEWS 2026-03-22; maintenance mode, next release expected 2027-03 | **Correct/current.** This is the latest of the GTK3 line as of mid-2026; correct pin for an AppIndicator/GTK3 app. |
| AyatanaAppIndicator3 0.1 | `gi.require_version("AyatanaAppIndicator3","0.1")` succeeds (also `tray.py:6`); `gir1.2-ayatanaappindicator3-0.1` installed; backing lib = **libayatana-appindicator 0.5.94-1build1** | GIR API version 0.1 is the stable namespace; Ayatana is the actively-maintained fork (upstream appindicator is unmaintained) | **Correct/ratified.** Note: "0.1" is the *GIR namespace* version, not the library version (0.5.94) — see note 2. |
| pycairo 1.27.0 | `cairo.version` → **1.27.0**; `python3-cairo 1.27.0-2build2` (dpkg) | Upstream v1.27.0 = 2024-09-06; superseded by 1.28.0 (2025-04) and 1.29.0 (2025-11). Debian stable/testing/unstable all still ship 1.27.0-2; Ubuntu 26.04 uses the Debian pin | **Correct/ratified.** This is normal distro lag (matches Debian stable), not an error. 1.27.0 is a build-only release with no API changes, so no behavioral risk vs 1.28/1.29. |
| unittest (stdlib) | `python3 -m unittest discover` is stdlib since 2.1 | — | Correct; no external pin. |
| hidraw via kernel hid-generic | `DRIVER=hid-generic` on the live device (`HID_ID=0003:000024AE:00001413`), `hid_generic` module loaded | hid-generic is core Linux kernel HID; the Rapoo device binds to it because `hid-rapoo.c` does not claim this device | Correct/ratified. |
| udev rule `24ae:1413\|24ae:4613`, `MODE="0664" GROUP="plugdev"` | Installed verbatim at `/etc/udev/rules.d/99-rapoo-vt7.rules` | — | Correct/ratified. Matches spine text exactly. |

## 2. Named technologies vs the Linux/GNOME Wayland desktop context

All four fit the described context and are the correct choices:

- **GTK3 on GNOME Wayland** — GTK 3.24 has a native Wayland backend; a GTK3 app + AppIndicator is the supported path. GNOME does not deprecate GTK3 apps; the stack is consistent with what is already running (the tray works today).
- **AyatanaAppIndicator3** — provides the StatusNotifierItem (SNI) bus protocol that the GNOME Shell `ubuntu-appindicators` extension renders on Wayland (where XEmbed-based legacy indicators do not work). This is the *standard* Wayland-correct mechanism, and it is the actively maintained fork of AppIndicator. Fits perfectly.
- **pycairo** — correct tool for rendering the % + color icon to a PNG `ImageSurface` and caching it. The project's CONTEXT.md already warns that `gi.repository.cairo` does not expose `ImageSurface`, so "pycairo" (`import cairo`) is the precise, correct dependency.
- **direct hidraw via hid-generic** — reality-confirmed: the config interface is bound to `hid-generic` on this machine. Direct `os.open("/dev/hidrawX", O_RDWR|O_NONBLOCK)` is a kernel-blessed, stable API (no third-party lib involved, nothing to go stale). Matches `device.py:127` and the CONTEXT.md decision against python3-hid.

## 3. Out-of-date / unconfirmed dependencies or protocol references

- **No third-party pip dependency is asserted.** The entire Stack is system packages + stdlib — the smallest stale-surface possible. Nothing was found that had not been confirmed against the web, the project, or the running system.
- Referenced spec exists: `_bmad-output/specs/spec-rapoo-vt7/SPEC.md` (plus `phase-map.md`, `stories.yaml`).
- Protocol references (report 6/7, 0xAA, EEPROM addresses, prefix 0xA5/0xFF) are project-ratified facts (CONTEXT.md §3) sourced from the downloaded official A Hub bundle `docs/rapoo_hub_app.js` + live device validation, not training data. No change needed.
- GNOME-extension assumption (`ubuntu-appindicators`) is implicit rather than stated in the spine; it is covered in CONTEXT.md §5 and is the documented prerequisite. If the spine is meant to be self-contained, one sentence naming it as a runtime prerequisite would help — minor.

## 4. Minor notes (non-blocking)

1. **pycairo 1.27.0 currency** — up to three minor releases behind upstream (1.28.0/1.29.0 exist). Correct as the Ubuntu 26.04 / Debian stable pin, and API-identical for the icon use-case, but if a pip-based install is ever introduced, expect 1.29.x.
2. **"AyatanaAppIndicator3 0.1" ambiguity** — 0.1 is the GIR namespace version; the actual library is `libayatana-appindicator 0.5.94`. A reader could mistake "0.1" for the library version. Suggest annotating (e.g. `0.1 (GIR; lib 0.5.94)`).
3. **Python 3.14.4 is not the newest 3.14 patch** (3.14.7 is) — irrelevant for a distro ratification, and 3.14.4 is exactly what the machine runs.

---

## Evidence inventory

- Machine: `python3 --version`, `dpkg-query -W` (python3, python3-gi, python3-cairo, gir1.2-ayatanaappindicator3-0.1, libayatana-appindicator3-1), `Gtk.get_*_version`, `gi.require_version("AyatanaAppIndicator3","0.1")`, `/sys/class/hidraw/hidraw1/device/uevent` (`DRIVER=hid-generic`), `lsmod` (`hid_generic`), `grep` on `/etc/udev/rules.d/99-rapoo-vt7.rules`.
- Web: python.org release 3.14.4 (2026-04-07) & version list (3.14.7 on 2026-08-05); gtk.org ("Latest old stable 3.24.52") + GNOME 3.24.52 NEWS (2026-03-22, maintenance mode); pycairo GitHub releases/PyPI (1.27.0=2024-09-06, 1.28.0, 1.29.0) + Debian tracker (stable 1.27.0-2); conda-forge listing.
- Project: `src/rapoo_vt7/tray.py:6,31,81,110`, `device.py:127`, `main.py:5-78`, `protocol.py:5-8`; `_bmad-output/specs/spec-rapoo-vt7/` exists.

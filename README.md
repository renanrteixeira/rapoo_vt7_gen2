# Rapoo VT7 — Battery in the systray

Battery icon for the GNOME systray with percentage and color
(green ≥50, yellow 20–49, red <20), Android/iOS style,
for the Rapoo VT7 mouse (2.4G receiver, VID/PID 24ae:1413).

Read **CONTEXT.md** first — it is the project resume document
(it contains the deciphered protocol and the current state).

## Installation (once)

```bash
sudo ./install.sh
```

## Run

```bash
./run.sh
```

## Diagnostics / development

```bash
python3 tools/probe.py
```

## Tests

```bash
python3 -m unittest discover -s tests
```

## Uninstall

```bash
./uninstall.sh
```

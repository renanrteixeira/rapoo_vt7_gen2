#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Installing dependencies (sudo)..."
sudo apt-get update
sudo apt-get install -y python3-hid python3-gi gir1.2-ayatanaappindicator3-0.1 python3-gi-cairo

echo "==> Applying udev rule..."
sudo install -m 0644 udev/99-rapoo-vt7.rules /etc/udev/rules.d/99-rapoo-vt7.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

echo "==> Trying to release the current hidraw immediately..."
for h in /sys/class/hidraw/hidraw*; do
  dev="/dev/$(basename "$h")"
  if grep -qiE "HID_ID=.*000024AE" "$h/device/uevent" 2>/dev/null; then
    sudo chmod 0666 "$dev"
    echo "    permission applied to $dev"
  fi
done

echo "==> Generating the app icon (Material, SVG + PNG 48-512)..."
python3 tools/appicon.py

echo "==> Creating the launcher in the applications menu..."
ROOT="$(pwd)"
# Named after the GApplication id (io.rapoo.vt7): GNOME resolves the app name
# (menus, notifications, window) from "<application-id>.desktop".
DESKTOP="${HOME}/.local/share/applications/io.rapoo.vt7.desktop"
mkdir -p "$(dirname "$DESKTOP")"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Rapoo VT7
Name[pt_BR]=Rapoo VT7
Name[en]=Rapoo VT7
Name[es]=Rapoo VT7
GenericName=Tools
GenericName[pt_BR]=Ferramentas
GenericName[es]=Herramientas
Comment=Tools for the Rapoo VT7
Comment[pt_BR]=Ferramentas para o Rapoo VT7
Comment[es]=Herramientas para el Rapoo VT7
Exec=${ROOT}/run.sh
Icon=rapoo-vt7
Terminal=false
StartupNotify=true
Categories=Utility;
EOF
echo "    launcher at ${DESKTOP}"

echo "==> Done. If you still get a permission error, unplug and replug the mouse."

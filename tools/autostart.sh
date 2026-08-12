#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

DESKTOP="${HOME}/.config/autostart/rapoo-vt7.desktop"
mkdir -p "$(dirname "$DESKTOP")"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Rapoo VT7
Comment=Shows the Rapoo VT7 mouse battery in the systray
Exec=${ROOT}/run.sh --hidden
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=5
EOF

echo "Autostart created at ${DESKTOP}"
echo "The app will start automatically on the next login."

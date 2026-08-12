#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_PROC="src.rapoo_vt7.main"

confirm() {
    local msg="$1"
    local reply
    read -r -p "${msg} [y/N] " reply
    case "${reply,,}" in
        y | yes) return 0 ;;
        *) return 1 ;;
    esac
}

if pgrep -f "${APP_PROC}" >/dev/null 2>&1; then
    echo "==> The app is running."
    if confirm "    Stop it before uninstalling?"; then
        pkill -f "${APP_PROC}" || true
        sleep 1
    fi
fi

echo "==> Removing udev rule..."
sudo rm -f /etc/udev/rules.d/99-rapoo-vt7.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw

echo "==> Removing icon cache..."
rm -rf "${HOME}/.cache/rapoo-vt7"

echo "==> Removing autostart (if any)..."
rm -f "${HOME}/.config/autostart/rapoo-vt7.desktop"

echo "==> Removing the launcher from the applications menu..."
rm -f "${HOME}/.local/share/applications/rapoo-vt7.desktop"
rm -f "${HOME}/.local/share/applications/io.rapoo.vt7.desktop"

echo "==> Removing the app icon (hicolor)..."
rm -f "${HOME}/.local/share/icons/hicolor/"*"/apps/rapoo-vt7."*
rm -f "${HOME}/.local/share/icons/hicolor/scalable/apps/rapoo-vt7.svg"
rm -f "$(dirname "$0")/assets/rapoo-vt7.svg"
gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

if confirm "Remove the installed apt packages (python3-hid, pycairo, appindicator...)? (default No)"; then
    echo "==> Removing apt packages (sudo)..."
    sudo apt-get remove --purge -y \
        python3-hid \
        python3-gi \
        python3-gi-cairo \
        python3-cairo \
        gir1.2-ayatanaappindicator3-0.1
fi

echo "==> Uninstall complete."

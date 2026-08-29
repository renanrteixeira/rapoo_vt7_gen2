#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Running from a terminal launched inside the VS Code snap (or another snap)
# injects snap GTK/GLib/libc paths (LOCPATH, GTK_PATH, GSETTINGS_SCHEMA_DIR,
# XDG_* , PYTHONSTARTUP...) that collide with the system python3 and crash it
# with "libpthread.so.0: undefined symbol: __libc_pthread_init". Reset those
# vars to the system defaults so the app runs from any terminal.
for v in LOCPATH GTK_PATH GSETTINGS_SCHEMA_DIR GTK_IM_MODULE_FILE GIO_MODULE_DIR \
         GTK_EXE_PREFIX GI_TYPELIB_PATH XDG_DATA_DIRS XDG_DATA_HOME PYTHONSTARTUP; do
    unset "$v" 2>/dev/null || true
done
export XDG_DATA_DIRS="${XDG_DATA_DIRS_VSCODE_SNAP_ORIG:-/usr/share/ubuntu:/usr/share/gnome:/usr/local/share/:/usr/share/:/var/lib/snapd/desktop}"

exec python3 -m src.rapoo_vt7.main "$@"

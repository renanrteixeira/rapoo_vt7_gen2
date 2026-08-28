import json
import os

from . import i18n

DEFAULT_LANG = "pt_BR"
DEFAULT_THEME = "system"

VALID_THEMES = ("light", "dark", "system")

CONFIG_DIR = os.path.expanduser("~/.config/rapoo-vt7")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_language():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        lang = data.get("language")
        if lang in i18n.LANGS:
            return lang
    except (OSError, ValueError):
        pass
    return DEFAULT_LANG


def save_language(lang):
    _save_setting({"language": lang})


def load_theme():
    """Theme preference ("light"/"dark"/"system"); invalid/missing -> "system"."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        theme = data.get("theme")
        if theme in VALID_THEMES:
            return theme
    except (OSError, ValueError):
        pass
    return DEFAULT_THEME


def save_theme(theme):
    if theme not in VALID_THEMES:
        theme = DEFAULT_THEME
    _save_setting({"theme": theme})


def _save_setting(patch):
    """Merges `patch` into config.json, preserving any other keys
    (language/theme live side by side)."""
    data = {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        pass
    data.update(patch)
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

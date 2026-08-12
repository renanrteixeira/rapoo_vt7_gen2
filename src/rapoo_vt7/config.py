import json
import os

from . import i18n

DEFAULT_LANG = "pt_BR"

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
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"language": lang}, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

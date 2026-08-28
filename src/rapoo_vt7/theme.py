"""Theme system: token table + light/dark/system resolution.

The GTK window is themed through a single stylesheet that branches on a root
style class (``theme-light`` / ``theme-dark``). All colors come from the two
token tables below so both themes stay in sync from one source; they are
injected into the CSS provider as ``@define-color`` so the static
``assets/rapoo-vt7.css`` refers to named colors (``@theme_card_bg`` etc.).
"""

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

DEFAULT_THEME = "system"
VALID_THEMES = ("light", "dark", "system")

# Raíz classes applied to the window root. A single stylesheet branches on
# these so both themes share one source of styling rules.
CLASS_DARK = "theme-dark"
CLASS_LIGHT = "theme-light"

# Token tables (single source of truth). Names map 1:1 to `@theme_*`
# @define-color names injected into the provider.
LIGHT_TOKENS = {
    "bg": "#f4f5f7",
    "fg": "#1f2328",
    "muted": "#6b7280",
    "card_bg": "#ffffff",
    "card_border": "#e2e5e9",
    "accent": "#2c8e3a",
    "accent_soft": "#e8f5e9",
    "danger": "#d93025",
    "danger_soft": "#fdecea",
}

DARK_TOKENS = {
    "bg": "#1b1c1f",
    "fg": "#e6e6e6",
    "muted": "#9ca3af",
    "card_bg": "#24262b",
    "card_border": "#33363c",
    "accent": "#4cc25a",
    "accent_soft": "#1f3323",
    "danger": "#f28b82",
    "danger_soft": "#3a2323",
}

THEME_TOKENS = {
    "light": LIGHT_TOKENS,
    "dark": DARK_TOKENS,
}

# Path to the static stylesheet, resolved relative to this package (repo
# layout: <root>/assets/rapoo-vt7.css) so it also works from an install.
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "assets",
)
BASE_CSS_PATH = os.path.join(ASSETS_DIR, "rapoo-vt7.css")

_base_css_cache = None  # None = not read yet, False = read failed

_TOKEN_LINE = "@define-color theme_{name} {value};"


def base_css():
    """The static stylesheet text (cached; "" on read failure)."""
    global _base_css_cache
    if _base_css_cache is None:
        try:
            with open(BASE_CSS_PATH, encoding="utf-8") as f:
                _base_css_cache = f.read()
        except OSError:
            _base_css_cache = ""
    return _base_css_cache


def sanitize_theme(theme):
    """Coerce an arbitrary config value into a valid theme ("system")."""
    if theme not in VALID_THEMES:
        return DEFAULT_THEME
    return theme


def effective_theme(theme):
    """Resolve "system" into "light"/"dark" using the GTK dark preference.

    Only reads the GTK settings; never mutates anything (pure). Falls back to
    "light" when no GTK settings object is available (headless).
    """
    theme = sanitize_theme(theme)
    if theme != "system":
        return theme
    settings = Gtk.Settings.get_default()
    try:
        if settings is not None and settings.get_property(
            "gtk-application-prefer-dark-theme"
        ):
            return "dark"
    except Exception:
        pass
    return "light"


def apply_theme(window_root, theme):
    """Toggles the theme classes on a window root; returns the effective theme.

    Pure in the sense that it only switches style classes on the given widget
    (no widget construction, no provider). The caller is expected to refresh
    the CSS provider token injection separately when the effective theme
    changes.
    """
    effective = effective_theme(theme)
    ctx = window_root.get_style_context()
    for cls in (CLASS_LIGHT, CLASS_DARK):
        if ctx.has_class(cls):
            ctx.remove_class(cls)
    ctx.add_class(CLASS_DARK if effective == "dark" else CLASS_LIGHT)
    return effective


def build_css(theme):
    """Full CSS string for a theme: token @define-color block + base sheet.

    The tokens define the named ``@theme_*`` colors that ``assets/
    rapoo-vt7.css`` uses, so both themes share the base rules and only the
    token values differ.
    """
    effective = effective_theme(theme)
    tokens = THEME_TOKENS[effective]
    lines = ["/* effective-theme tokens: %s */" % effective]
    for name, value in tokens.items():
        lines.append(_TOKEN_LINE.format(name=name, value=value))
    lines.append("")
    base = base_css()
    if base:
        lines.append(base)
    return "\n".join(lines)


def new_provider(theme):
    """Builds a Gtk.CssProvider loaded with the themed CSS for `theme`."""
    provider = Gtk.CssProvider()
    try:
        provider.load_from_data(build_css(theme).encode("utf-8"))
    except Exception:
        # A malformed/over-aggressive stylesheet must never crash the app:
        # fall back to an empty provider (default GTK look remains).
        provider.load_from_data(b"")
    return provider

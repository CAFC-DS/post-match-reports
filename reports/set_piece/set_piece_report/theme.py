"""Light / dark themes and colour utilities for the report.

The page is driven entirely from a :class:`Theme`: the HTML pulls its CSS custom
properties from it, and every pitch graphic is drawn with its surface / line /
heat colours so the artwork sits on the same paper as the page (cream in light
mode, charcoal in dark mode).

Team bar colours are resolved from the club-colour map in :mod:`config`, with a
contrast guard (teams whose brand colours clash fall back to the theme's
home/away pair) and a dark-mode lift so very dark crests (Swansea, Derby) stay
visible on a dark sheet.
"""

from __future__ import annotations

from dataclasses import dataclass

from set_piece_report.config import (
    CORNER_TYPE_COLORS,
    FK_TYPE_COLORS,
    TEAM_COLORS,
)


# --------------------------------------------------------------------------- #
# Low-level colour maths
# --------------------------------------------------------------------------- #
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _mix(a: str, b: str, t: float) -> str:
    """Blend ``a`` toward ``b`` by fraction ``t`` (0..1)."""
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return _rgb_to_hex((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def lighten(h: str, t: float) -> str:
    return _mix(h, "#FFFFFF", t)


def darken(h: str, t: float) -> str:
    return _mix(h, "#000000", t)


def luminance(h: str) -> float:
    """Perceived relative luminance in 0..1 (sRGB approximation)."""
    r, g, b = (c / 255.0 for c in _hex_to_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_text(bg: str) -> str:
    """Ink or paper text that reads on ``bg``."""
    return "#14171C" if luminance(bg) > 0.55 else "#FFFFFF"


def _distance(a: str, b: str) -> float:
    ra, ga, ba = _hex_to_rgb(a)
    rb, gb, bb = _hex_to_rgb(b)
    return ((ra - rb) ** 2 + (ga - gb) ** 2 + (ba - bb) ** 2) ** 0.5


# --------------------------------------------------------------------------- #
# Theme definition
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Theme:
    name: str
    paper: str
    surface: str
    ink: str
    muted: str
    faint: str
    grid: str
    hair: str
    chip: str          # subtle fill behind legend items
    red: str
    red_dark: str
    green: str
    pitch_surface: str
    pitch_line: str
    heat_stops: tuple[str, ...]
    corner_colors: dict[str, str]
    fk_colors: dict[str, str]
    throw_colors: dict[str, str]
    edge_won: str          # first-contact won  (success)
    edge_lost: str         # first-contact lost
    edge_none: str         # uncontested / short (not grey)
    goal: str              # goal marker (star) fill
    goal_edge: str
    fallback_home: str
    fallback_away: str

    def as_css_vars(self) -> dict[str, str]:
        return {
            "paper": self.paper,
            "surface": self.surface,
            "ink": self.ink,
            "muted": self.muted,
            "faint": self.faint,
            "grid": self.grid,
            "hair": self.hair,
            "chip": self.chip,
            "red": self.red,
            "red_dark": self.red_dark,
            "green": self.green,
        }


LIGHT = Theme(
    name="light",
    paper="#FAF6F0",
    surface="#FFFFFF",
    ink="#1A1A1A",
    muted="#5D6470",
    faint="#8A8578",
    grid="#E8E3D8",
    hair="#EDE7DB",
    chip="#F1EADD",
    red="#D01012",
    red_dark="#A40B0E",
    green="#2D8F6A",
    pitch_surface="#F4EFE4",
    pitch_line="#C4BAA0",
    heat_stops=("#F4EFE4", "#EAD6A6", "#DCA23F", "#C0522B"),
    corner_colors=CORNER_TYPE_COLORS,
    fk_colors={
        "CROSS": "#EE7733",        # a driven cross into the box
        "HIGH_BALL": "#0077BB",    # lofted / high ball from deep
        "SHORT": "#33BBEE",        # short / recycled / kept
        "SHOT": "#AA3377",         # direct free-kick (shot at goal)
        "OTHER": "#B4AA95",
    },
    throw_colors={"BOX_THROW": "#AA3377", "OTHER_THROW": "#7F8891"},
    edge_won="#1F9D57",            # won first contact / possession retained
    edge_lost="#E23B3B",           # lost
    edge_none="#97A0AB",           # uncontested
    goal="#F5C518",
    goal_edge="#1A1A1A",
    fallback_home="#315A7D",
    fallback_away="#D01012",
)

DARK = Theme(
    name="dark",
    paper="#12151B",
    surface="#1A1E26",
    ink="#F2EEE6",
    muted="#A9B0BC",
    faint="#6E7684",
    grid="#2A303A",
    hair="#232935",
    chip="#20262F",
    red="#FF5A5C",
    red_dark="#FF7A7C",
    green="#46C08F",
    pitch_surface="#1B212B",
    pitch_line="#3B4351",
    heat_stops=("#1B212B", "#4E421F", "#9A6E24", "#D9603A"),
    corner_colors={
        "NEAR_POST": "#F59A4E",    # orange
        "CENTRAL": "#4CA6E0",      # blue
        "FAR_POST": "#D06BB0",     # magenta / purple
        "SHORT": "#5BC8F0",        # cyan
    },
    fk_colors={
        "CROSS": "#F59A4E",
        "HIGH_BALL": "#4CA6E0",
        "SHORT": "#5BC8F0",
        "SHOT": "#D06BB0",
        "OTHER": "#B7AE9A",
    },
    throw_colors={"BOX_THROW": "#D06BB0", "OTHER_THROW": "#98A0AA"},
    edge_won="#3FD07E",
    edge_lost="#FF5A5C",
    edge_none="#AAB2BD",
    goal="#FFD34D",
    goal_edge="#12151B",
    fallback_home="#6C9BD1",
    fallback_away="#FF5A5C",
)


def get_theme(name: str) -> Theme:
    return DARK if str(name).lower() == "dark" else LIGHT


# --------------------------------------------------------------------------- #
# Team bar colours
# --------------------------------------------------------------------------- #
_CLASH_THRESHOLD = 90.0     # RGB distance below which two brand colours clash


def _visible(colour: str, theme: Theme) -> str:
    """Nudge a brand colour so it reads on the current paper."""
    lum = luminance(colour)
    if theme.name == "dark":
        # Only lift crests that genuinely disappear on a dark sheet: near-black
        # (Swansea, Derby) toward a light tint, very-dark navies a touch. Leave
        # saturated reds / mid blues alone so they keep their hue.
        if lum < 0.13:
            return lighten(colour, 0.70)
        if lum < 0.20:
            return lighten(colour, 0.25)
        return colour
    # Light mode: pull washed-out colours (Watford / Oxford yellow) down a touch.
    if lum > 0.82:
        return darken(colour, 0.10)
    return colour


def resolve_bar_colors(home_team: str, away_team: str, theme: Theme) -> tuple[str, str]:
    """Return (home, away) bar colours: real club colours where we know them and
    they don't clash, otherwise the theme's home/away fallback pair."""
    home = TEAM_COLORS.get(home_team)
    away = TEAM_COLORS.get(away_team)
    if home is None or away is None or _distance(home, away) < _CLASH_THRESHOLD:
        return theme.fallback_home, theme.fallback_away
    return _visible(home, theme), _visible(away, theme)

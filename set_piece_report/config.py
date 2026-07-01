"""Palette, fixed labels and the set-piece taxonomy for the match report.

Colours are lifted from the ``season_story`` design system (cream paper, charcoal
ink, Charlton red) so the page sits in the same editorial family as the full
season report.

Corners are categorised by the **IMPECT corner type** carried in the data
(``setPieceSubPhaseCornerType``) — near post / central / far post / short —
rather than an inferred swing, so the classification is factual.
"""

from __future__ import annotations

# --- season_story editorial palette -------------------------------------------
PAPER = "#FAF6F0"          # background cream
SURFACE = "#FFFFFF"        # card / pitch surface
INK = "#1A1A1A"            # text charcoal
MUTED = "#5D6470"          # subtle text
GRID = "#E8E3D8"           # hairline grid
RED = "#D01012"            # primary red
RED_DARK = "#A40B0E"
GREEN = "#2D8F6A"          # "above season" accent
BLUE = "#315A7D"           # secondary accent

# Pitch reads as a slightly warmer sheet of the same paper.
PITCH_SURFACE = "#F4EFE4"
PITCH_LINE = "#C4BAA0"     # soft warm grey markings
PITCH_LINE_SOFT = "#DBD2BC"

# Per-team bar colours (home = blue, away = red) echo the example layout.
HOME_BAR = BLUE
AWAY_BAR = RED

# --- corner taxonomy (IMPECT setPieceSubPhaseCornerType) ----------------------
CORNER_SHORT = "SHORT"
CORNER_NEAR = "NEAR_POST"
CORNER_CENTRAL = "CENTRAL"
CORNER_FAR = "FAR_POST"

CORNER_TYPE_LABELS = {
    CORNER_NEAR: "Near post",
    CORNER_CENTRAL: "Central",
    CORNER_FAR: "Far post",
    CORNER_SHORT: "Short",
}
CORNER_TYPE_COLORS = {
    CORNER_NEAR: "#D8A21B",       # gold
    CORNER_CENTRAL: "#2E8C86",    # teal
    CORNER_FAR: "#C0392B",        # brick red
    CORNER_SHORT: "#7F8DA3",      # muted blue-grey
}
# Legend / draw order, near-post first (most common threatening delivery).
CORNER_TYPE_ORDER = [CORNER_NEAR, CORNER_CENTRAL, CORNER_FAR, CORNER_SHORT]

# Map raw IMPECT corner-type values onto the taxonomy above.
IMPECT_CORNER_TYPE_MAP = {
    "CORNER_NEAR_POST": CORNER_NEAR,
    "CORNER_CENTRAL": CORNER_CENTRAL,
    "CORNER_FAR_POST": CORNER_FAR,
    "CORNER_OPEN_PLAY": CORNER_SHORT,
}

# --- free-kick delivery taxonomy ---------------------------------------------
FK_TYPE_COLORS = {
    "CROSS": "#D8A21B",           # cross / high ball into the box
    "HIGH_BALL": "#2E8C86",       # high ball (not directly into box)
    "INTO_POSSESSION": "#7F8DA3",   # recycled / kept in possession
    "OTHER": MUTED,
}

# IMPECT category constants ----------------------------------------------------
CORNER_CATEGORIES = ("CORNER_LEFT", "CORNER_RIGHT")
FREE_KICK_CATEGORY = "FREE_KICK"
THROW_IN_CATEGORY = "THROW_IN"
FREE_KICK_SHOT_TYPE = "FREE_KICK_SHOT"
DIRECT_FREE_KICK_ACTION = "DIRECT_FREE_KICK"

# Regular-season cut-off (playoffs excluded from the per-90 baselines).
REGULAR_SEASON_CUTOFF = "2026-05-04"

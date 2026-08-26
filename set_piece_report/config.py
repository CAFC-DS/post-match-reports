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

# Per-team bar colours (home = blue, away = red) — the neutral fallback pair
# used when a club isn't in ``TEAM_COLORS`` or two brands clash. Real club
# colours (below) are preferred; see ``theme.resolve_bar_colors``.
HOME_BAR = BLUE
AWAY_BAR = RED

# Primary brand colour per Championship 25/26 club, used for the stat bars so a
# fixture reads in its own colours. Kept mid-tone where possible; ``theme`` lifts
# very dark crests for dark mode and guards against same-match clashes.
TEAM_COLORS = {
    "AFC Wrexham": "#D50032",
    "Birmingham City": "#20438A",
    "Blackburn Rovers": "#009FE3",
    "Bristol City": "#E30613",
    "Charlton Athletic": "#D01012",
    "Coventry City": "#6CADDF",
    "Derby County": "#1C1C1C",
    "FC Middlesbrough": "#E11B38",
    "FC Millwall": "#00285E",
    "FC Portsmouth": "#001489",
    "FC Southampton": "#D71920",
    "FC Watford": "#E8B900",
    "Hull City": "#F5A12D",
    "Ipswich Town": "#16478E",
    "Leicester City": "#0053A0",
    "Norwich City": "#00A94F",
    "Oxford United": "#E4A400",
    "Preston North End": "#0B3D7B",
    "Queens Park Rangers": "#005CAB",
    "Sheffield United": "#EE2737",
    "Sheffield Wednesday": "#0060A9",
    "Stoke City": "#E03A3E",
    "Swansea City": "#1A1A1A",
    "West Bromwich Albion": "#0B2265",
}

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
# Landing-zone colours: a colourblind-safe categorical set (Paul Tol "vibrant"),
# deliberately avoiding red/green — those are reserved for the first-contact
# outcome ring (won / lost) so the two channels never clash.
CORNER_TYPE_COLORS = {
    CORNER_NEAR: "#EE7733",       # orange
    CORNER_CENTRAL: "#0077BB",    # blue
    CORNER_FAR: "#AA3377",        # magenta / purple
    CORNER_SHORT: "#33BBEE",      # cyan
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

# IMPECT identifies throw-ins but does not provide a native long-throw subtype.
# Keep this taxonomy aligned with the pre-match set-piece report: provider start
# zone is authoritative, with endpoint geometry and a 45 m plausibility ceiling.
BOX_THROW = "BOX_THROW"
OTHER_THROW = "OTHER_THROW"
ANOMALY_THROW = "ANOMALY"
THROW_BOX_MIN_X = 34.5
THROW_BOX_MAX_ABS_Y = 22.0
THROW_MAX_DISTANCE = 45.0
THROW_BOX_START_ZONES = frozenset({
    "LEFT_WING_BESIDES_BOX", "RIGHT_WING_BESIDES_BOX",
    "LEFT_WING_IN_FRONT_OF_BOX", "RIGHT_WING_IN_FRONT_OF_BOX",
    "LEFT_CORNER", "RIGHT_CORNER",
})
FREE_KICK_SHOT_TYPE = "FREE_KICK_SHOT"
DIRECT_FREE_KICK_ACTION = "DIRECT_FREE_KICK"

# Regular-season cut-off (playoffs excluded from the per-90 baselines).
REGULAR_SEASON_CUTOFF = "2026-05-04"

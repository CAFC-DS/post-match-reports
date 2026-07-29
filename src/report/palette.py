"""Colour and type tokens, lifted directly from the season-review design
system (full-season-analysis/report_templates/styles/design_system.css) so
this report sits in the same visual family as the club's other board-facing
output. Do not invent new colours here — extend the source stylesheet first
if a new token is genuinely needed.
"""

from __future__ import annotations

# --- paper / ink -------------------------------------------------------------
PAPER = "#f3eee1"
PAPER_2 = "#efe8d8"
INK = "#1a1a18"
MUTED = "#6f6a5d"
FAINT = "#918b7c"
HAIR = "#cfc7b4"
HAIR_SOFT = "#ded6c4"
TINT = "#eae2d0"

# --- club colour convention (applied consistently everywhere: tables, maps,
# charts, leaderboards) -------------------------------------------------------
CHARLTON_RED = "#d01012"
CHARLTON_RED_DARK = "#a00d0f"
OPPONENT_GREY = "#7d7869"
OPPONENT_GREY_LIGHT = "#a39d8f"

# --- action-outcome semantics (pass/entry maps) -------------------------------
SUCCESS_GREEN = "#5c7a4a"
FAIL_REDGREY = "#a8685f"

# --- accent -------------------------------------------------------------------
AMBER = "#c0892d"

# --- passing-network node colour: net packing threat added by a player's own
# passes (PXT_PASS), diverging around a neutral zero. Local to this report —
# the season-review sheet has no equivalent metric — following the same
# local-extension pattern as OPPONENT_GREY / FAIL_REDGREY above. Deliberately
# not red/green: on the CVD (colour-blindness) check, the pale ends of a
# literal red-green ramp — where most players land — collapse to the same
# colour under deuteranopia (ΔE 0.5, against a target of 12). Purple/green
# clears that check on every pair while keeping the same "gave it back" vs
# "created it" read; the midpoint reuses OPPONENT_GREY rather than a new tone.
THREAT_LOW = "#6d3f83"
THREAT_LOW_LIGHT = "#a479b8"
THREAT_MID = OPPONENT_GREY
THREAT_HIGH_LIGHT = "#7fa066"
THREAT_HIGH = "#4f6b3e"

# --- type ----------------------------------------------------------------------
FONT_DISPLAY = "'Playfair Display', Georgia, 'Times New Roman', serif"
FONT_TEXT = "'Spectral', 'Iowan Old Style', Georgia, serif"
FONT_SANS = "'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', sans-serif"


def team_color(team: str, charlton_name: str = "Charlton Athletic") -> str:
    """Charlton always red, any opponent always the same neutral grey."""
    return CHARLTON_RED if team == charlton_name else OPPONENT_GREY

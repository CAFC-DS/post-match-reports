"""Output filenames for the generated post-match reports.

Names read from Charlton's point of view, e.g.
``Post Match Report - Derby County (H).pdf``.
"""
from __future__ import annotations

import re

CHARLTON = "Charlton Athletic"

BOARD = "Post Match Report"
ANALYST = "Analyst Post Match Report"
SET_PIECE = "Post Match Set Piece Report"


def _clean(value: str) -> str:
    # Keep names filesystem-safe (no slashes, colons, etc.) but leave spaces.
    return re.sub(r"\s+", " ", re.sub(r'[\\/:*?"<>|]+', " ", value)).strip()


def report_stem(kind: str, home_team: str, away_team: str) -> str:
    """``<kind> - <Opponent> (H|A)`` from Charlton's perspective."""
    charlton_home = home_team == CHARLTON
    opponent = away_team if charlton_home else home_team
    return f"{kind} - {_clean(opponent)} ({'H' if charlton_home else 'A'})"

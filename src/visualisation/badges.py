"""Club-badge helper. Maps team names to badge images and produces base64 data URIs.

Badges live under ``assets/badges/``. Vendored from set-piece-report's
``src/visualisation/badges.py`` (same mapping table, same encoding approach);
trimmed to the clubs this project has badge files for so far.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path


BADGE_DIR = Path(__file__).resolve().parents[2] / "assets" / "badges"


TEAM_BADGE_FILES: dict[str, str] = {
    "AFC Wrexham": "Wrexham_A.F.C._Logo.svg.png",
    "Birmingham City": "Birmingham-City.png",
    "Blackburn Rovers": "Blackburn_Rovers.svg.png",
    "Bolton Wanderers": "Bolton_Wanderers_FC_logo.svg.png",
    "Bristol City": "Bristol_City_crest.png",
    "Cardiff City": "Cardiff_City_crest.svg.png",
    "Charlton Athletic": "Charlton Logo.png",
    "Coventry City": "Coventry_City_FC_crest.svg.png",
    "Derby County": "Derby_County_crest.svg.png",
    "FC Burnley": "Burnley_FC_Logo.svg.png",
    "FC Middlesbrough": "Middlesbrough_FC_crest.svg.png",
    "FC Millwall": "Millwall_FC_crest.svg.png",
    "FC Portsmouth": "Portsmouth_FC_logo.svg.png",
    "FC Southampton": "FC_Southampton.svg.png",
    "FC Watford": "Watford.svg.png",
    "Hull City": "Hull_City_A.F.C._logo.svg.png",
    "Ipswich Town": "Ipswich_Town.svg.png",
    "Leicester City": "Leicester_City_crest.svg.png",
    "Lincoln City": "Lincoln_City_FC_2024_crest.svg.png",
    "Norwich City": "Norwich_City.png",
    "Oxford United": "Oxford_United_FC_logo.svg.png",
    "Preston North End": "Preston_North_End_FC.svg.png",
    "Queens Park Rangers": "Queens_Park_Rangers_crest.svg.png",
    "Sheffield United": "Sheffield_United_FC_logo.svg.png",
    "Sheffield Wednesday": "Sheffield_Wednesday_badge.svg.png",
    "Stoke City": "Stoke_City_FC.svg.png",
    "Swansea City": "Swansea_City_A.F.C._logo.png",
    "Tottenham Hotspur": "Tottenham_Hotspur.png",
    "West Bromwich Albion": "West_Bromwich_Albion.svg.png",
    "West Ham United": "West_Ham_United_FC_logo.svg.png",
    "Wolverhampton Wanderers": "Wolverhampton_Wanderers.svg.png",
}


def badge_path(team_name: str) -> Path | None:
    filename = TEAM_BADGE_FILES.get(team_name)
    if not filename:
        return None
    path = BADGE_DIR / filename
    return path if path.exists() else None


@lru_cache(maxsize=64)
def badge_data_uri(team_name: str) -> str | None:
    """Return a base64-encoded data URI of the badge, or None if missing."""
    path = badge_path(team_name)
    if path is None:
        return None
    try:
        data = path.read_bytes()
    except OSError:
        return None
    suffix = path.suffix.lower().lstrip(".")
    mime = "png" if suffix == "png" else suffix
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"

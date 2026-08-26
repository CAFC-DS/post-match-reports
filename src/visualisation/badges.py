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
    "Charlton Athletic": "Charlton Logo.png",
    "Swansea City": "Swansea_City_A.F.C._logo.png",
    "Derby County": "Derby_County_crest.svg.png",
    "FC Southampton": "FC_Southampton.svg.png",
    "Stoke City": "Stoke_City_FC.svg.png",
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

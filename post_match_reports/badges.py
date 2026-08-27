"""Load the monorepo's canonical badge resolver under an unambiguous name."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_PATH = Path(__file__).resolve().parents[1] / "src" / "visualisation" / "badges.py"
_SPEC = importlib.util.spec_from_file_location("_cafc_canonical_badges", _PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - installation failure
    raise ImportError(f"Cannot load badge resolver from {_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

badge_data_uri = _MODULE.badge_data_uri
badge_path = _MODULE.badge_path
TEAM_BADGE_FILES = _MODULE.TEAM_BADGE_FILES

"""Shared local cache for DVMS match data.

Tracking files are ~450MB raw per match and the four report repos all vendor
this package, so the cache lives *outside* any repo — one copy per match,
shared by every consumer: ``~/.cache/cafc-dvms/<OPTA_MATCH_ID>/`` (override
the root with ``CAFC_DVMS_CACHE``). Raw pulls and derived parquet artifacts
sit side by side under the match directory:

    <root>/<match_id>/f24.xml            raw Opta F24 (ASSETS.RAW_PAYLOAD)
    <root>/<match_id>/f7.xml             raw Opta F7
    <root>/<match_id>/ss_meta.json       Second Spectrum metadata
    <root>/<match_id>/physical_summary.csv
    <root>/<match_id>/physical_splits.csv
    <root>/<match_id>/tracking.jsonl.gz  positional feed (from the stage)
    <root>/<match_id>/frames_5hz.parquet ... derived artifacts (preprocess.py)
"""

from __future__ import annotations

import os
from pathlib import Path

# Filenames per asset subtype (see the DVMS handover for the subtype table).
SUBTYPE_FILENAMES = {
    20: "f24.xml",
    21: "f7.xml",
    40: "ss_meta.json",
    42: "physical_splits.csv",
    43: "physical_summary.csv",
}
TRACKING_FILENAME = "tracking.jsonl.gz"


def cache_root() -> Path:
    root = os.environ.get("CAFC_DVMS_CACHE")
    return Path(root).expanduser() if root else Path.home() / ".cache" / "cafc-dvms"


def match_dir(opta_match_id: str, create: bool = True) -> Path:
    # The id sometimes arrives in its padded "g2566913" form; store bare.
    match_id = str(opta_match_id).lstrip("g")
    d = cache_root() / match_id
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def cached_path(opta_match_id: str, subtype: int) -> Path:
    return match_dir(opta_match_id) / SUBTYPE_FILENAMES[subtype]


def tracking_path(opta_match_id: str) -> Path:
    return match_dir(opta_match_id) / TRACKING_FILENAME


def cache_status() -> list[dict]:
    """One row per cached match: which files exist and their sizes (bytes)."""
    root = cache_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        files = {p.name: p.stat().st_size for p in d.iterdir() if p.is_file()}
        out.append({"match_id": d.name, "files": files,
                    "total_bytes": sum(files.values())})
    return out

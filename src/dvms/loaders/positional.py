"""Positional tracking retrieval from the Snowflake internal stage.

The tracking feed is far too big for a table cell — it lives gzip-compressed
in ``@DVMS_RAW.POSITIONAL_STAGE`` at a path matching the asset's
``ASSET_KEY``. One ``GET`` per match (~28MB compressed) into the shared
cache; later calls read from disk.
"""

from __future__ import annotations

from pathlib import Path

from . import cache
from . import snowflake_source as sf

_TRACKING_SUBTYPE = 38


def fetch_tracking(fixture_id: str, opta_match_id: str,
                   refresh: bool = False, env_path: str = ".env") -> Path:
    """Return the local path of the match's gzipped tracking JSONL."""
    dest = cache.tracking_path(opta_match_id)
    if dest.is_file() and not refresh:
        return dest

    df = sf.query(
        f"""
        select ASSET_KEY
        from {sf.assets_table()}
        where FIXTURE_ID = %(fixture_id)s
          and ASSET_SUBTYPE = %(subtype)s
          and STAGED_AT is not null
        order by LOADED_AT desc
        limit 1
        """,
        {"fixture_id": fixture_id, "subtype": _TRACKING_SUBTYPE},
        env_path=env_path,
    )
    if df.empty:
        raise LookupError(
            f"no staged tracking file for fixture {fixture_id}. Stage it with: "
            "python -m python.extract.dvms.load_dvms_positional "
            f"--fixture-id {fixture_id}  (in cafc-data-platform)"
        )
    asset_key = str(df.iloc[0, 0])
    got = sf.get_staged_file(asset_key, dest.parent, env_path=env_path)
    got.rename(dest)
    return dest

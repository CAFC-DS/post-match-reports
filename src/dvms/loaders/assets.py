"""Inline asset retrieval (F24/F7/metadata/physical CSVs) with disk cache.

The small per-match files live inline in ``ASSETS.RAW_PAYLOAD``; the first
fetch writes them into the shared cache directory and later calls read from
disk without touching Snowflake. ``refresh=True`` forces a repull.
"""

from __future__ import annotations

from . import cache
from . import snowflake_source as sf


def fetch_asset_text(fixture_id: str, opta_match_id: str, subtype: int,
                     refresh: bool = False, env_path: str = ".env") -> str:
    path = cache.cached_path(opta_match_id, subtype)
    if path.is_file() and not refresh:
        return path.read_text()

    df = sf.query(
        f"""
        select RAW_PAYLOAD
        from {sf.assets_table()}
        where FIXTURE_ID = %(fixture_id)s
          and ASSET_SUBTYPE = %(subtype)s
          and RAW_PAYLOAD is not null
        order by LOADED_AT desc
        limit 1
        """,
        {"fixture_id": fixture_id, "subtype": subtype},
        env_path=env_path,
    )
    if df.empty:
        raise LookupError(
            f"no inline asset of subtype {subtype} for fixture {fixture_id} — "
            "was the fixture loaded with asset download enabled?"
        )
    text = str(df.iloc[0, 0])
    path.write_text(text)
    return text

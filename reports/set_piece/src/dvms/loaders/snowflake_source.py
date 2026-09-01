"""Snowflake access for the DVMS_RAW schema.

Reuses the repo's vendored ``SnowflakeConnector`` (same ``.env``, same auth);
every query names ``CAFC_DB.DVMS_RAW`` objects fully-qualified, so the
connection's default database/schema (set for the IMPECT tables) never
matters. Override the database name with ``DVMS_DATABASE`` if the platform
ever moves it.

The DVMS_RAW grants live on ``DEV_ROLE`` (see the handover), which is not
necessarily the role the repo's ``.env`` connects with for the IMPECT
tables — each session switches to ``DVMS_ROLE`` (default ``DEV_ROLE``)
before querying.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from ...db.snowflake_connection import SnowflakeConnector


def _db() -> str:
    return os.environ.get("DVMS_DATABASE", "CAFC_DB")


def _role() -> str:
    return os.environ.get("DVMS_ROLE", "DEV_ROLE")


def _warehouse() -> str:
    # Deliberately NOT falling back to SNOWFLAKE_WAREHOUSE: that's the IMPECT
    # connection's warehouse, which DEV_ROLE has no grant on.
    return os.environ.get("DVMS_WAREHOUSE", "DEVELOPMENT_WH")


def _use_context(cur) -> None:
    cur.execute(f"USE ROLE {_role()}")
    cur.execute(f"USE WAREHOUSE {_warehouse()}")


def fixtures_table() -> str:
    # DVMS_RAW.FIXTURES is append-only: a fixture gets a pre-match row (null
    # score) and later a post-match row (final score), so it is NOT one row
    # per FIXTURE_ID. Read the deduped staging view instead -- same columns
    # and types, guaranteed one latest row per FIXTURE_ID. Override with
    # DVMS_FIXTURES_RELATION to fall back to raw.
    return os.environ.get(
        "DVMS_FIXTURES_RELATION", f"{_db()}.DVMS_RAW_STAGING.STG_DVMS__FIXTURES"
    )


def assets_table() -> str:
    return f"{_db()}.DVMS_RAW.ASSETS"


def positional_stage() -> str:
    return f"@{_db()}.DVMS_RAW.POSITIONAL_STAGE"


def connector(env_path: str = ".env") -> SnowflakeConnector:
    return SnowflakeConnector(env_path=env_path)


def query(sql: str, params: dict | None = None,
          env_path: str = ".env") -> pd.DataFrame:
    with connector(env_path).connection() as conn:
        with conn.cursor() as cur:
            _use_context(cur)
            cur.execute(sql, params or {})
            try:
                return cur.fetch_pandas_all()
            except Exception:
                rows = cur.fetchall()
                columns = [d[0] for d in (cur.description or [])]
                return pd.DataFrame(rows, columns=columns)


def get_staged_file(asset_key: str, dest_dir: Path, env_path: str = ".env") -> Path:
    """``GET`` one staged positional file into ``dest_dir``.

    Snowflake appends ``.gz`` on auto-compressed files; the caller shouldn't
    care, so the newest file in ``dest_dir`` after the GET is returned.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    before = set(dest_dir.iterdir())
    with connector(env_path).connection() as conn:
        with conn.cursor() as cur:
            _use_context(cur)
            cur.execute(f"GET {positional_stage()}/{asset_key} file://{dest_dir}/")
    new_files = [p for p in dest_dir.iterdir() if p not in before]
    if not new_files:
        raise FileNotFoundError(
            f"GET {positional_stage()}/{asset_key} produced no file in {dest_dir}"
        )
    return max(new_files, key=lambda p: p.stat().st_mtime)

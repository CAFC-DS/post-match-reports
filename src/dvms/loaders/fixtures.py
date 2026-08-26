"""Fixture discovery against ``DVMS_RAW.FIXTURES``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from . import snowflake_source as sf


@dataclass
class FixtureRef:
    fixture_id: str          # DVMS document id — the ASSETS join key
    opta_match_id: str       # bare numeric, e.g. "2566913"
    match_date: pd.Timestamp
    home_team: str
    away_team: str
    home_score: Optional[int]
    away_score: Optional[int]


def list_fixtures(env_path: str = ".env") -> pd.DataFrame:
    """Every loaded fixture, newest first."""
    return sf.query(
        f"""
        select FIXTURE_ID, OPTA_MATCH_ID, MATCH_DATE,
               HOME_TEAM_NAME, AWAY_TEAM_NAME, HOME_SCORE, AWAY_SCORE
        from {sf.fixtures_table()}
        order by MATCH_DATE desc
        """,
        env_path=env_path,
    )


def _to_ref(row: pd.Series) -> FixtureRef:
    return FixtureRef(
        fixture_id=str(row["FIXTURE_ID"]),
        opta_match_id=str(row["OPTA_MATCH_ID"]).lstrip("g"),
        match_date=pd.Timestamp(row["MATCH_DATE"]),
        home_team=str(row["HOME_TEAM_NAME"]),
        away_team=str(row["AWAY_TEAM_NAME"]),
        home_score=int(row["HOME_SCORE"]) if pd.notna(row["HOME_SCORE"]) else None,
        away_score=int(row["AWAY_SCORE"]) if pd.notna(row["AWAY_SCORE"]) else None,
    )


def resolve_fixture(opta_match_id: str, env_path: str = ".env") -> FixtureRef:
    """Look one fixture up by its Opta match id (bare or ``g``-prefixed)."""
    match_id = str(opta_match_id).lstrip("g")
    df = list_fixtures(env_path)
    hits = df[df["OPTA_MATCH_ID"].astype(str).str.lstrip("g") == match_id]
    if hits.empty:
        loaded = ", ".join(df["OPTA_MATCH_ID"].astype(str).str.lstrip("g"))
        raise LookupError(
            f"Opta match id {match_id!r} is not loaded in DVMS_RAW. "
            f"Loaded fixtures: {loaded}. To load more, run the extractor in "
            "cafc-data-platform (see the DVMS handover, §8)."
        )
    return _to_ref(hits.iloc[0])

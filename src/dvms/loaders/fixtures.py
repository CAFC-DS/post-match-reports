"""Fixture discovery against ``DVMS_RAW.FIXTURES``."""

from __future__ import annotations

from dataclasses import dataclass
import re
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


def normalize_team_name(name: str) -> str:
    """Normalize harmless provider spelling differences, not team identity."""
    words = re.sub(r"[^a-z0-9]+", " ", str(name).lower()).split()
    return " ".join(word for word in words if word not in {"fc", "afc"})


def resolve_fixture_for_match(home_team: str, away_team: str, match_date,
                              env_path: str = ".env") -> FixtureRef | None:
    """Resolve one exact home/away/date DVMS fixture.

    A date with no DVMS fixture is normal and returns ``None``. A date that
    has loaded fixtures but no exact identity match is treated as a mapping
    problem and fails loudly; multiple exact matches are also ambiguous.
    """
    fixtures = list_fixtures(env_path)
    target_date = pd.Timestamp(match_date).date()
    dates = pd.to_datetime(fixtures["MATCH_DATE"]).dt.date
    same_date = fixtures.loc[dates == target_date]
    if same_date.empty:
        return None

    home_key = normalize_team_name(home_team)
    away_key = normalize_team_name(away_team)
    exact = same_date.loc[
        same_date["HOME_TEAM_NAME"].map(normalize_team_name).eq(home_key)
        & same_date["AWAY_TEAM_NAME"].map(normalize_team_name).eq(away_key)
    ]
    if len(exact) == 1:
        return _to_ref(exact.iloc[0])

    candidates = ", ".join(
        f"{str(row.OPTA_MATCH_ID).lstrip('g')} ({row.HOME_TEAM_NAME} v {row.AWAY_TEAM_NAME})"
        for row in same_date.itertuples()
    )
    if exact.empty:
        raise LookupError(
            f"DVMS fixtures exist on {target_date}, but none matches "
            f"{home_team} v {away_team}. Candidates: {candidates}"
        )
    exact_ids = ", ".join(str(value).lstrip("g") for value in exact["OPTA_MATCH_ID"])
    raise LookupError(
        f"Multiple DVMS fixtures match {home_team} v {away_team} on "
        f"{target_date}: {exact_ids}. Supply --dvms-match-id explicitly."
    )

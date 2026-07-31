"""Loads SkillCorner physical summary data for one fixture from
``CAFC_DB.SKILLCORNER_RAW.PHYSICAL_SUMMARY``.

There is no shared match or player id between SkillCorner and Impect in this
codebase, so the fixture is located by (kickoff date, team names) — the same
identity ``_assert_same_fixture`` already leans on for Impect/DVMS — and rows
are returned keyed by team + surname for ``blended_player_contributions`` to
join on, matching its existing (team, surname) convention for DVMS physical
data.

Confirmed live (2026-07-31): the account's default role (``ACCOUNTADMIN`` in
``.env``) has SELECT on this table (granted this session; it did not before).
No ``USE ROLE`` switch needed, unlike ``impect_cafcdb_source``'s ``DEV_ROLE``.
"""

from __future__ import annotations

import pandas as pd

from src.db.snowflake_connection import SnowflakeConnector

_PHYSICAL_SQL = """
select
    "PLAYER" as player,
    "TEAM" as team,
    "MINUTES" as minutes,
    "DISTANCE" as distance,
    "HSR_DISTANCE" as hsr_distance,
    "SPRINT_DISTANCE" as sprint_distance
from CAFC_DB.SKILLCORNER_RAW.PHYSICAL_SUMMARY
where "DATE" = %(match_date)s
  and "TEAM" in (%(home_team)s, %(away_team)s)
  and "PHYSICAL_CHECK_PASSED"
"""


def load_physical_summary(match_date: str, home_team: str, away_team: str,
                           env_path: str = ".env") -> pd.DataFrame:
    """SkillCorner physical rows for one fixture, one row per player who
    passed SkillCorner's own physical data quality check.

    ``match_date`` is ``YYYY-MM-DD``. Team names must match SkillCorner's own
    spelling (confirmed identical to Impect's for Charlton fixtures: "Charlton
    Athletic", "Swansea City", etc. -- not re-derived here, since DVMS/Impect
    reconciliation already happens upstream in ``_assert_same_fixture``).
    """
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(_PHYSICAL_SQL, {
            "match_date": match_date,
            "home_team": home_team,
            "away_team": away_team,
        })
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    df.columns = [c.lower() for c in df.columns]
    if df.empty:
        return df
    for col in ("minutes", "distance", "hsr_distance", "sprint_distance"):
        df[col] = df[col].astype(float)
    df["_team_key"] = df["team"].str.strip().str.lower()
    df["_name_key"] = df["player"].str.split().str[-1].str.lower()
    df = df.drop_duplicates(subset=["_team_key", "_name_key"])
    return df

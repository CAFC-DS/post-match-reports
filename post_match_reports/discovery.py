from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass

import pandas as pd

from src.db.snowflake_connection import SnowflakeConnector
from src.dvms.loaders import snowflake_source as dvms_sf
from src.dvms.loaders.fixtures import FixtureRef, list_fixtures, normalize_team_name


_CANDIDATES_SQL = """
select
    m.ID as MATCH_ID,
    m.SCHEDULEDDATE as KICKOFF_UTC,
    hs.NAME as HOME_TEAM,
    aws.NAME as AWAY_TEAM,
    count(e.EVENT_ID) as EVENT_COUNT,
    sum(case when e.ACTION = 'GOAL' and e.SQUAD_ID = m.HOMESQUADID then 1 else 0 end)
      + sum(case when e.ACTION = 'OWN_GOAL' and e.SQUAD_ID = m.AWAYSQUADID then 1 else 0 end)
      as HOME_GOALS,
    sum(case when e.ACTION = 'GOAL' and e.SQUAD_ID = m.AWAYSQUADID then 1 else 0 end)
      + sum(case when e.ACTION = 'OWN_GOAL' and e.SQUAD_ID = m.HOMESQUADID then 1 else 0 end)
      as AWAY_GOALS
from CAFC_DB.IMPECT_RAW.MATCHES m
join CAFC_DB.IMPECT_RAW.SQUADS hs
  on hs.ID = m.HOMESQUADID and hs.ITERATION_ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS aws
  on aws.ID = m.AWAYSQUADID and aws.ITERATION_ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.EVENTS e on e.MATCH_ID = m.ID
where (lower(hs.NAME) like %(team_pattern)s or lower(aws.NAME) like %(team_pattern)s)
  and m.SCHEDULEDDATE <= dateadd(hour, -3, current_timestamp())
group by m.ID, m.SCHEDULEDDATE, hs.NAME, aws.NAME, m.HOMESQUADID, m.AWAYSQUADID
order by m.SCHEDULEDDATE desc
"""

_REQUIRED_INLINE_SUBTYPES = frozenset({20, 21, 40, 43})
_TRACKING_SUBTYPE = 38


@dataclass(frozen=True)
class ReadyFixture:
    impect_match_id: int
    dvms_match_id: str
    fixture_id: str
    kickoff_utc: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int

    def to_dict(self) -> dict:
        return asdict(self)


def _candidate_rows(team: str, env_path: str = ".env") -> pd.DataFrame:
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute("USE ROLE DEV_ROLE")
        cur.execute("USE WAREHOUSE DEVELOPMENT_WH")
        cur.execute(_CANDIDATES_SQL, {"team_pattern": f"%{team.lower()}%"})
        rows = cur.fetchall()
        columns = [item[0] for item in cur.description]
    return pd.DataFrame(rows, columns=columns)


def _matching_dvms(row: pd.Series, fixtures: pd.DataFrame) -> FixtureRef | None:
    target_date = pd.Timestamp(row["KICKOFF_UTC"]).date()
    same_date = fixtures.loc[pd.to_datetime(fixtures["MATCH_DATE"]).dt.date == target_date]
    home = normalize_team_name(row["HOME_TEAM"])
    away = normalize_team_name(row["AWAY_TEAM"])
    exact = same_date.loc[
        same_date["HOME_TEAM_NAME"].map(normalize_team_name).eq(home)
        & same_date["AWAY_TEAM_NAME"].map(normalize_team_name).eq(away)
    ]
    if len(exact) != 1:
        return None
    match = exact.iloc[0]
    if pd.isna(match["HOME_SCORE"]) or pd.isna(match["AWAY_SCORE"]):
        return None
    return FixtureRef(
        fixture_id=str(match["FIXTURE_ID"]),
        opta_match_id=str(match["OPTA_MATCH_ID"]).lstrip("g"),
        match_date=pd.Timestamp(match["MATCH_DATE"]),
        home_team=str(match["HOME_TEAM_NAME"]),
        away_team=str(match["AWAY_TEAM_NAME"]),
        home_score=int(match["HOME_SCORE"]),
        away_score=int(match["AWAY_SCORE"]),
    )


def _dvms_assets_ready(fixture_id: str, env_path: str = ".env") -> bool:
    assets = dvms_sf.query(
        f"""
        select ASSET_SUBTYPE, RAW_PAYLOAD is not null as HAS_PAYLOAD,
               STAGED_AT is not null as IS_STAGED
        from {dvms_sf.assets_table()}
        where FIXTURE_ID = %(fixture_id)s
          and ASSET_SUBTYPE in (20, 21, 38, 40, 43)
        """,
        {"fixture_id": fixture_id},
        env_path=env_path,
    )
    if assets.empty:
        return False
    inline = {
        int(row.ASSET_SUBTYPE)
        for row in assets.itertuples()
        if int(row.ASSET_SUBTYPE) in _REQUIRED_INLINE_SUBTYPES and bool(row.HAS_PAYLOAD)
    }
    tracking = any(
        int(row.ASSET_SUBTYPE) == _TRACKING_SUBTYPE and bool(row.IS_STAGED)
        for row in assets.itertuples()
    )
    return inline == _REQUIRED_INLINE_SUBTYPES and tracking


def discover_latest_ready(
    team: str = "Charlton Athletic",
    not_before: dt.date | None = None,
    env_path: str = ".env",
) -> ReadyFixture | None:
    """Return the newest completed fixture with every production input ready."""
    candidates = _candidate_rows(team, env_path)
    fixtures = list_fixtures(env_path)
    team_key = normalize_team_name(team)
    for _, row in candidates.iterrows():
        kickoff = pd.Timestamp(row["KICKOFF_UTC"])
        if not_before and kickoff.date() < not_before:
            continue
        teams = {normalize_team_name(row["HOME_TEAM"]), normalize_team_name(row["AWAY_TEAM"])}
        if team_key not in teams or int(row["EVENT_COUNT"]) == 0:
            continue
        dvms = _matching_dvms(row, fixtures)
        if dvms is None or not _dvms_assets_ready(dvms.fixture_id, env_path):
            continue
        return ReadyFixture(
            impect_match_id=int(row["MATCH_ID"]),
            dvms_match_id=dvms.opta_match_id,
            fixture_id=dvms.fixture_id,
            kickoff_utc=kickoff.isoformat(),
            home_team=str(row["HOME_TEAM"]),
            away_team=str(row["AWAY_TEAM"]),
            home_goals=int(row["HOME_GOALS"] or 0),
            away_goals=int(row["AWAY_GOALS"] or 0),
        )
    return None

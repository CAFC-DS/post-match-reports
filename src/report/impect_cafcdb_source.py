"""Loads Impect match events from the governed platform table
(``CAFC_DB.IMPECT_RAW.EVENTS``) and flattens them into the exact column
contract ``metrics.py`` already expects (the same shape
``IMPECT_EVENTS_STAGING`` provided) — so every function in the vendored,
unmodified ``metrics.py`` runs against this data without any changes.

Confirmed live (2026-07-30) against CAFC_DB: ``EVENTS`` carries raw event
geometry/coordinates/lanes/packing-zones (``START_DETAIL``/``END_DETAIL``),
per-event threat (``PXT_DETAIL:team``/``:opponent``, verified byte-identical
to staging's ``pxTTeam``/``pxTOpponent`` via a row-level join), and — since
a recent re-run of the extractor — a new ``EVENT_KPIS`` column: a JSON array
of per-player KPI dicts for that event, carrying ``SHOT_XG``, ``PACKING_XG``,
``POSTSHOT_XG``, ``PXT_ATTACK``, ``SUCCESSFUL_PASSES``, ``WON_GROUND_DUELS``,
etc. — the same KPI catalogue staging's ALL_CAPS columns already had. The
acting player's own dict is always the first element of that array (the
other elements are other on-pitch players' defensive-only KPIs, e.g.
``DEF_PXT_SHOT``) — matched explicitly here by ``playerId`` rather than
trusting array order, since that's a much smaller assumption to depend on.

Access requires ``DEV_ROLE``/``DEVELOPMENT_WH`` — the account's default role
in ``.env`` (``ACCOUNTADMIN``) does not have SELECT on ``CAFC_DB.IMPECT_RAW``
tables, confirmed empirically. Follows the same per-query role/warehouse
switch pattern already used by ``src/dvms/loaders/snowflake_source.py``.
"""

from __future__ import annotations

import json

import pandas as pd

from src.db.snowflake_connection import SnowflakeConnector

DEV_ROLE = "DEV_ROLE"
DEV_WAREHOUSE = "DEVELOPMENT_WH"

# Every EVENT_KPIS field metrics.py reads. Missing values default to 0.0
# (matching how a NULL float column behaves under pandas' NaN-skipping sums
# elsewhere in metrics.py) rather than NaN, since these are the raw inputs to
# arithmetic (sums, comparisons) metrics.py performs directly on the column.
_KPI_FIELDS = [
    "SHOT_XG", "PACKING_XG", "POSTSHOT_XG", "PXT_ATTACK", "PXT_PASS",
    "SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES",
    "WON_GROUND_DUELS", "WON_AERIAL_DUELS",
    "BALL_WIN_NUMBER", "SECOND_BALL_WIN",
    "OFFENSIVE_TOUCHES",
    "SHOT_AT_GOAL_NUMBER", "SHOT_AT_GOAL_NUMBER_ON_TARGET",
    "SHOT_AT_GOAL_NUMBER_SUCCESS", "SHOT_AT_GOAL_NUMBER_BLOCKED",
    "SHOT_AT_GOAL_NUMBER_OTHER",
    # Packing counts (2026-08, expanded report): raw opponents/defenders
    # taken out of the game by a pass or dribble, confirmed present on
    # PASS/DRIBBLE events in EVENT_KPIS.
    "BYPASSED_OPPONENTS", "BYPASSED_DEFENDERS",
]

_EVENTS_SQL = """
select
    e.MATCH_ID as "matchId",
    m.ITERATIONID as "iterationId",
    m.SCHEDULEDDATE as "dateTime",
    it."COMPETITION.NAME" as "competitionName",
    it.SEASON as "season",
    hs.NAME as "homeSquadName",
    aws.NAME as "awaySquadName",
    e.EVENT_ID as "eventId",
    e.EVENT_INDEX as "eventNumber",
    e.PERIOD_ID as "periodId",
    e.GAME_TIME as "gameTime",
    e.GAME_TIME_IN_SEC as "gameTimeInSec",
    e.SQUAD_ID as "squadId",
    sq.NAME as "squadName",
    e.PHASE as "phase",
    e.PLAYER_ID as "playerId",
    coalesce(p.COMMONNAME, p.FIRSTNAME || ' ' || p.LASTNAME) as "playerName",
    e.ACTION_TYPE as "actionType",
    e.ACTION as "action",
    e.RESULT as "result",
    e.START_DETAIL:adjCoordinates.x::float as "startAdjCoordinatesX",
    e.START_DETAIL:adjCoordinates.y::float as "startAdjCoordinatesY",
    e.START_DETAIL:pitchPosition::string as "startPitchPosition",
    e.START_DETAIL:lane::string as "startLane",
    e.START_DETAIL:packingZone::string as "startPackingZone",
    e.END_DETAIL:adjCoordinates.x::float as "endAdjCoordinatesX",
    e.END_DETAIL:adjCoordinates.y::float as "endAdjCoordinatesY",
    e.END_DETAIL:pitchPosition::string as "endPitchPosition",
    e.END_DETAIL:lane::string as "endLane",
    e.END_DETAIL:packingZone::string as "endPackingZone",
    e.EVENT_KPIS as "eventKpis"
from CAFC_DB.IMPECT_RAW.EVENTS e
join CAFC_DB.IMPECT_RAW.MATCHES m on m.ID = e.MATCH_ID
join CAFC_DB.IMPECT_RAW.ITERATIONS it on it.ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS hs on hs.ID = m.HOMESQUADID and hs.ITERATION_ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS aws on aws.ID = m.AWAYSQUADID and aws.ITERATION_ID = m.ITERATIONID
left join CAFC_DB.IMPECT_RAW.SQUADS sq on sq.ID = e.SQUAD_ID and sq.ITERATION_ID = m.ITERATIONID
left join CAFC_DB.IMPECT_RAW.PLAYERS p on p.ID = e.PLAYER_ID and p.ITERATION_ID = m.ITERATIONID
where e.MATCH_ID = %(match_id)s
order by e.EVENT_INDEX
"""


# One row per completed league fixture, final score derived from the event
# log itself, matching the exact logic of board-post-match-report's
# sql/extracts/season_results.sql (a goal is credited to the scorer's own
# squad, an OWN_GOAL to the other squad). Play-offs excluded via the
# match-day name (not "competitionType" or a matchday-index cutoff -- see
# that file's own comment for why those are unreliable signals).
_SEASON_RESULTS_SQL = """
select
    m.ID as "match_id",
    m.SCHEDULEDDATE as "kickoff_utc",
    hs.NAME as "home_team",
    aws.NAME as "away_team",
    sum(case when e.ACTION = 'GOAL' and e.SQUAD_ID = m.HOMESQUADID then 1 else 0 end)
  + sum(case when e.ACTION = 'OWN_GOAL' and e.SQUAD_ID = m.AWAYSQUADID then 1 else 0 end)
        as "home_goals",
    sum(case when e.ACTION = 'GOAL' and e.SQUAD_ID = m.AWAYSQUADID then 1 else 0 end)
  + sum(case when e.ACTION = 'OWN_GOAL' and e.SQUAD_ID = m.HOMESQUADID then 1 else 0 end)
        as "away_goals"
from CAFC_DB.IMPECT_RAW.MATCHES m
join CAFC_DB.IMPECT_RAW.SQUADS hs on hs.ID = m.HOMESQUADID and hs.ITERATION_ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS aws on aws.ID = m.AWAYSQUADID and aws.ITERATION_ID = m.ITERATIONID
left join CAFC_DB.IMPECT_RAW.EVENTS e on e.MATCH_ID = m.ID and e.ACTION in ('GOAL', 'OWN_GOAL')
where m.ITERATIONID = %(iteration_id)s
  and not upper(m."MATCHDAY.NAME") like '%%PLAYOFF%%'
group by m.ID, m.SCHEDULEDDATE, hs.NAME, aws.NAME
order by "kickoff_utc"
"""


def load_season_results(iteration_id: int, env_path: str = ".env") -> pd.DataFrame:
    """One row per completed league fixture in the iteration (competition
    season), with the final score -- the CAFC_DB equivalent of
    sql/extracts/season_results.sql, consumed by metrics.season_context."""
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute(_SEASON_RESULTS_SQL, {"iteration_id": iteration_id})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    df.columns = [c.lower() for c in df.columns]
    return df


def _kpi_row_for_player(event_kpis_json: str | None, player_id) -> dict:
    if not event_kpis_json:
        return {}
    entries = json.loads(event_kpis_json)
    for entry in entries:
        if entry.get("playerId") == player_id:
            return entry
    # Some events (whistles, formation markers) carry no acting player and
    # no KPI entries at all -- treat as "no KPI values for this event".
    return {}


def load_match_events(match_id: int, env_path: str = ".env") -> pd.DataFrame:
    """Impect events for one match, sourced from CAFC_DB, flattened to the
    exact column contract metrics.py expects."""
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute(_EVENTS_SQL, {"match_id": match_id})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

    df = pd.DataFrame(rows, columns=cols)

    kpi_rows = [
        _kpi_row_for_player(r["eventKpis"], r["playerId"])
        for _, r in df.iterrows()
    ]
    for field in _KPI_FIELDS:
        df[field] = [float(k.get(field, 0.0) or 0.0) for k in kpi_rows]

    df = df.drop(columns=["eventKpis"])
    return df

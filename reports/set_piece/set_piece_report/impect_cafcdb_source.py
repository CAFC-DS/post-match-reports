"""Impect single-match events sourced from the governed platform table
(``CAFC_DB.IMPECT_RAW.EVENTS``), for fixtures not yet loaded into the legacy
``CAFC_TEST_ANALYSIS.PUBLIC.IMPECT_EVENTS_STAGING`` table ``data.py`` normally
reads from (confirmed live 2026-08-17: ``IMPECT_RAW`` already carries the new
26/27 Championship season -- Charlton 2-1 Derby, 2026-08-15, ``MATCH_ID``
267831 -- while ``IMPECT_EVENTS_STAGING`` is still pinned to season "25/26").

**The set-piece sub-phase fields are derived, not sourced.** Confirmed live
against the real event payload: Impect's raw ``setPiece`` object on every
event is just ``{id, mainEvent, subPhaseId}`` -- no corner-type or
first-touch-won field exists anywhere in the provider feed. The legacy
``IMPECT_EVENTS_STAGING`` columns this report's ``metrics.py`` reads
(``setPieceCategory``, ``setPieceSubPhaseCornerType``,
``setPieceSubPhaseFirstTouchWon``, ``setPieceSubPhaseFreeKickType``) were
themselves derived by whoever built that table. This module re-derives them
the same way ``src/dvms/metrics/opta_setpiece_map.py`` derives the equivalent
concepts from Opta F24 (which has no such fields either) -- except grouping by
Impect's own ``subPhaseId`` (a real shared-phase key returned by the provider)
rather than a time window, which is strictly more reliable than Opta's
"next event within N seconds" heuristic.

Access requires ``DEV_ROLE``/``DEVELOPMENT_WH`` -- the account's default role
in ``.env`` (``ACCOUNTADMIN``) has no SELECT grant on ``CAFC_DB.IMPECT_RAW``
tables, confirmed empirically. Same per-query role/warehouse switch pattern as
``src/dvms/loaders/snowflake_source.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.db.snowflake_connection import SnowflakeConnector

from set_piece_report.data import (  # noqa: E402
    MatchContext,
    _count_goals,
    _matchday_info,
)

DEV_ROLE = "DEV_ROLE"
DEV_WAREHOUSE = "DEVELOPMENT_WH"

# EVENT_KPIS fields metrics.py reads off shot/goal events, plus the set-piece
# possession-value KPIs the platform confirmed exist (PXT_SETPIECE family) --
# not currently consumed by metrics.py, but pulled through for completeness /
# future use rather than dropped on the floor.
_KPI_FIELDS = ["SHOT_XG", "PXT_SETPIECE", "OPP_PXT_SETPIECE", "DEF_PXT_SETPIECE"]

# Real pitch geometry in the same adjusted-coordinate frame pitch.py already
# assumes for this data (X in [-52.5, 52.5], attacking goal at +52.5; Y in
# [-34, 34]) -- standard box/six-yard dimensions in metres, not Opta's 0-100
# fixed frame the DVMS derivation uses.
_HALF_LEN = 52.5
_BOX_X = _HALF_LEN - 16.5      # 36.0
_BOX_Y = 20.16                 # box half-width

_EVENTS_SQL = """
with player_names as (
    -- PLAYERS is sliced per iteration, and a brand-new iteration's slice can
    -- lag its first few fixtures (confirmed on Championship 26/27 iteration
    -- 2114: Joel Piroe, scorer of West Ham's goal in match 267843, has no
    -- row there at all despite ten other iterations carrying him) -- an
    -- iteration-matched join on PLAYERS silently drops those names to NULL.
    -- A player's name does not change across iterations, so look it up by
    -- ID alone, deduplicated to one row per player.
    select ID, coalesce(COMMONNAME, FIRSTNAME || ' ' || LASTNAME) as NAME
    from CAFC_DB.IMPECT_RAW.PLAYERS
    qualify row_number() over (partition by ID order by ITERATION_ID desc) = 1
)
select
    e.MATCH_ID as "matchId",
    m.SCHEDULEDDATE as "dateTime",
    it."COMPETITION.NAME" as "competitionName",
    it.SEASON as "season",
    m."MATCHDAY.NAME" as "matchDayName",
    hs.NAME as "homeSquadName",
    aws.NAME as "awaySquadName",
    e.EVENT_ID as "eventId",
    e.EVENT_INDEX as "sequenceIndex",
    e.PERIOD_ID as "period",
    e.GAME_TIME_IN_SEC as "gameTimeInSec",
    e.SQUAD_ID as "squadId",
    sq.NAME as "squadName",
    atk.NAME as "attackingSquadName",
    e.PLAYER_ID as "playerId",
    pn.NAME as "playerName",
    e.ACTION_TYPE as "actionType",
    e.ACTION as "action",
    e.RESULT as "result",
    e.START_DETAIL:adjCoordinates.x::float as "startAdjCoordinatesX",
    e.START_DETAIL:adjCoordinates.y::float as "startAdjCoordinatesY",
    e.END_DETAIL:adjCoordinates.x::float as "endAdjCoordinatesX",
    e.END_DETAIL:adjCoordinates.y::float as "endAdjCoordinatesY",
    e.SET_PIECE_DETAIL:mainEvent::boolean as "_spMainEvent",
    e.SET_PIECE_DETAIL:subPhaseId::string as "setPieceId",
    e.SET_PIECE_DETAIL:subPhaseStartZone::string as "setPieceSubPhaseStartZone",
    e.EVENT_KPIS as "_eventKpis"
from CAFC_DB.IMPECT_RAW.EVENTS e
join CAFC_DB.IMPECT_RAW.MATCHES m on m.ID = e.MATCH_ID
join CAFC_DB.IMPECT_RAW.ITERATIONS it on it.ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS hs on hs.ID = m.HOMESQUADID and hs.ITERATION_ID = m.ITERATIONID
join CAFC_DB.IMPECT_RAW.SQUADS aws on aws.ID = m.AWAYSQUADID and aws.ITERATION_ID = m.ITERATIONID
left join CAFC_DB.IMPECT_RAW.SQUADS sq on sq.ID = e.SQUAD_ID and sq.ITERATION_ID = m.ITERATIONID
left join CAFC_DB.IMPECT_RAW.SQUADS atk on atk.ID = e.CURRENT_ATTACKING_SQUAD_ID and atk.ITERATION_ID = m.ITERATIONID
left join player_names pn on pn.ID = e.PLAYER_ID
where e.MATCH_ID = %(match_id)s
order by e.EVENT_INDEX
"""


def _kpi_row(event_kpis_json: str | None, player_id) -> dict:
    if not isinstance(event_kpis_json, (str, bytes, bytearray)) or not event_kpis_json:   # NaN (pandas 3) or None
        return {}
    for entry in json.loads(event_kpis_json):
        if entry.get("playerId") == player_id:
            return entry
    return {}


def _corner_type(end_x: float, end_y: float) -> str:
    """near/central/far-post vs short, in Impect's raw-value vocabulary
    (``IMPECT_CORNER_TYPE_MAP`` keys) so ``classify_corner_type`` in
    metrics.py maps it onto the report's taxonomy unchanged."""
    if pd.isna(end_x) or pd.isna(end_y) or end_x < _BOX_X or abs(end_y) > _BOX_Y:
        return "CORNER_OPEN_PLAY"
    third = (2 * _BOX_Y) / 3.0
    # Near post is whichever third is closest to the corner flag the ball was
    # struck from (start_y sign), mirroring the DVMS derivation's convention.
    if end_y > _BOX_Y - third:
        return "CORNER_NEAR_POST" if end_y > 0 else "CORNER_FAR_POST"
    if end_y < -(_BOX_Y - third):
        return "CORNER_NEAR_POST" if end_y < 0 else "CORNER_FAR_POST"
    return "CORNER_CENTRAL"


def _fk_type(action: str, end_x: float, end_y: float) -> str:
    if "CROSS" in str(action).upper():
        return "CROSS"
    if pd.notna(end_x) and end_x >= _BOX_X and pd.notna(end_y) and abs(end_y) <= _BOX_Y:
        return "HIGH_BALL"
    return "SHORT"


def _derive_set_piece_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Fill setPieceCategory / setPieceSubPhaseCornerType /
    setPieceSubPhaseFreeKickType / setPieceSubPhaseFirstTouchWon /
    setPieceSubPhaseFirstTouchPlayerName by grouping events on Impect's own
    ``subPhaseId`` (``setPieceId``) -- see module docstring for why these
    columns don't exist on the raw feed at all."""
    df = df.sort_values("sequenceIndex").reset_index(drop=True)
    for col in ("setPieceCategory", "setPieceSubPhaseCornerType",
                "setPieceSubPhaseFreeKickType", "setPieceSubPhaseFirstTouchWon",
                "setPieceSubPhaseFirstTouchPlayerName"):
        df[col] = None
    df["setPieceSubPhaseIndex"] = 0

    has_phase = df["setPieceId"].notna()
    for phase_id, idx in df.loc[has_phase].groupby("setPieceId").groups.items():
        idx = sorted(idx)
        main_idx = next((i for i in idx if bool(df.at[i, "_spMainEvent"])), idx[0])
        main = df.loc[main_idx]
        action_type = str(main["actionType"])

        if action_type == "CORNER":
            category = "CORNER_LEFT" if float(main["startAdjCoordinatesY"] or 0) > 0 else "CORNER_RIGHT"
            corner_type = _corner_type(main["endAdjCoordinatesX"], main["endAdjCoordinatesY"])
            for i in idx:
                df.at[i, "setPieceCategory"] = category
                df.at[i, "setPieceSubPhaseCornerType"] = corner_type
        elif action_type == "FREE_KICK":
            fk_type = _fk_type(main["action"], main["endAdjCoordinatesX"], main["endAdjCoordinatesY"])
            for i in idx:
                df.at[i, "setPieceCategory"] = "FREE_KICK"
                df.at[i, "setPieceSubPhaseFreeKickType"] = fk_type
        elif action_type == "THROW_IN":
            for i in idx:
                df.at[i, "setPieceCategory"] = "THROW_IN"
        elif action_type == "SHOT":
            # A dead-ball shot as the phase's own main event, with no separate
            # delivery event before it, is a direct free-kick attempt -- the
            # only set-piece shape where the "delivery" and "attempt" are the
            # same event.
            for i in idx:
                df.at[i, "setPieceCategory"] = "FREE_KICK"
                df.at[i, "setPieceSubPhaseFreeKickType"] = "FREE_KICK_SHOT"
        else:
            continue

        if action_type in ("CORNER", "FREE_KICK"):
            rest = [i for i in idx if i != main_idx]
            nxt = next((i for i in rest if str(df.at[i, "playerName"]) not in ("nan", "None", "")), None)
            if nxt is not None:
                won = str(df.at[nxt, "squadId"]) == str(main["squadId"])
                df.at[main_idx, "setPieceSubPhaseFirstTouchWon"] = str(won)
                if won:
                    df.at[main_idx, "setPieceSubPhaseFirstTouchPlayerName"] = df.at[nxt, "playerName"]

    # Impect can split a single attacking move into a new sub-phase after the
    # first contact (for example, the recycled free-kick phase that led to
    # Lloyd Jones's goal). Those continuation rows have a new subPhaseId but
    # no set-piece category of their own. Inherit the immediately preceding
    # phase's category when it is contiguous and remains with the same attack.
    phase_groups = []
    for phase_id, idx in df.loc[has_phase].groupby("setPieceId").groups.items():
        idx = sorted(idx)
        phase_groups.append((idx[0], idx[-1], phase_id, idx))
    phase_groups.sort(key=lambda x: x[0])
    for pos, (start, end, phase_id, idx) in enumerate(phase_groups):
        if df.loc[idx, "setPieceCategory"].notna().any() or pos == 0:
            continue
        prev_start, prev_end, _, prev_idx = phase_groups[pos - 1]
        if start != prev_end + 1:
            continue
        prev_cat = df.at[prev_idx[-1], "setPieceCategory"]
        prev_attack = df.at[prev_idx[-1], "attackingSquadName"]
        curr_attack = df.at[idx[0], "attackingSquadName"]
        if pd.notna(prev_cat) and prev_attack == curr_attack:
            df.loc[idx, "setPieceCategory"] = prev_cat
            prev_fk = df.at[prev_idx[-1], "setPieceSubPhaseFreeKickType"]
            if pd.notna(prev_fk):
                df.loc[idx, "setPieceSubPhaseFreeKickType"] = prev_fk
            # Mark recycled phases explicitly so the report can separate
            # first-phase delivery outcomes from second-phase shots/goals.
            if "setPieceSubPhaseIndex" not in df.columns:
                df["setPieceSubPhaseIndex"] = 0
            df.loc[idx, "setPieceSubPhaseIndex"] = 1

    return df.drop(columns=["_spMainEvent"])


def exclude_penalty_phases(df: pd.DataFrame) -> pd.DataFrame:
    """Remove every penalty from the set-piece analysis: the ``PENALTY_KICK`` shot, its goal event and, when the
    penalty arrives inside a running set-piece phase (a foul in the box from a corner or throw-in), everything in
    that phase from the penalty onwards (saves, rebounds, second balls). Earlier events of the phase stay."""
    if df.empty or "action" not in df.columns:
        return df
    pens = df[df["action"].astype(str) == "PENALTY_KICK"]
    if pens.empty:
        return df
    drop = set(pens.index)
    for idx, pen in pens.iterrows():
        seq = pen["sequenceIndex"]
        same_match = df["matchId"] == pen["matchId"]
        if pd.notna(pen.get("setPieceId")):
            in_phase = same_match & (df["setPieceId"] == pen["setPieceId"]) & (df["sequenceIndex"] >= seq)
            drop |= set(df.index[in_phase])
        goal = same_match & (df["actionType"].astype(str) == "GOAL") & (df["squadName"] == pen["squadName"]) \
            & (df["sequenceIndex"] > seq) & (df["sequenceIndex"] <= seq + 3)
        drop |= set(df.index[goal])
    return df.drop(index=sorted(drop)).reset_index(drop=True)


def load_match_events(match_id: int, env_path: str = ".env", exclude_penalties: bool = True) -> pd.DataFrame:
    """Impect events for one match, sourced from CAFC_DB, flattened + with
    set-piece sub-phase fields derived to the exact column contract
    ``set_piece_report/metrics.py`` expects (the shape ``IMPECT_EVENTS_STAGING``
    provided for matches it carries)."""
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute(_EVENTS_SQL, {"match_id": match_id})
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No events found for matchId={match_id} in CAFC_DB.IMPECT_RAW.EVENTS.")

    df = pd.DataFrame(rows, columns=cols)

    kpi_rows = [_kpi_row(r["_eventKpis"], r["playerId"]) for _, r in df.iterrows()]
    for field in _KPI_FIELDS:
        df[field] = [float(k.get(field, 0.0) or 0.0) for k in kpi_rows]
    df = df.drop(columns=["_eventKpis"])

    df = _derive_set_piece_fields(df)
    df["_dt"] = pd.to_datetime(df["dateTime"], utc=True, errors="coerce")
    return exclude_penalty_phases(df) if exclude_penalties else df


def _matchday_names(match_id: int, competition: str, env_path: str = ".env") -> pd.DataFrame:
    """Every round name of this fixture's iteration, for the 'round x of y' line."""
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute("""select distinct m."MATCHDAY.NAME" from CAFC_DB.IMPECT_RAW.MATCHES m
                       where m.ITERATIONID = (select ITERATIONID from CAFC_DB.IMPECT_RAW.MATCHES where ID = %(id)s)""",
                    {"id": match_id})
        names = [r[0] for r in cur.fetchall()]
    return pd.DataFrame({"competitionName": competition, "matchDayName": names})


MIN_BASELINE_MATCHES = 3        # earlier matches each club needs before per-90 comparisons are shown
_CACHE = Path.home() / ".cache" / "charlton-post-match-analyst"


def _earlier_matches(match_id: int, env_path: str = ".env") -> tuple[pd.DataFrame, int, int]:
    """Earlier matches of the same iteration for either club of ``match_id``: ``matchId``, ``squadId`` pairs."""
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute("""
            select p.ID, p.HOMESQUADID, p.AWAYSQUADID from CAFC_DB.IMPECT_RAW.MATCHES c
            join CAFC_DB.IMPECT_RAW.MATCHES p on p.ITERATIONID = c.ITERATIONID and p.SCHEDULEDDATE < c.SCHEDULEDDATE
            where c.ID = %(id)s
              and (p.HOMESQUADID in (c.HOMESQUADID, c.AWAYSQUADID) or p.AWAYSQUADID in (c.HOMESQUADID, c.AWAYSQUADID))
            order by p.SCHEDULEDDATE""", {"id": match_id})
        rows = cur.fetchall()
        cur.execute("select HOMESQUADID, AWAYSQUADID from CAFC_DB.IMPECT_RAW.MATCHES where ID = %(id)s", {"id": match_id})
        home_id, away_id = cur.fetchone()
    return pd.DataFrame([{"matchId": int(r[0]), "home": int(r[1]), "away": int(r[2])} for r in rows]), int(home_id), int(away_id)


def _cached_match_events(match_id: int, env_path: str) -> pd.DataFrame | None:
    """One earlier match's events (set-piece fields derived), cached: finished matches never change."""
    path = _CACHE / f"setpiece_events_{int(match_id)}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    try:
        frame = load_match_events(match_id, env_path, exclude_penalties=False)    # cache the raw feed
    except ValueError:                          # a match without events (not yet processed)
        return None
    _CACHE.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return frame


def load_season_baselines(match_id: int, env_path: str = ".env") -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """Each club's events from its earlier matches this season (``home``, ``away``) and how many matches that is."""
    earlier, home_id, away_id = _earlier_matches(match_id, env_path)

    def side(squad_id: int) -> pd.DataFrame:
        ids = earlier.loc[(earlier["home"] == squad_id) | (earlier["away"] == squad_id), "matchId"].tolist()
        frames = [f for f in (_cached_match_events(i, env_path) for i in ids) if f is not None]
        return exclude_penalty_phases(pd.concat(frames, ignore_index=True)) if frames else pd.DataFrame()

    home, away = side(home_id), side(away_id)
    return home, away, int(home["matchId"].nunique()) if len(home) else 0, int(away["matchId"].nunique()) if len(away) else 0


def load_match_context(match_id: int, env_path: str = ".env") -> MatchContext:
    """``MatchContext`` for a match sourced from ``CAFC_DB.IMPECT_RAW`` rather
    than the legacy ``IMPECT_EVENTS_STAGING`` table, which no longer exists.
    Season baselines come from the clubs' earlier matches in the same iteration
    (see ``load_season_baselines``)."""
    raw = load_match_events(match_id, env_path, exclude_penalties=False)
    match = exclude_penalty_phases(raw)             # every stat ignores penalties; the scoreline below does not

    home = str(match["homeSquadName"].iloc[0])
    away = str(match["awaySquadName"].iloc[0])
    competition = str(match["competitionName"].iloc[0])

    home_season, away_season, home_n, away_n = load_season_baselines(match_id, env_path)
    matchday, matchday_total = _matchday_info(_matchday_names(match_id, competition, env_path), competition,
                                              match["matchDayName"].iloc[0])

    player_team = (
        match.dropna(subset=["playerName", "squadName"])
        .groupby("playerName")["squadName"]
        .agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )

    return MatchContext(
        match_id=int(match_id),
        date=match["_dt"].iloc[0],
        competition=competition,
        season=str(match["season"].iloc[0]),
        matchday=matchday,
        matchday_total=matchday_total,
        home_team=home,
        away_team=away,
        home_goals=_count_goals(raw, home),
        away_goals=_count_goals(raw, away),
        match_events=match,
        home_season_events=home_season if len(home_season) else match.iloc[0:0],
        away_season_events=away_season if len(away_season) else match.iloc[0:0],
        player_team=player_team,
        # Per-90 / % comparisons use each club's own earlier matches this season, and only appear once both
        # clubs have MIN_BASELINE_MATCHES of them; earlier in the season the columns show "-".
        show_comparisons=min(home_n, away_n) >= MIN_BASELINE_MATCHES,
    )

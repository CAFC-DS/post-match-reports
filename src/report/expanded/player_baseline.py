"""Player match values and 26/27 season / league baselines, built from Impect event data.

The league-wide player KPI tables stop at 25/26, so this season's baselines are built from
``EVENTS`` itself: every KPI entry in ``EVENT_KPIS`` is credited to the player it names
(passer, receiver, duel winner *and* loser), summed per player per match, and turned into
per-90 rates using minutes from ``MATCH_INFO`` (starters, substitutions, last event).

* **Season average** - the player's own rate over this season's earlier matches.
* **League average** - the pooled rate of every player in the same position group over the
  same matches (total / total minutes, so a 10-minute cameo does not carry a full weight).

The reported match is excluded from both, so a player is not compared with himself.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.report.impect_cafcdb_source import DEV_ROLE, DEV_WAREHOUSE, SnowflakeConnector

CACHE_DIR = Path.home() / ".cache" / "charlton-post-match-analyst"

# Raw KPIs summed per player per match (every KPI entry is credited to the player it names).
KPI_COLUMNS = [
    "SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES", "PXT_ATTACK", "BYPASSED_OPPONENTS", "BALL_WIN_NUMBER",
    "BALL_LOSS_NUMBER", "NUMBER_OF_PRESSES", "WON_GROUND_DUELS", "LOST_GROUND_DUELS", "WON_AERIAL_DUELS",
    "LOST_AERIAL_DUELS", "SHOT_XG", "SHOT_AT_GOAL_NUMBER", "SHOT_AT_GOAL_NUMBER_ON_TARGET", "EXPECTED_GOAL_ASSISTS",
    "SHOT_ASSISTS", "SHOT_CREATING_ACTIONS", "SECOND_BALL_WIN", "GOALS", "ASSISTS", "PXT_PASS", "PXT_DRIBBLE", "PXT_REC",
    "OFFENSIVE_TOUCHES", "DEFENSIVE_TOUCHES", "YELLOW_CARD", "FORCED_TURNOVERS",
]
# Counts of what the player himself did, from the event rows he is the actor of.
ACTOR_COLUMNS = ["SAVES", "CATCHES", "INTERCEPTIONS", "CLEARANCES", "BLOCKS", "FOULS", "CROSSES", "CROSSES_COMPLETED",
                 "DRIBBLES", "DRIBBLES_COMPLETED", "PASSES_FINAL_THIRD", "PASSES_BOX", "RECEPTIONS", "RECEPTIONS_BTL",
                 "LONG_PASSES", "LONG_PASSES_COMPLETED", "OFFSIDES", "GOAL_KICKS"]
VALUE_COLUMNS = KPI_COLUMNS + ACTOR_COLUMNS

POSITION_GROUPS = {
    "GOALKEEPER": "GK", "CENTRAL_DEFENDER": "CB", "LEFT_WINGBACK_DEFENDER": "FB", "RIGHT_WINGBACK_DEFENDER": "FB",
    "DEFENSE_MIDFIELD": "MF", "CENTRAL_MIDFIELD": "MF", "ATTACKING_MIDFIELD": "MF", "LEFT_MIDFIELD": "MF",
    "RIGHT_MIDFIELD": "MF", "LEFT_WINGER": "W", "RIGHT_WINGER": "W", "CENTER_FORWARD": "CF",
}
GROUP_ORDER = ("GK", "CB", "FB", "MF", "W", "CF")
GROUP_LABELS = {"GK": "Goalkeepers", "CB": "Centre-backs", "FB": "Full-backs", "MF": "Midfielders", "W": "Wingers",
                "CF": "Forwards"}

class Metric:
    """A row on the player pages. ``den`` None = a count (shown raw today, per 90 in the averages);
    otherwise a percentage numerator / denominator."""

    def __init__(self, label: str, desc: str, num: tuple[str, ...], den: tuple[str, ...] | None = None,
                 better: bool = True, raw_dec: int = 0, avg_dec: int = 1):
        self.label, self.desc, self.num, self.den = label, desc, num, den
        self.better, self.raw_dec, self.avg_dec = better, raw_dec, avg_dec

    @property
    def is_pct(self) -> bool:
        return self.den is not None


_DUELS = ("WON_GROUND_DUELS", "WON_AERIAL_DUELS")
_ALL_DUELS = _DUELS + ("LOST_GROUND_DUELS", "LOST_AERIAL_DUELS")
METRICS: dict[str, Metric] = {
    "passes": Metric("Passes completed", "Successful passes", ("SUCCESSFUL_PASSES",)),
    "pass_pct": Metric("Pass accuracy", "Share of his passes that found a team-mate", ("SUCCESSFUL_PASSES",),
                       ("SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES"), avg_dec=0),
    "xt": Metric("Threat created (xT)", "How far his passes, carries and receptions moved the ball towards goal",
                 ("PXT_ATTACK",), raw_dec=2, avg_dec=2),
    "bypassed": Metric("Opponents bypassed", "Opponents taken out of the game by his passes and carries",
                       ("BYPASSED_OPPONENTS",)),
    "wins": Metric("Ball wins", "Times he won the ball back", ("BALL_WIN_NUMBER",)),
    "losses": Metric("Ball losses", "Times he gave the ball away (lower is better)", ("BALL_LOSS_NUMBER",), better=False),
    "presses": Metric("Pressures", "Times he pressed an opponent on the ball", ("NUMBER_OF_PRESSES",)),
    "duels": Metric("Duels won", "Ground and aerial duels he won", _DUELS),
    "duel_pct": Metric("Duel win rate", "Share of all his duels that he won", _DUELS, _ALL_DUELS, avg_dec=0),
    "aerials": Metric("Aerial duels won", "Headed duels he won", ("WON_AERIAL_DUELS",)),
    "aerial_pct": Metric("Aerial win rate", "Share of his aerial duels that he won", ("WON_AERIAL_DUELS",),
                         ("WON_AERIAL_DUELS", "LOST_AERIAL_DUELS"), avg_dec=0),
    "interceptions": Metric("Interceptions", "Passes he cut out", ("INTERCEPTIONS",)),
    "clearances": Metric("Clearances", "Balls he cleared from danger", ("CLEARANCES",)),
    "blocks": Metric("Blocks", "Shots and passes he blocked", ("BLOCKS",)),
    "fouls": Metric("Fouls committed", "Lower is better", ("FOULS",), better=False),
    "saves": Metric("Saves", "Shots he saved", ("SAVES",)),
    "catches": Metric("Catches and claims", "Balls he caught", ("CATCHES",)),
    "crosses": Metric("Crosses attempted", "Crosses into the box", ("CROSSES",)),
    "crosses_done": Metric("Crosses completed", "Crosses that reached a team-mate", ("CROSSES_COMPLETED",)),
    "dribbles": Metric("Carries completed", "Times he carried the ball without losing it", ("DRIBBLES_COMPLETED",)),
    "second_balls": Metric("Second balls won", "Loose balls he won after a contest", ("SECOND_BALL_WIN",)),
    "touches": Metric("Touches", "Times he had the ball at his feet", ("OFFENSIVE_TOUCHES", "DEFENSIVE_TOUCHES")),
    "xt_pass": Metric("Threat from passes", "xT added by his passing", ("PXT_PASS",), raw_dec=2, avg_dec=2),
    "xt_carry": Metric("Threat from carries", "xT added by carrying the ball", ("PXT_DRIBBLE",), raw_dec=2, avg_dec=2),
    "xt_rec": Metric("Threat from receiving", "xT added by receiving the ball in good positions", ("PXT_REC",),
                     raw_dec=2, avg_dec=2),
    "passes_third": Metric("Passes into the final third", "Completed passes that took the ball into the final third",
                           ("PASSES_FINAL_THIRD",)),
    "passes_box": Metric("Passes into the box", "Completed passes into the opposition box", ("PASSES_BOX",)),
    "receptions": Metric("Receptions", "Times he received the ball (as tagged by Impect)", ("RECEPTIONS",)),
    "receptions_btl": Metric("Receptions between the lines", "Receptions between the opposition lines",
                             ("RECEPTIONS_BTL",)),
    "long_passes": Metric("Long passes completed", "Chipped and diagonal passes that reached a team-mate",
                          ("LONG_PASSES_COMPLETED",)),
    "long_pct": Metric("Long pass accuracy", "Share of his long passes that found a team-mate",
                       ("LONG_PASSES_COMPLETED",), ("LONG_PASSES",), avg_dec=0),
    "forced": Metric("Forced turnovers", "Presses after which the opponent lost the ball", ("FORCED_TURNOVERS",)),
    "forced_pct": Metric("Press success rate", "Share of his presses that made the opponent lose the ball",
                         ("FORCED_TURNOVERS",), ("NUMBER_OF_PRESSES",), avg_dec=0),
    "offsides": Metric("Offsides", "Lower is better", ("OFFSIDES",), better=False),
    "goal_kicks": Metric("Goal kicks", "Goal kicks taken", ("GOAL_KICKS",)),
    "yellows": Metric("Yellow cards", "Lower is better", ("YELLOW_CARD",), better=False),
    "goals": Metric("Goals", "", ("GOALS",), raw_dec=0, avg_dec=2),
    "shots": Metric("Shots", "Attempts at goal", ("SHOT_AT_GOAL_NUMBER",)),
    "sot": Metric("Shots on target", "", ("SHOT_AT_GOAL_NUMBER_ON_TARGET",)),
    "xg": Metric("Expected goals (xG)", "Quality of his chances", ("SHOT_XG",), raw_dec=2, avg_dec=2),
    "xa": Metric("Expected assists (xA)", "Quality of the chances he created", ("EXPECTED_GOAL_ASSISTS",), raw_dec=2,
                 avg_dec=2),
    "key_passes": Metric("Key passes", "Passes that led to a shot", ("SHOT_ASSISTS",)),
    "sca": Metric("Shot-creating actions", "Passes, carries and wins that led to a shot", ("SHOT_CREATING_ACTIONS",)),
}
GROUP_METRICS = {
    "GK": ("saves", "catches", "passes", "pass_pct", "long_passes", "long_pct", "goal_kicks", "xt", "bypassed",
           "clearances", "losses"),
    "CB": ("touches", "passes", "pass_pct", "passes_third", "bypassed", "interceptions", "clearances", "blocks", "duels",
           "duel_pct", "aerials", "aerial_pct", "wins", "losses", "fouls", "yellows"),
    "FB": ("touches", "passes", "pass_pct", "passes_third", "passes_box", "crosses", "crosses_done", "xt", "bypassed",
           "dribbles", "receptions_btl", "duels", "interceptions", "wins", "presses", "losses"),
    "MF": ("touches", "passes", "pass_pct", "passes_third", "passes_box", "xt", "bypassed", "key_passes", "sca",
           "receptions_btl", "interceptions", "wins", "presses", "forced", "duels", "second_balls", "losses"),
    "W": ("touches", "goals", "shots", "sot", "xg", "xa", "key_passes", "sca", "xt", "dribbles", "passes_box",
          "crosses_done", "receptions_btl", "bypassed", "presses", "forced", "losses"),
    "CF": ("touches", "goals", "shots", "sot", "xg", "xa", "key_passes", "xt", "receptions", "receptions_btl", "aerials",
           "duel_pct", "presses", "forced", "offsides", "wins", "losses", "yellows"),
}
MIN_SEASON_MINUTES = 90        # earlier minutes needed before a player's own average means anything
MIN_MATCH_MINUTES = 20         # shorter appearances are shown but not rated
NEUTRAL_BAND = 0.05            # within 5% (relative) of the average counts as level


def minute_of(game_time_in_sec: float) -> float:
    """Match minute for Impect's ``gameTimeInSec`` (the second half starts at 10000)."""
    t = float(game_time_in_sec)
    return 45.0 + (t - 10000.0) / 60.0 if t >= 10000.0 else t / 60.0


def player_minutes(info: dict[str, Any], match_end: float) -> dict[int, float]:
    """Minutes per player id for one side: starters play to the end or until subbed off;
    substitutes from the minute they come on."""
    starts = json.loads(info["starting"]) if isinstance(info["starting"], str) else []
    subs = json.loads(info["subs"]) if isinstance(info["subs"], str) else []
    on = {int(s["playerId"]): 0.0 for s in starts}
    off: dict[int, float] = {}
    for s in sorted(subs, key=lambda s: s["gameTime"]["gameTimeInSec"]):
        pid, minute = int(s["playerId"]), minute_of(s["gameTime"]["gameTimeInSec"])
        if s["substitutionType"] == "SUB_ON":
            on[pid] = minute
        elif s["substitutionType"] == "SUB_OFF":
            off[pid] = minute                 # POSITION_CHANGE and POSITION_SIDE_CHANGE rows are not exits
    return {pid: max(off.get(pid, match_end) - start, 0.0) for pid, start in on.items()}


def group_of(position: str | None) -> str | None:
    return POSITION_GROUPS.get(str(position))


def _kpi_sql(match_filter: str, iteration_id: int) -> str:
    plain = [c for c in KPI_COLUMNS if c != "FORCED_TURNOVERS"]
    sums = ",\n  ".join(f'sum(coalesce(k.value:{c}::float, 0)) as "{c}"' for c in plain)
    # a press forces a turnover when the pressed event's action failed
    sums += (",\n  sum(iff(coalesce(k.value:NUMBER_OF_PRESSES::float, 0) > 0 and e.RESULT = 'FAIL', 1, 0))"
             ' as "FORCED_TURNOVERS"')
    return f"""
select e.MATCH_ID as "matchId", k.value:playerId::int as "playerId", k.value:position::string as "position",
  {sums}
from CAFC_DB.IMPECT_RAW.EVENTS e, lateral flatten(input => parse_json(e.EVENT_KPIS)) k
where e.ITERATION_ID = {int(iteration_id)} and e.EVENT_KPIS is not null and {match_filter}
group by 1, 2, 3"""


def _actor_sql(match_filter: str, iteration_id: int) -> str:
    cross = "e.ACTION_TYPE = 'PASS' and e.ACTION in ('HIGH_CROSS', 'LOW_CROSS')"
    start, end = "e.START_DETAIL:pitchPosition::string", "e.END_DETAIL:pitchPosition::string"
    done = "e.ACTION_TYPE = 'PASS' and e.RESULT = 'SUCCESS'"
    into_third = (f"{done} and {end} in ('FINAL_THIRD', 'OPPONENT_BOX') "
                  f"and coalesce({start}, '') not in ('FINAL_THIRD', 'OPPONENT_BOX')")
    into_box = f"{done} and {end} = 'OPPONENT_BOX' and coalesce({start}, '') != 'OPPONENT_BOX'"
    long_pass = "e.ACTION_TYPE = 'PASS' and e.ACTION in ('CHIPPED_PASS', 'DIAGONAL_PASS')"
    return f"""
select e.MATCH_ID as "matchId", e.PLAYER_ID as "playerId",
  count_if(e.ACTION_TYPE = 'GK_SAVE') as "SAVES",
  count_if(e.ACTION_TYPE = 'GK_CATCH') as "CATCHES",
  count_if(e.ACTION_TYPE = 'INTERCEPTION') as "INTERCEPTIONS",
  count_if(e.ACTION_TYPE = 'CLEARANCE') as "CLEARANCES",
  count_if(e.ACTION_TYPE = 'BLOCK' and e.ACTION = 'BLOCK') as "BLOCKS",
  count_if(e.ACTION_TYPE = 'FOUL') as "FOULS",
  count_if({cross}) as "CROSSES",
  count_if({cross} and e.RESULT = 'SUCCESS') as "CROSSES_COMPLETED",
  count_if(e.ACTION_TYPE = 'DRIBBLE') as "DRIBBLES",
  count_if(e.ACTION_TYPE = 'DRIBBLE' and e.RESULT = 'SUCCESS') as "DRIBBLES_COMPLETED",
  count_if({into_third}) as "PASSES_FINAL_THIRD",
  count_if({into_box}) as "PASSES_BOX",
  count_if(e.ACTION_TYPE = 'RECEPTION') as "RECEPTIONS",
  count_if(e.ACTION_TYPE = 'RECEPTION' and e.ACTION = 'AVAILABILITY_BTL') as "RECEPTIONS_BTL",
  count_if({long_pass}) as "LONG_PASSES",
  count_if({long_pass} and e.RESULT = 'SUCCESS') as "LONG_PASSES_COMPLETED",
  count_if(e.ACTION_TYPE = 'OFFSIDE') as "OFFSIDES",
  count_if(e.ACTION_TYPE = 'GOAL_KICK') as "GOAL_KICKS"
from CAFC_DB.IMPECT_RAW.EVENTS e
where e.ITERATION_ID = {int(iteration_id)} and e.PLAYER_ID is not null and {match_filter}
group by 1, 2"""


def load_player_matches(iteration_id: int, match_ids: list[int], env_path: str = ".env") -> pd.DataFrame:
    """One row per (match, player, position played) with summed KPIs, ``minutes`` and ``squadId``."""
    ids = ", ".join(str(int(m)) for m in match_ids)
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute(_kpi_sql(f"e.MATCH_ID in ({ids})", iteration_id))
        kpis = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        cur.execute(_actor_sql(f"e.MATCH_ID in ({ids})", iteration_id))
        actors = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
        cur.execute(f"""select MATCH_ID, HOME_SQUAD_ID, AWAY_SQUAD_ID, HOME_STARTING_POSITIONS, AWAY_STARTING_POSITIONS,
                               HOME_SUBSTITUTIONS, AWAY_SUBSTITUTIONS, HOME_PLAYERS, AWAY_PLAYERS, MATCH_DATETIME
                        from CAFC_DB.IMPECT_RAW.MATCH_INFO where MATCH_ID in ({ids})""")
        infos = cur.fetchall()
        cur.execute(f"""select MATCH_ID, max(GAME_TIME_IN_SEC) from CAFC_DB.IMPECT_RAW.EVENTS
                        where MATCH_ID in ({ids}) group by 1""")
        ends = {int(m): minute_of(t) for m, t in cur.fetchall()}

    rows = []
    for match_id, home, away, hs, as_, hsub, asub, hplayers, aplayers, kickoff in infos:
        end = max(ends.get(int(match_id), 90.0), 90.0)
        for squad, starting, subs, players in ((home, hs, hsub, hplayers), (away, as_, asub, aplayers)):
            shirts = {int(p["id"]): p.get("shirtNumber") for p in json.loads(players)} if isinstance(players, str) else {}
            for pid, minutes in player_minutes({"starting": starting, "subs": subs}, end).items():
                rows.append({"matchId": int(match_id), "playerId": pid, "squadId": int(squad), "minutes": minutes,
                             "shirt": shirts.get(pid), "kickoff": str(kickoff)})
    minutes = pd.DataFrame(rows, columns=["matchId", "playerId", "squadId", "minutes", "shirt", "kickoff"])
    out = collapse_positions(kpis.merge(minutes, on=["matchId", "playerId"], how="inner"))
    out = out.merge(actors, on=["matchId", "playerId"], how="left")
    out[ACTOR_COLUMNS] = out[ACTOR_COLUMNS].fillna(0.0).astype(float)
    return out


def collapse_positions(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per player per match: KPIs summed across the positions he played, the position
    with the most activity as his ``position`` and its ``group``."""
    frame = frame.copy()
    frame["_activity"] = frame[KPI_COLUMNS].abs().sum(axis=1)
    main = frame.sort_values("_activity", ascending=False).drop_duplicates(["matchId", "playerId"])
    main = main[["matchId", "playerId", "position", "squadId", "minutes", "shirt", "kickoff"]]
    sums = frame.groupby(["matchId", "playerId"], as_index=False)[KPI_COLUMNS].sum()
    out = sums.merge(main, on=["matchId", "playerId"])
    out["group"] = out["position"].map(group_of)
    return out


def _rate(frame: pd.DataFrame, key: str) -> float | None:
    """The metric's rate over ``frame``: per 90 minutes for a count, a percentage for a rate metric
    (a pooled sum, so many matches / players combine correctly)."""
    m = METRICS[key]
    n = float(frame[list(m.num)].to_numpy().sum())
    if m.den is not None:
        d = float(frame[list(m.den)].to_numpy().sum())
        return n / d * 100.0 if d > 0 else None
    minutes = float(frame["minutes"].sum())
    return n / minutes * 90.0 if minutes > 0 else None


def _today(frame: pd.DataFrame, key: str) -> float | None:
    """What the player got in the game: the raw count, or the percentage."""
    m = METRICS[key]
    if m.den is not None:
        return _rate(frame, key)
    return float(frame[list(m.num)].to_numpy().sum())


def verdict(value: float | None, average: float | None, higher_is_better: bool) -> str:
    """'up' / 'down' / 'level' (better / worse / within 5%), '' when there is nothing to compare."""
    if value is None or average is None:
        return ""
    if average == 0:
        return "level" if value == 0 else ("up" if (value > 0) == higher_is_better else "down")
    rel = (value - average) / abs(average)
    if abs(rel) <= NEUTRAL_BAND:
        return "level"
    return "up" if (rel > 0) == higher_is_better else "down"


def natural_group(history_rows: pd.DataFrame) -> str | None:
    """The position group a player has spent most minutes in over the earlier matches, None without history."""
    rows = history_rows[history_rows["group"].notna()]
    if rows.empty:
        return None
    by_group = rows.groupby("group")["minutes"].sum()
    return str(by_group.idxmax()) if float(by_group.max()) > 0 else None


def physical_by_shirt(dvms_match: Any, team: str) -> dict[int, dict[str, float]]:
    """Second Spectrum physical totals for ``team`` keyed by shirt number (the key Impect's MATCH_INFO shares)."""
    phys, lineups = dvms_match.physical, dvms_match.f7.lineups
    if phys is None or phys.empty or lineups.empty:
        return {}
    lu = lineups[["player_id", "team_id", "shirt_number"]].copy()
    lu["player_id"] = lu["player_id"].astype(str)
    merged = phys.assign(opta_player_id=phys["opta_player_id"].astype(str)).merge(
        lu, left_on="opta_player_id", right_on="player_id", how="inner")
    out: dict[int, dict[str, float]] = {}
    for r in merged.itertuples():
        if dvms_match.team_name_of(dvms_match.side_of(r.team_id)) != team or pd.isna(r.shirt_number):
            continue
        out[int(r.shirt_number)] = {"distance": float(r.distance) / 1000.0, "hsr": float(r.hsr),
                                    "sprint": float(r.sprinting), "runs": float(r.n_high_intensity_runs),
                                    "top_speed": float(r.top_speed)}
    return out


PHYSICAL_ROWS = (("distance", "Distance covered", "km", 1), ("hsr", "High-speed running", "m", 0),
                 ("sprint", "Sprint distance", "m", 0), ("runs", "High-intensity runs", "", 0),
                 ("top_speed", "Top speed", "km/h", 1))


def build_player_tables(history: pd.DataFrame, today: pd.DataFrame, squad_id: int) -> list[dict[str, Any]]:
    """Groups of player rows for one squad in the reported match.

    ``history`` is every earlier match of the season; ``today`` the reported match rows. A player is
    placed in the group of the position he played most today. Each cell carries what he did today (raw),
    his own earlier per-90 rate and the league's pooled per-90 rate for the group. The verdicts compare
    today's *per-90 equivalent* with those averages, so a 45-minute cameo is judged fairly."""
    mine = today[today["squadId"] == squad_id]
    out: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
    for pid, rows in mine.groupby("playerId"):
        main = rows.sort_values("minutes", ascending=False).iloc[0]
        today_group = main["group"]
        mine_before = history[(history["playerId"] == pid)]
        group = natural_group(mine_before) or today_group
        if group not in out:
            continue
        minutes = float(rows["minutes"].max())
        league = history[history["group"] == group]
        enough_history = float(mine_before["minutes"].sum()) >= MIN_SEASON_MINUTES
        rated = minutes >= MIN_MATCH_MINUTES
        cells = []
        for key in GROUP_METRICS[group]:
            m = METRICS[key]
            season = _rate(mine_before, key) if enough_history else None
            lg = _rate(league, key)
            rate_today = _rate(rows, key)                 # per 90 for counts, % for rate metrics
            cells.append({"key": key, "today": _today(rows, key),
                          "season": verdict(rate_today, season, m.better) if rated else "",
                          "league": verdict(rate_today, lg, m.better) if rated else "",
                          "season_value": season, "league_value": lg})
        out[group].append({"playerId": int(pid), "minutes": round(minutes), "cells": cells,
                           "played_as": GROUP_LABELS.get(today_group, "") if today_group != group else ""})
    return [{"group": g, "label": GROUP_LABELS[g], "players": sorted(out[g], key=lambda p: -p["minutes"])}
            for g in GROUP_ORDER if out[g]]


def season_to_date(match_id: int, iteration_id: int, kickoff: str, env_path: str = ".env",
                   refresh: bool = False) -> pd.DataFrame:
    """Every player-match of the season up to and including ``match_id``, cached on disk.

    Matches are final once played, so only matches missing from the cache are queried."""
    cache = CACHE_DIR / f"player_matches_{int(iteration_id)}_v4.parquet"
    have = pd.read_parquet(cache) if cache.exists() and not refresh else pd.DataFrame()
    connector = SnowflakeConnector(env_path)
    with connector.connection() as conn:
        cur = conn.cursor()
        cur.execute(f"USE ROLE {DEV_ROLE}")
        cur.execute(f"USE WAREHOUSE {DEV_WAREHOUSE}")
        cur.execute("""select distinct e.MATCH_ID from CAFC_DB.IMPECT_RAW.EVENTS e
                       join CAFC_DB.IMPECT_RAW.MATCHES m on m.ID = e.MATCH_ID
                       where e.ITERATION_ID = %(it)s and m.SCHEDULEDDATE <= %(ko)s""",
                    {"it": int(iteration_id), "ko": kickoff})
        wanted = {int(r[0]) for r in cur.fetchall()} | {int(match_id)}
    missing = sorted(wanted - set(have["matchId"]) if len(have) else wanted)
    if missing:
        new = load_player_matches(iteration_id, missing, env_path)
        have = pd.concat([have, new], ignore_index=True) if len(have) else new
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        have.to_parquet(cache)
    return have[have["matchId"].isin(wanted)]


def _format(value: float | None, key: str, raw: bool = False) -> str:
    if value is None:
        return "–"
    m = METRICS[key]
    decimals = m.raw_dec if raw else m.avg_dec
    return f"{value:.{decimals}f}" + ("%" if m.is_pct else "")


def _both(season: str, league: str) -> str:
    """One verdict for the value cell from its two comparisons: up / down / level, 'mixed' when they disagree."""
    scores = [{"up": 1, "down": -1, "level": 0}[v] for v in (season, league) if v]
    if not scores:
        return ""
    if 1 in scores and -1 in scores:
        return "mixed"
    total = sum(scores)
    return "up" if total > 0 else ("down" if total < 0 else "level")


# The report shows three pages: the six position groups are merged into defenders (with the goalkeeper),
# midfielders and attackers. Rows are exactly ``PAGE_ROWS`` when listed, otherwise the union of the
# member groups' metrics in order of first appearance; a player simply has no value for a metric of another role.
PAGE_GROUPS = {"defenders": ("GK", "CB", "FB"), "midfielders": ("MF",), "attackers": ("W", "CF")}
PAGE_LABELS = {"defenders": "Goalkeepers & Defenders", "midfielders": "Midfielders", "attackers": "Wingers & Forwards"}
PAGE_ROWS = {
    "defenders": ("saves", "catches", "long_passes", "touches", "passes", "pass_pct", "passes_third", "bypassed", "xt",
                  "interceptions", "clearances", "blocks", "duels", "aerials", "wins", "presses", "fouls", "losses"),
    "attackers": ("touches", "goals", "shots", "sot", "xg", "xa", "key_passes", "sca", "xt", "dribbles", "passes_box",
                  "receptions_btl", "bypassed", "presses", "forced", "aerials", "offsides", "losses"),
}
_BLANK_CELL = {"text": "", "own": "", "league": "", "v_own": "", "v_league": "", "v_both": ""}


def merge_pages(group_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine the per-group pages into ``PAGE_GROUPS``; empty pages are kept so the page count is fixed."""
    by_key = {g["key"]: g for g in group_pages}
    merged = []
    for key, members in PAGE_GROUPS.items():
        parts = [by_key[m.lower()] for m in members if m.lower() in by_key and by_key[m.lower()]["columns"]]
        columns = [c for part in parts for c in part["columns"]]
        order: list[str] = list(PAGE_ROWS.get(key, ()))      # a listed page shows exactly these rows
        if not order:
            for part in parts:
                order += [r["key"] for r in part["rows"] if r["key"] not in order]
        rows = []
        for metric in order:
            template = next((r for part in parts for r in part["rows"] if r["key"] == metric), None)
            if template is None:
                continue
            cells = []
            for part in parts:
                own = next((r for r in part["rows"] if r["key"] == metric), None)
                cells += own["cells"] if own else [dict(_BLANK_CELL, text="–") for _ in part["columns"]]
            rows.append({"key": metric, "label": template["label"], "desc": template["desc"], "cells": cells})
        phys: list[dict[str, Any]] = []
        for part in parts:
            for r in part["physical"]:
                match = next((x for x in phys if x["label"] == r["label"]), None)
                if match is None:
                    match = {"label": r["label"], "unit": r["unit"], "cells": []}
                    phys.append(match)
        for r in phys:
            r["cells"] = []
            for part in parts:
                own = next((x for x in part["physical"] if x["label"] == r["label"]), None)
                r["cells"] += own["cells"] if own else ["–"] * len(part["columns"])
        merged.append({"key": key, "label": PAGE_LABELS[key], "columns": columns, "rows": rows, "physical": phys})
    return merged


def players_context(all_rows: pd.DataFrame, events: pd.DataFrame, team: str, match_id: int,
                    physical: dict[int, dict[str, float]] | None = None) -> dict[str, Any]:
    """Template context: one page per position group for ``team``'s players. Players are the columns
    (starters then subs by minutes), the group's metrics are the rows, and each player has three cells:
    what he did today (raw), his own per-90 average and the league per-90 average for the position.
    Colours compare today's per-90 equivalent with the two averages."""
    today = all_rows[all_rows["matchId"] == match_id]
    if today.empty:
        return {}
    history = all_rows[(all_rows["matchId"] != match_id) & (all_rows["kickoff"] < today["kickoff"].iloc[0])]
    names = events.dropna(subset=["playerId"]).drop_duplicates("playerId").set_index("playerId")["playerName"]
    squad = events.loc[events["squadName"] == team, "squadId"].dropna()
    if squad.empty:
        return {}
    groups = {g["group"]: g["players"] for g in build_player_tables(history, today, int(squad.iloc[0]))}

    pages = []
    for group in GROUP_ORDER:
        keys = GROUP_METRICS[group]
        players = groups.get(group, [])
        columns = []
        for p in players:
            shirt = today.loc[today["playerId"] == p["playerId"], "shirt"]
            columns.append({"role": GROUP_LABELS[group],
                            "name": str(names.get(p["playerId"], "")).split()[-1] or str(p["playerId"]),
                            "shirt": int(shirt.iloc[0]) if len(shirt) and pd.notna(shirt.iloc[0]) else "",
                            "minutes": p["minutes"], "rated": p["minutes"] >= MIN_MATCH_MINUTES,
                            "played_as": p["played_as"]})
        rows = []
        for k, key in enumerate(keys):
            cells = []
            for p in players:
                c = p["cells"][k]
                cells.append({"text": _format(c["today"], key, raw=True), "own": _format(c["season_value"], key),
                              "league": _format(c["league_value"], key), "v_own": c["season"], "v_league": c["league"],
                              "v_both": _both(c["season"], c["league"])})
            rows.append({"key": key, "label": METRICS[key].label, "desc": METRICS[key].desc, "cells": cells})
        phys_rows = []
        if physical:
            for key, label, unit, dec in PHYSICAL_ROWS:
                vals = [physical.get(c["shirt"], {}).get(key) if c["shirt"] != "" else None for c in columns]
                if any(v is not None for v in vals):
                    phys_rows.append({"label": label, "unit": unit,
                                      "cells": ["–" if v is None else f"{v:.{dec}f}" for v in vals]})
        pages.append({"key": group.lower(), "label": GROUP_LABELS[group], "columns": columns, "rows": rows,
                      "physical": phys_rows})
    return {"player_pages": merge_pages(pages), "player_baseline_matches": int(history["matchId"].nunique())}

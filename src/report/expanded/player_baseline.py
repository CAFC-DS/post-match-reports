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

# Raw KPIs summed per player per match.
KPI_COLUMNS = [
    "SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES", "PXT_ATTACK", "BYPASSED_OPPONENTS", "BALL_WIN_NUMBER",
    "BALL_LOSS_NUMBER", "NUMBER_OF_PRESSES", "WON_GROUND_DUELS", "LOST_GROUND_DUELS", "WON_AERIAL_DUELS",
    "LOST_AERIAL_DUELS", "SHOT_XG", "SHOT_AT_GOAL_NUMBER", "EXPECTED_GOAL_ASSISTS", "SHOT_CREATING_ACTIONS",
    "GOALS", "ASSISTS",
]

POSITION_GROUPS = {
    "GOALKEEPER": "GK", "CENTRAL_DEFENDER": "CB", "LEFT_WINGBACK_DEFENDER": "FB", "RIGHT_WINGBACK_DEFENDER": "FB",
    "DEFENSE_MIDFIELD": "MF", "CENTRAL_MIDFIELD": "MF", "ATTACKING_MIDFIELD": "MF", "LEFT_MIDFIELD": "MF",
    "RIGHT_MIDFIELD": "MF", "LEFT_WINGER": "W", "RIGHT_WINGER": "W", "CENTER_FORWARD": "CF",
}
GROUP_ORDER = ("GK", "CB", "FB", "MF", "W", "CF")
GROUP_LABELS = {"GK": "Goalkeepers", "CB": "Centre-backs", "FB": "Full-backs", "MF": "Midfielders", "W": "Wingers",
                "CF": "Forwards"}

# metric key -> (label, numerator KPIs, denominator KPIs or None for per-90, higher_is_better, decimals)
METRICS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...] | None, bool, int]] = {
    "pass_pct": ("Pass %", ("SUCCESSFUL_PASSES",), ("SUCCESSFUL_PASSES", "UNSUCCESSFUL_PASSES"), True, 0),
    "passes": ("Passes /90", ("SUCCESSFUL_PASSES",), None, True, 0),
    "xt": ("Threat /90", ("PXT_ATTACK",), None, True, 2),
    "bypassed": ("Opp. bypassed /90", ("BYPASSED_OPPONENTS",), None, True, 1),
    "duel_pct": ("Duels won %", ("WON_GROUND_DUELS", "WON_AERIAL_DUELS"),
                 ("WON_GROUND_DUELS", "WON_AERIAL_DUELS", "LOST_GROUND_DUELS", "LOST_AERIAL_DUELS"), True, 0),
    "aerial_pct": ("Aerial won %", ("WON_AERIAL_DUELS",), ("WON_AERIAL_DUELS", "LOST_AERIAL_DUELS"), True, 0),
    "wins": ("Ball wins /90", ("BALL_WIN_NUMBER",), None, True, 1),
    "losses": ("Ball losses /90", ("BALL_LOSS_NUMBER",), None, False, 1),
    "presses": ("Pressures /90", ("NUMBER_OF_PRESSES",), None, True, 1),
    "xg": ("xG /90", ("SHOT_XG",), None, True, 2),
    "shots": ("Shots /90", ("SHOT_AT_GOAL_NUMBER",), None, True, 1),
    "xa": ("xA /90", ("EXPECTED_GOAL_ASSISTS",), None, True, 2),
    "sca": ("Shot-creating /90", ("SHOT_CREATING_ACTIONS",), None, True, 1),
}
GROUP_METRICS = {
    "GK": ("pass_pct", "passes", "xt", "bypassed", "losses"),
    "CB": ("pass_pct", "bypassed", "duel_pct", "aerial_pct", "wins", "losses"),
    "FB": ("pass_pct", "xt", "bypassed", "duel_pct", "wins", "presses"),
    "MF": ("pass_pct", "xt", "bypassed", "wins", "presses", "losses"),
    "W": ("xt", "bypassed", "xg", "xa", "sca", "losses"),
    "CF": ("xg", "shots", "xa", "xt", "duel_pct", "presses"),
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
    sums = ",\n  ".join(f'sum(coalesce(k.value:{c}::float, 0)) as "{c}"' for c in KPI_COLUMNS)
    return f"""
select e.MATCH_ID as "matchId", k.value:playerId::int as "playerId", k.value:position::string as "position",
  {sums}
from CAFC_DB.IMPECT_RAW.EVENTS e, lateral flatten(input => parse_json(e.EVENT_KPIS)) k
where e.ITERATION_ID = {int(iteration_id)} and e.EVENT_KPIS is not null and {match_filter}
group by 1, 2, 3"""


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
    return collapse_positions(kpis.merge(minutes, on=["matchId", "playerId"], how="inner"))


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
    """The metric over ``frame`` (a pooled sum, so many matches / players combine correctly)."""
    _, num, den, _, _ = METRICS[key]
    n = float(frame[list(num)].to_numpy().sum())
    if den is not None:
        d = float(frame[list(den)].to_numpy().sum())
        return n / d * 100.0 if d > 0 else None
    minutes = float(frame["minutes"].sum())
    return n / minutes * 90.0 if minutes > 0 else None


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


def build_player_tables(history: pd.DataFrame, today: pd.DataFrame, squad_id: int) -> list[dict[str, Any]]:
    """Groups of player rows for one squad in the reported match.

    ``history`` is every earlier match of the season; ``today`` the reported match rows. A player is
    placed in the group of the position he played most today, and his metrics are rated against his own
    earlier rates (season) and the league's pooled rate for that group."""
    mine = today[today["squadId"] == squad_id]
    out: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
    for pid, rows in mine.groupby("playerId"):
        main = rows.sort_values("minutes", ascending=False).iloc[0]
        group = main["group"]
        if group not in out:
            continue
        minutes = float(rows["minutes"].max())
        mine_before = history[(history["playerId"] == pid)]
        league = history[history["group"] == group]
        enough_history = float(mine_before["minutes"].sum()) >= MIN_SEASON_MINUTES
        cells = []
        for key in GROUP_METRICS[group]:
            label, _, _, better, decimals = METRICS[key]
            value = _rate(rows, key)
            season = _rate(mine_before, key) if enough_history else None
            lg = _rate(league, key)
            rated = minutes >= MIN_MATCH_MINUTES
            cells.append({"key": key, "value": value, "decimals": decimals,
                          "season": verdict(value, season, better) if rated else "",
                          "league": verdict(value, lg, better) if rated else "",
                          "season_value": season, "league_value": lg})
        out[group].append({"playerId": int(pid), "minutes": round(minutes), "cells": cells})
    return [{"group": g, "label": GROUP_LABELS[g], "columns": [METRICS[k][0] for k in GROUP_METRICS[g]],
             "players": sorted(out[g], key=lambda p: -p["minutes"])} for g in GROUP_ORDER if out[g]]


def season_to_date(match_id: int, iteration_id: int, kickoff: str, env_path: str = ".env",
                   refresh: bool = False) -> pd.DataFrame:
    """Every player-match of the season up to and including ``match_id``, cached on disk.

    Matches are final once played, so only matches missing from the cache are queried."""
    cache = CACHE_DIR / f"player_matches_{int(iteration_id)}_v2.parquet"
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


def _format(value: float | None, key: str) -> str:
    if value is None:
        return "–"
    decimals = METRICS[key][4]
    return f"{value:.{decimals}f}" + ("%" if METRICS[key][2] is not None else "")


def _both(season: str, league: str) -> str:
    """One verdict for the value cell from its two comparisons: up / down / level, 'mixed' when they disagree."""
    scores = [{"up": 1, "down": -1, "level": 0}[v] for v in (season, league) if v]
    if not scores:
        return ""
    if 1 in scores and -1 in scores:
        return "mixed"
    total = sum(scores)
    return "up" if total > 0 else ("down" if total < 0 else "level")


def players_context(all_rows: pd.DataFrame, events: pd.DataFrame, teams: tuple[str, str], match_id: int) -> dict[str, Any]:
    """Template context: one page per position group, both teams on it. Players are the columns
    (the subject's first), the group's metrics are the rows, and each player has three cells:
    today's value, his own earlier average and the league average, tinted by the comparison."""
    today = all_rows[all_rows["matchId"] == match_id]
    if today.empty:
        return {}
    history = all_rows[(all_rows["matchId"] != match_id) & (all_rows["kickoff"] < today["kickoff"].iloc[0])]
    names = events.dropna(subset=["playerId"]).drop_duplicates("playerId").set_index("playerId")["playerName"]
    by_team: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for team in teams:
        squad = events.loc[events["squadName"] == team, "squadId"].dropna()
        if squad.empty:
            return {}
        by_team[team] = {g["group"]: g["players"] for g in build_player_tables(history, today, int(squad.iloc[0]))}

    pages = []
    for group in GROUP_ORDER:
        keys = GROUP_METRICS[group]
        columns, players = [], []
        for i, team in enumerate(teams):
            for p in by_team[team].get(group, []):
                shirt = today.loc[today["playerId"] == p["playerId"], "shirt"]
                columns.append({"team": team, "is_subject": i == 0,
                                "name": str(names.get(p["playerId"], "")).split()[-1] or str(p["playerId"]),
                                "shirt": int(shirt.iloc[0]) if len(shirt) and pd.notna(shirt.iloc[0]) else "",
                                "minutes": p["minutes"], "rated": p["minutes"] >= MIN_MATCH_MINUTES})
                players.append(p)
        rows = [{"label": "Minutes", "cells": [{"text": f"{p['minutes']}'", "own": "", "league": "", "v_own": "",
                                                "v_league": "", "v_both": ""} for p in players], "is_minutes": True}]
        for k, key in enumerate(keys):
            cells = []
            for p in players:
                c = p["cells"][k]
                cells.append({"text": _format(c["value"], key), "own": _format(c["season_value"], key),
                              "league": _format(c["league_value"], key), "v_own": c["season"], "v_league": c["league"],
                              "v_both": _both(c["season"], c["league"])})
            rows.append({"label": METRICS[key][0], "cells": cells, "is_minutes": False})
        pages.append({"key": group.lower(), "label": GROUP_LABELS[group], "columns": columns, "rows": rows})
    return {"player_pages": pages, "player_baseline_matches": int(history["matchId"].nunique())}

"""Transition metrics: what happens in the seconds after a team loses the ball (defending) and after it
wins the ball (attacking). Pure pandas over the match events already loaded for the report.

* A *loss* is an event with ``BALL_LOSS_NUMBER == 1``; a *regain* is ``BALL_WIN_NUMBER == 1``.
* A shot counts as "after" a loss / regain when it falls within ``WINDOW_S`` seconds in the same period
  and the ball did not change hands in between (the same continuity rule the report already used).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.report.expanded.inpossession import PACKING_ZONE_GROUPS

WINDOW_S = 15.0           # a shot this soon after a change of possession is "caused" by it
COUNTERPRESS_S = 5.0      # a regain this soon after a loss is a counter-press win
REGAIN_CAP_S = 20.0       # longer than this and the ball is treated as not won back
BUCKETS = (("under 3 s", 0.0, 3.0), ("3–5 s", 3.0, 5.0), ("5–10 s", 5.0, 10.0), ("10–20 s", 10.0, 20.0))
THIRD_NAMES = ("Defensive third", "Middle third", "Attacking third")


def _flag(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(0, index=frame.index)
    return pd.to_numeric(frame[name], errors="coerce").fillna(0)


def _third(x: float) -> int:
    return 0 if x < -17.5 else (1 if x < 17.5 else 2)


def _minute(t: float) -> float:
    """Match minute for Impect's ``gameTimeInSec`` (the second half starts at 10000)."""
    return 45.0 + (t - 10000.0) / 60.0 if t >= 10000.0 else t / 60.0


def _surname(name: Any) -> str:
    return str(name).split()[-1] if isinstance(name, str) and name.strip() else "?"


def _after(events: pd.DataFrame, t: float, period: Any, keeper: str, shooter: str) -> tuple[int, float, float | None]:
    """Shots by ``shooter`` in the window after ``t`` before ``keeper`` touches the ball again:
    ``(shots, xG, seconds to the first shot)``."""
    window = events[(events["periodId"] == period) & (events["gameTimeInSec"] > t)
                    & (events["gameTimeInSec"] <= t + WINDOW_S)]
    shots, xg, first = 0, 0.0, None
    for row in window.itertuples():
        if row.squadName == keeper and row.squadName != shooter:
            break                                    # the team that lost the ball touched it again
        if row.squadName == shooter and _flag(window.loc[[row.Index]], "SHOT_AT_GOAL_NUMBER").iloc[0] == 1:
            shots += 1
            xg += float(0 if pd.isna(row.SHOT_XG) else row.SHOT_XG)
            first = first if first is not None else float(row.gameTimeInSec) - t
    return shots, xg, first


def losses(events: pd.DataFrame, team: str, opponent: str) -> pd.DataFrame:
    """One row per ball loss by ``team``: where, who, how fast it was won back and what the opponent got from it."""
    ev = events.sort_values(["periodId", "gameTimeInSec"]).reset_index(drop=True)
    mine = ev[ev["squadName"] == team]
    lost = mine[_flag(mine, "BALL_LOSS_NUMBER") == 1]
    wins = mine[_flag(mine, "BALL_WIN_NUMBER") == 1]
    rows = []
    for r in lost.itertuples():
        later = wins[(wins["periodId"] == r.periodId) & (wins["gameTimeInSec"] > r.gameTimeInSec)
                     & (wins["gameTimeInSec"] <= r.gameTimeInSec + REGAIN_CAP_S)]
        regain_s = float(later["gameTimeInSec"].iloc[0] - r.gameTimeInSec) if len(later) else np.nan
        shots, xg, first = _after(ev, r.gameTimeInSec, r.periodId, team, opponent)
        x = pd.to_numeric(r.startAdjCoordinatesX, errors="coerce")
        rows.append({"minute": _minute(r.gameTimeInSec), "player": _surname(r.playerName),
                     "zone": PACKING_ZONE_GROUPS.get(str(r.startPackingZone)),
                     "third": _third(x) if pd.notna(x) else None, "x": x,
                     "y": pd.to_numeric(r.startAdjCoordinatesY, errors="coerce"), "regain_s": regain_s,
                     "regainer": _surname(later["playerName"].iloc[0]) if len(later) else None,
                     "shots": shots, "xg": xg})
    return pd.DataFrame(rows, columns=["minute", "player", "zone", "third", "x", "y", "regain_s", "regainer", "shots", "xg"])


def regains(events: pd.DataFrame, team: str, opponent: str) -> pd.DataFrame:
    """One row per ball win by ``team``: where, who, and the shots the team got within the window."""
    ev = events.sort_values(["periodId", "gameTimeInSec"]).reset_index(drop=True)
    mine = ev[ev["squadName"] == team]
    won = mine[_flag(mine, "BALL_WIN_NUMBER") == 1]
    rows = []
    for r in won.itertuples():
        shots, xg, first = _after(ev, r.gameTimeInSec, r.periodId, opponent, team)
        x = pd.to_numeric(r.startAdjCoordinatesX, errors="coerce")
        rows.append({"minute": _minute(r.gameTimeInSec), "player": _surname(r.playerName),
                     "zone": PACKING_ZONE_GROUPS.get(str(r.startPackingZone)),
                     "third": _third(x) if pd.notna(x) else None, "x": x,
                     "y": pd.to_numeric(r.startAdjCoordinatesY, errors="coerce"), "shots": shots, "xg": xg,
                     "first_shot_s": first})
    return pd.DataFrame(rows, columns=["minute", "player", "zone", "third", "x", "y", "shots", "xg", "first_shot_s"])


def regain_speed(frame: pd.DataFrame) -> dict[str, Any]:
    """Time-to-regain buckets for a ``losses`` frame: counts per bucket plus 'not won back', and the median."""
    n = len(frame)
    secs = frame["regain_s"]
    buckets = [{"label": label, "n": int(((secs >= lo) & (secs < hi)).sum())} for label, lo, hi in BUCKETS]
    buckets.append({"label": "not won back", "n": int(secs.isna().sum())})
    for b in buckets:
        b["pct"] = round(b["n"] / n * 100) if n else 0
    return {"n": n, "buckets": buckets, "median_s": round(float(secs.median()), 1) if secs.notna().any() else None,
            "counterpress_n": int((secs < COUNTERPRESS_S).sum()),
            "counterpress_pct": round(float((secs < COUNTERPRESS_S).sum()) / n * 100) if n else 0}


def counterpress_players(frame: pd.DataFrame, top: int = 8) -> list[dict[str, Any]]:
    """Who won the ball back within five seconds of a loss (a ``losses`` frame)."""
    quick = frame[frame["regain_s"] < COUNTERPRESS_S]
    counts = quick["regainer"].value_counts().head(top)
    return [{"name": str(k), "n": int(v)} for k, v in counts.items()]


def punished(frame: pd.DataFrame, top: int = 5) -> dict[str, Any]:
    """What the opponent got from a ``losses`` frame: totals, by zone and by third, and the costliest losses."""
    zone = frame.dropna(subset=["zone"]).groupby("zone").agg(losses=("xg", "size"), xg=("xg", "sum"), shots=("shots", "sum"))
    third = frame.dropna(subset=["third"]).groupby("third").agg(losses=("xg", "size"), xg=("xg", "sum"), shots=("shots", "sum"))
    costly = frame[frame["xg"] > 0].sort_values("xg", ascending=False).head(top)
    return {
        "n": len(frame), "shots": int(frame["shots"].sum()), "xg": round(float(frame["xg"].sum()), 2),
        "with_shot": int((frame["shots"] > 0).sum()),
        "xg_by_zone": {z: round(float(v), 2) for z, v in zone["xg"].items()},
        "losses_by_zone": {z: int(v) for z, v in zone["losses"].items()},
        "by_third": [{"name": THIRD_NAMES[int(i)], "losses": int(r.losses), "xg": round(float(r.xg), 2), "shots": int(r.shots)}
                     for i, r in third.sort_index().iterrows()],
        "costliest": [{"minute": f"{int(r.minute)}'", "player": r.player, "zone": r.zone or "–",
                       "xg": round(float(r.xg), 2), "shots": int(r.shots)} for r in costly.itertuples()],
    }


def attacking(frame: pd.DataFrame, top: int = 8) -> dict[str, Any]:
    """Summary of a ``regains`` frame: regains that became shots, xG created, how quickly, who started attacks."""
    led = frame[frame["shots"] > 0]
    starters = led["player"].value_counts().head(top)
    by_zone = frame.dropna(subset=["zone"]).groupby("zone").agg(wins=("xg", "size"), xg=("xg", "sum"))
    by_third = frame.dropna(subset=["third"]).groupby("third").agg(wins=("xg", "size"), xg=("xg", "sum"), shots=("shots", "sum"))
    return {
        "n": len(frame), "with_shot": len(led), "shot_pct": round(len(led) / len(frame) * 100) if len(frame) else 0,
        "shots": int(frame["shots"].sum()), "xg": round(float(frame["xg"].sum()), 2),
        "median_first_shot_s": round(float(led["first_shot_s"].median()), 1) if len(led) else None,
        "xg_by_zone": {z: round(float(v), 2) for z, v in by_zone["xg"].items()},
        "wins_by_zone": {z: int(v) for z, v in by_zone["wins"].items()},
        "by_third": [{"name": THIRD_NAMES[int(i)], "wins": int(r.wins), "xg": round(float(r.xg), 2), "shots": int(r.shots)}
                     for i, r in by_third.sort_index().iterrows()],
        "starters": [{"name": str(k), "n": int(v)} for k, v in starters.items()],
    }


# --------------------------------------------------------------------------- #
# Report context: maps, tables and tiles for the two transition pages
# --------------------------------------------------------------------------- #
ROWS = 5            # rows in the table under each pitch


def losers(frame: pd.DataFrame, top: int = 4) -> list[dict[str, Any]]:
    """Players whose ball losses were followed by an opponent shot (a ``losses`` frame)."""
    counts = frame[frame["shots"] > 0]["player"].value_counts().head(top)
    return [{"name": str(k), "n": int(v)} for k, v in counts.items()]


def _pitch_map(frame: pd.DataFrame, colour: str, top: int = ROWS, vertical: bool = False) -> str:
    """Every event in grey; those followed by a shot as bubbles sized by xG; the costliest numbered."""
    from src.report import pitch

    pitch_obj, fig, ax = pitch._vertical_pitch((3.4, 5.2)) if vertical else pitch._horizontal_pitch((5.6, 3.6))
    f = frame.dropna(subset=["x", "y"])
    if len(f):
        x, y = pitch._to_pitch(f["x"], f["y"])
        pitch_obj.scatter(x, y, ax=ax, s=16, color="#cfc7b4", zorder=2)
    hot = f[f["xg"] > 0].sort_values("xg", ascending=False)
    if len(hot):
        x, y = pitch._to_pitch(hot["x"], hot["y"])
        pitch_obj.scatter(x, y, ax=ax, s=70 + hot["xg"].to_numpy() * 800, color=colour, alpha=.8,
                          edgecolors="white", zorder=3)
        for k, (px, py) in enumerate(zip(x.to_numpy()[:top], y.to_numpy()[:top]), 1):
            ax.text(*((py, px) if vertical else (px, py)), str(k), ha="center", va="center", fontsize=8, fontweight="bold", color="white", zorder=5)
    return pitch._fig_to_uri(fig)


def _padded(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    """Always ``ROWS`` rows so both teams' tables line up."""
    return (rows + [{k: "–" for k in keys}] * ROWS)[:ROWS]


def transition_context(events: pd.DataFrame, subject: str, opponent: str) -> dict[str, Any]:
    from src.report import palette


    teams = (subject, opponent)
    colour = {subject: palette.CHARLTON_RED, opponent: palette.OPPONENT_GREY}
    opp = {subject: opponent, opponent: subject}
    lost = {t: losses(events, t, opp[t]) for t in teams}
    won = {t: regains(events, t, opp[t]) for t in teams}
    punish = {t: punished(lost[t], ROWS) for t in teams}
    attack = {t: attacking(won[t]) for t in teams}
    speed = {t: regain_speed(lost[t]) for t in teams}
    from src.report.expanded.packing_zones import LABELS

    zone_label = lambda z: LABELS.get(z, z) if z and z != "–" else "–"

    def costly_rows(t: str) -> list[dict[str, Any]]:
        top = lost[t][lost[t]["xg"] > 0].sort_values("xg", ascending=False).head(ROWS)
        return [{"n": i, "minute": f"{int(r.minute)}'", "player": r.player, "zone": zone_label(r.zone),
                 "back": "not won back" if pd.isna(r.regain_s) else f"{r.regain_s:.0f} s", "shots": int(r.shots),
                 "xg": round(float(r.xg), 2)} for i, r in enumerate(top.itertuples(), 1)]

    def best_rows(t: str) -> list[dict[str, Any]]:
        top = won[t][won[t]["xg"] > 0].sort_values("xg", ascending=False).head(ROWS)
        return [{"n": i, "minute": f"{int(r.minute)}'", "player": r.player, "zone": zone_label(r.zone),
                 "to_shot": "–" if pd.isna(r.first_shot_s) else f"{r.first_shot_s:.1f} s", "shots": int(r.shots),
                 "xg": round(float(r.xg), 2)} for i, r in enumerate(top.itertuples(), 1)]

    defending, attacking_ctx = {}, {}
    for t in teams:
        sp, p, a = speed[t], punish[t], attack[t]
        defending[t] = {
            "summary": f"{p['n']} lost · {sp['counterpress_pct']}% won back within 5 s · {p['xg']:.2f} xG conceded ({p['shots']} shots)",
            "pitch": _pitch_map(lost[t], colour[t], vertical=True), "buckets": sp["buckets"],
            "median": f"{sp['median_s']} s" if sp["median_s"] is not None else "–",
            "counterpress": counterpress_players(lost[t], 4), "by_third": p["by_third"], "losers": losers(lost[t]),
            "rows": _padded(costly_rows(t), ("n", "minute", "player", "zone", "back", "shots", "xg")),
            "xg_max": max([r["xg"] for r in costly_rows(t)] + [1e-9]),
        }
        attacking_ctx[t] = {
            "summary": f"{a['n']} won · {a['shot_pct']}% ended in a shot within 15 s · {a['xg']:.2f} xG created ({a['shots']} shots)",
            "pitch": _pitch_map(won[t], colour[t]),
            "by_third": a["by_third"], "starters": a["starters"][:6],
            "rows": _padded(best_rows(t), ("n", "minute", "player", "zone", "to_shot", "shots", "xg")),
            "xg_max": max([r["xg"] for r in best_rows(t)] + [1e-9]),
        }
    return {"trans_defending": defending, "trans_attacking": attacking_ctx}

"""Game state and phase splits: how the match changed with the score and the clock.

Everything is cut from the Impect events already loaded. The score timeline comes from GOAL events
(own goals count for the other side), the subject team's state is leading / level / trailing, and
each slice of the match (a state, a half, before / after the first substitution, a 15-minute period)
gets the same measures for both teams: xG, shots, share of passes (possession), pressures and
regains in the opposition half.
"""
from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from src.report import metrics, palette
from src.report.expanded import overview

STATES = (("leading", "Leading"), ("level", "Level"), ("trailing", "Trailing"))
STATE_COLOURS = {"leading": palette.CHARLTON_RED, "level": "#a39d8f", "trailing": "#4a4538"}
PERIODS = ((0, 15), (15, 30), (30, 45), (45, 60), (60, 75), (75, 90))
PERIOD_LABELS = ("0–15'", "15–30'", "30–45'", "45–60'", "60–75'", "75–90'")
SMALL_SAMPLE_MINUTES = 10.0


def with_minutes(events: pd.DataFrame) -> pd.DataFrame:
    """Events with a numeric ``minute`` (stoppage folded into the half) and a ``period_bin`` (0-5)."""
    out = events.copy()
    out["minute"] = out["gameTime"].astype(str).map(metrics.minute_num)
    cap = np.where(pd.to_numeric(out["periodId"], errors="coerce") == 1, 44.999, 89.999)
    out["period_bin"] = (np.minimum(out["minute"].to_numpy(), cap) // 15).astype(int)
    return out


def goal_minutes(events: pd.DataFrame) -> list[tuple[float, str, str]]:
    """``(minute, scoring team, scorer)`` in order; an own goal is credited to the other team."""
    home, away = str(events["homeSquadName"].iloc[0]), str(events["awaySquadName"].iloc[0])
    ev = with_minutes(events) if "minute" not in events else events
    out = []
    for r in ev[(ev["action"] == "GOAL") | (ev["actionType"] == "OWN_GOAL")].sort_values("gameTimeInSec").itertuples():
        team = str(r.squadName)
        if r.actionType == "OWN_GOAL":
            team = away if team == home else home
        out.append((float(r.minute), team, str(r.playerName)))
    return out


def state_intervals(goals: list[tuple[float, str, str]], subject: str, end: float) -> list[dict[str, Any]]:
    """Consecutive slices of the match with the subject's state: ``start``, ``end``, ``state``, ``diff``."""
    cuts = [0.0] + [g[0] for g in goals] + [end]
    out, diff = [], 0
    for i in range(len(cuts) - 1):
        if i > 0:
            diff += 1 if goals[i - 1][1] == subject else -1
        if cuts[i + 1] > cuts[i]:
            state = "leading" if diff > 0 else ("trailing" if diff < 0 else "level")
            out.append({"start": cuts[i], "end": cuts[i + 1], "state": state, "diff": diff})
    return out


def _slice_measures(ev: pd.DataFrame, pressure: pd.DataFrame, subject: str, opponent: str, minutes: float) -> dict[str, Any]:
    def team(frame: pd.DataFrame, name: str) -> pd.DataFrame:
        return frame[frame["squadName"] == name]

    shots = ev[pd.to_numeric(ev.get("SHOT_AT_GOAL_NUMBER", 0), errors="coerce").fillna(0) == 1]
    passes = ev[ev["actionType"] == "PASS"]
    passes_s, passes_o = len(team(passes, subject)), len(team(passes, opponent))
    regain = ev[(pd.to_numeric(ev.get("BALL_WIN_NUMBER", 0), errors="coerce").fillna(0) == 1)
                & (pd.to_numeric(ev["startAdjCoordinatesX"], errors="coerce") > 0)]
    press_s, press_o = len(team(pressure, subject)), len(team(pressure, opponent))
    per_min = (lambda n: round(n / minutes, 2)) if minutes > 0 else (lambda n: 0.0)
    return {
        "minutes": round(minutes, 1), "small": bool(minutes < SMALL_SAMPLE_MINUTES),
        "xg_for": round(float(team(shots, subject)["SHOT_XG"].sum()), 2),
        "xg_against": round(float(team(shots, opponent)["SHOT_XG"].sum()), 2),
        "shots_for": len(team(shots, subject)), "shots_against": len(team(shots, opponent)),
        "possession": round(passes_s / (passes_s + passes_o) * 100) if passes_s + passes_o else None,
        "pressures_for": press_s, "pressures_against": press_o,
        "pressures_per_min": per_min(press_s), "regains": len(team(regain, subject)),
    }


def _between(frame: pd.DataFrame, start: float, end: float) -> pd.DataFrame:
    """Events in the minutes after ``start`` up to and including ``end``: an event at the very minute of a goal
    (the goal itself) belongs to the state before it. The match start is inclusive."""
    after = frame["minute"] >= 0 if start <= 0 else frame["minute"] > start
    return frame[after & (frame["minute"] <= end)]


def slice_row(label: str, ev: pd.DataFrame, pressure: pd.DataFrame, subject: str, opponent: str,
              ranges: list[tuple[float, float]]) -> dict[str, Any]:
    """Measures for the union of minute ranges (a state can occur more than once)."""
    parts = [_between(ev, a, b) for a, b in ranges]
    pparts = [_between(pressure, a, b) for a, b in ranges]
    ev_s = pd.concat(parts) if parts else ev.iloc[0:0]
    pr_s = pd.concat(pparts) if pparts else pressure.iloc[0:0]
    minutes = sum(b - a for a, b in ranges)
    return {"label": label, **_slice_measures(ev_s, pr_s, subject, opponent, minutes)}


def game_state_tables(events: pd.DataFrame, pressure: pd.DataFrame, subject: str, opponent: str,
                      first_sub_minute: float | None = None) -> dict[str, Any]:
    ev = with_minutes(events)
    pr = pressure.merge(ev[["eventId", "minute"]].drop_duplicates("eventId"), on="eventId", how="left")
    end = float(ev["minute"].max())
    goals = goal_minutes(ev)
    intervals = state_intervals(goals, subject, end)

    states = []
    for key, label in STATES:
        ranges = [(i["start"], i["end"]) for i in intervals if i["state"] == key]
        if ranges:
            states.append({"key": key, **slice_row(label, ev, pr, subject, opponent, ranges)})
    first_half_end = float(ev.loc[pd.to_numeric(ev["periodId"], errors="coerce") == 1, "minute"].max())
    other = [slice_row("First half", ev, pr, subject, opponent, [(0.0, first_half_end)]),
             slice_row("Second half", ev, pr, subject, opponent, [(first_half_end, end)])]
    if first_sub_minute is not None and 0 < first_sub_minute < end:
        other += [slice_row(f"Before the first substitution ({first_sub_minute:.0f}')", ev, pr, subject, opponent,
                            [(0.0, first_sub_minute)]),
                  slice_row("After the first substitution", ev, pr, subject, opponent, [(first_sub_minute, end)])]

    periods = []
    for i, (a, b) in enumerate(PERIODS):
        e = ev[ev["period_bin"] == i]
        p = pr[(pr["minute"].notna()) & (np.minimum(pr["minute"], 89.999) // 15 == i)]
        m = _slice_measures(e, p, subject, opponent, 15.0)
        passes = e[e["actionType"] == "PASS"]
        shots = e[pd.to_numeric(e.get("SHOT_AT_GOAL_NUMBER", 0), errors="coerce").fillna(0) == 1]
        periods.append({"label": PERIOD_LABELS[i],
                        "xg": (m["xg_for"], m["xg_against"]), "pressures": (m["pressures_for"], m["pressures_against"]),
                        "possession": (m["possession"] if m["possession"] is not None else 50,
                                       100 - m["possession"] if m["possession"] is not None else 50),
                        "shots": (m["shots_for"], m["shots_against"]), "passes": len(passes), "n_shots": len(shots)})
    first_goal = goals[0] if goals else None
    return {"states": states, "other": other, "periods": periods, "intervals": intervals, "goals": goals, "end": end,
            "first_goal": first_goal}


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def state_band_chart(data: dict[str, Any], subject: str) -> str:
    """The subject's state across the match on the shared 0-98 minute axis, goals marked."""
    font = 10.5
    fig, ax = plt.subplots(figsize=(16.0, 1.5), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.97, bottom=0.3)
    ax.set_facecolor(palette.PAPER)
    overview._style_time_axis(ax, font)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    shade = {"leading": ("#d01012", "#a00d0f"), "level": ("#a39d8f", "#a39d8f"), "trailing": ("#6b6455", "#3d3829")}
    for iv in data["intervals"]:
        colour = shade[iv["state"]][0 if abs(iv["diff"]) <= 1 else 1]
        ax.add_patch(Rectangle((iv["start"], .14), iv["end"] - iv["start"], .5, facecolor=colour,
                               edgecolor=palette.PAPER, linewidth=1.5, zorder=2))
        if iv["end"] - iv["start"] >= 7:
            by = f" by {abs(iv['diff'])}" if iv["diff"] else ""
            ax.text((iv["start"] + iv["end"]) / 2, .39, dict(STATES)[iv["state"]] + by, ha="center", va="center",
                    fontsize=font, color="white", fontweight="bold", zorder=4)
    for k, (minute, team, scorer) in enumerate(data["goals"]):
        mine = team == subject
        y = .93 if k % 2 == 0 else .78                       # alternate rows so neighbouring goals never overlap
        ax.scatter([minute], [y], s=110, c=palette.CHARLTON_RED if mine else palette.OPPONENT_GREY,
                   edgecolors=palette.PAPER, linewidths=1.2, zorder=5)
        ax.plot([minute, minute], [.64, y], color=palette.HAIR, lw=.8, zorder=1)
        ax.text(min(minute + 1.0, overview.X_AXIS_MAX - 8), y, f"{str(scorer).split()[-1]} {int(minute)}'", va="center",
                fontsize=font - 1, color=palette.INK, fontweight="bold" if mine else "normal", zorder=6)
    ax.spines["bottom"].set_visible(False)
    return overview._png_uri(fig, tight=False, dpi=200)


def period_chart(periods: list[dict[str, Any]], subject_colour: str, opponent_colour: str) -> str:
    """Three small multiples over the six 15-minute periods: xG, possession, pressures; both teams."""
    font = 10.5
    fig, axes = plt.subplots(1, 3, figsize=(16.0, 3.1), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.035, right=0.995, top=0.86, bottom=0.14, wspace=0.12)
    x = np.arange(len(periods))
    for ax, key, title, fmt in zip(axes, ("xg", "possession", "pressures"),
                                   ("xG", "Share of passes (%)", "Pressures"), ("{:.2f}", "{:.0f}", "{:.0f}")):
        ax.set_facecolor(palette.PAPER)
        a = [p[key][0] for p in periods]
        b = [p[key][1] for p in periods]
        ax.bar(x - .2, a, .38, color=subject_colour, zorder=3)
        ax.bar(x + .2, b, .38, color=opponent_colour, zorder=3)
        top = max(a + b + [1e-9])
        for xi, v in zip(x - .2, a):
            ax.text(xi, v + top * .02, fmt.format(v), ha="center", va="bottom", fontsize=font - 2, color=palette.INK)
        for xi, v in zip(x + .2, b):
            ax.text(xi, v + top * .02, fmt.format(v), ha="center", va="bottom", fontsize=font - 2, color=palette.MUTED)
        ax.set_xticks(x)
        ax.set_xticklabels([p["label"] for p in periods], fontsize=font - 1.5, color=palette.MUTED)
        ax.set_ylim(0, top * 1.18)
        ax.set_yticks([])
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(palette.HAIR)
        ax.tick_params(length=0)
        ax.set_title(title, loc="left", fontsize=font, fontweight="bold", color=palette.INK)
    return overview._png_uri(fig, tight=False, dpi=200)


def gamestate_context(events: pd.DataFrame, pressure: pd.DataFrame, subject: str, opponent: str,
                      first_sub_minute: float | None = None) -> dict[str, Any]:
    data = game_state_tables(events, pressure, subject, opponent, first_sub_minute)
    return {
        "gamestate": {k: data[k] for k in ("states", "other", "end", "first_goal")},
        "gamestate_band_img": state_band_chart(data, subject),
        "gamestate_period_img": period_chart(data["periods"], palette.CHARLTON_RED, palette.OPPONENT_GREY),
    }

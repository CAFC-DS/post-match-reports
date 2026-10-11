"""The match summary page: facts in plain sentences, built by rules from numbers already computed.

No advice and no free text: every line is a measurement (what happened, by how much, against
what), phrased the same way every match.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.report import metrics
from src.report.expanded import season_baseline as sb

_PCT_KEYS = {"possession_pct", "pass_accuracy_pct", "duels_won_pct"}
_DEC_KEYS = {"non_penalty_xg", "set_piece_xg", "packing_xt"}


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _fmt(key: str, value: float) -> str:
    if key in _PCT_KEYS:
        return f"{value:.0f}%"
    if key in _DEC_KEYS:
        return f"{value:.2f}"
    if key == "pressing_intensity":
        return f"PPDA {abs(value):.1f}"
    return f"{value:.0f}"


def score_and_scorers(events: pd.DataFrame, subject: str, opponent: str) -> dict[str, Any]:
    """Final and half-time score from the goal events, with scorers by team."""
    goals = metrics.goal_events(events)
    first_half_end = float(events.loc[pd.to_numeric(events["periodId"], errors="coerce") == 1, "gameTimeInSec"].max())
    totals = {subject: 0, opponent: 0}
    half = {subject: 0, opponent: 0}
    scorers: dict[str, list[dict[str, str]]] = {subject: [], opponent: []}
    home = str(events["homeSquadName"].iloc[0])
    own = events[events["actionType"] == "OWN_GOAL"]
    for g in goals:
        totals[g.team] += 1
        half[g.team] += int(g.game_time_sec <= first_half_end)
        scorers[g.team].append({"who": g.player.split()[-1], "minute": f"{int(g.minute)}'"})
    for r in own.itertuples():                                 # an own goal counts for the other side
        other = opponent if str(r.squadName) == subject else subject
        totals[other] += 1
        half[other] += int(r.gameTimeInSec <= first_half_end)
        scorers[other].append({"who": f"{str(r.playerName).split()[-1]} (og)", "minute": f"{int(metrics.minute_num(str(r.gameTime)))}'"})
    return {"score": totals, "half_time": half, "scorers": scorers, "home": home}


def key_numbers(stats: pd.DataFrame, subject: str, opponent: str) -> list[dict[str, str]]:
    """Both teams' headline numbers, one row each."""
    def duels(team: str) -> float:
        won = lambda t: float(stats.loc[t, "won_ground_duels"] + stats.loc[t, "won_aerial_duels"])
        total = won(subject) + won(opponent)
        return won(team) / total * 100 if total else 0.0

    rows = [("Possession", lambda t: f"{stats.loc[t, 'possession_pct']:.0f}%"),
            ("Shots (on target)", lambda t: f"{int(stats.loc[t, 'shots'])} ({int(stats.loc[t, 'shots_on_target'])})"),
            ("Expected goals (xG)", lambda t: f"{stats.loc[t, 'non_penalty_xg']:.2f}"),
            ("Pass accuracy", lambda t: f"{stats.loc[t, 'pass_accuracy_pct']:.0f}%"),
            ("Duels won", lambda t: f"{duels(t):.0f}%"),
            ("Opposition-half regains", lambda t: f"{int(stats.loc[t, 'opponent_half_regains'])}")]
    return [{"label": label, "subject": fn(subject), "opponent": fn(opponent)} for label, fn in rows]


def how_it_went(gs: dict[str, Any], stats: pd.DataFrame, subject: str, opponent: str) -> list[str]:
    """Sentences about the shape of the game: score states, first goal, chances, the sharpest spell."""
    lines = []
    minutes = {s["key"]: s["minutes"] for s in gs["states"]}
    parts = [f"{minutes[k]:.0f} minutes {word}" for k, word in (("leading", "leading"), ("level", "level"),
                                                                 ("trailing", "trailing")) if minutes.get(k)]
    if parts:
        never = " and never led" if not minutes.get("leading") else ""
        lines.append(f"{subject} spent " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + f"{never}.")
    if gs["first_goal"]:
        minute, team, scorer = gs["first_goal"]
        lines.append(f"First goal: {str(scorer).split()[-1]} for {team} after {int(minute)} minutes.")
    xg = lambda t: float(stats.loc[t, "non_penalty_xg"])
    shots = lambda t: (int(stats.loc[t, "shots"]), int(stats.loc[t, "shots_on_target"]))
    lines.append(f"{subject} created {xg(subject):.2f} xG from {shots(subject)[0]} shots ({shots(subject)[1]} on target); "
                 f"{opponent} created {xg(opponent):.2f} xG from {shots(opponent)[0]} ({shots(opponent)[1]} on target).")
    periods = gs.get("periods") or []
    best = max(((p["xg"][i], p["label"], (subject, opponent)[i]) for p in periods for i in (0, 1)), default=None)
    if best and best[0] > 0:
        lines.append(f"The most dangerous spell was {best[1]}, when {best[2]} created {best[0]:.2f} xG.")
    lines.append(f"{subject} made {stats.loc[subject, 'possession_pct']:.0f}% of the passes.")
    halves = {r["label"]: r for r in gs.get("other", [])}
    if "First half" in halves and "Second half" in halves:
        a, b = halves["First half"], halves["Second half"]
        lines.append(f"By half, xG was {a['xg_for']:.2f}–{a['xg_against']:.2f} in the first and "
                     f"{b['xg_for']:.2f}–{b['xg_against']:.2f} in the second; {subject} pressed {a['pressures_per_min']:.1f} "
                     f"times a minute before the break and {b['pressures_per_min']:.1f} after it.")
    after = next((r for r in gs.get("other", []) if r["label"] == "After the first substitution"), None)
    before = next((r for r in gs.get("other", []) if r["label"].startswith("Before the first substitution")), None)
    if before and after:
        lines.append(f"{before['label'].split('(')[1].rstrip(')')} was the first change: xG was "
                     f"{before['xg_for']:.2f}–{before['xg_against']:.2f} before it and {after['xg_for']:.2f}–"
                     f"{after['xg_against']:.2f} after it.")
    return lines


def against_the_season(match_values: dict[str, float], baseline: pd.DataFrame,
                       wheel_metrics: list[tuple[str, str, str, bool]], subject: str, n: int = 3) -> dict[str, list[str]]:
    """The measures furthest above and below the subject's own average across the baseline matches."""
    ranked = []
    for _category, col, label, higher_is_better in wheel_metrics:
        pct = sb.percentile_of(baseline, col, match_values[col])
        if not higher_is_better:
            pct = 100 - pct
        ranked.append((pct, label.replace("\n", " "), col))
    ranked.sort()
    sentence = lambda pct, label, col: (
        f"{label}: {_fmt(col, match_values[col])} against an average of {_fmt(col, float(baseline[col].mean()))} "
        f"({_ordinal(round(pct))} percentile of {len(baseline)} matches)")
    return {"above": [sentence(*r) for r in reversed(ranked[-n:])], "below": [sentence(*r) for r in ranked[:n]]}


def standouts(player_pages: list[dict[str, Any]], n: int = 3) -> list[dict[str, Any]]:
    """Players better than both averages in the most measures (rated appearances only)."""
    found = []
    for page in player_pages:
        for j, col in enumerate(page["columns"]):
            if not col["rated"]:
                continue
            cells = [(row["label"], row["cells"][j]) for row in page["rows"]]
            rated = [(label, c) for label, c in cells if c["v_both"]]
            ups = [(label, c) for label, c in rated if c["v_both"] == "up"]
            if rated:
                found.append({"name": col["name"], "position": page["label"].lower(), "ups": len(ups), "rated": len(rated),
                              "best": [f"{label} {c['text']}" for label, c in ups[:3]], "minutes": col["minutes"]})
    found.sort(key=lambda f: (-f["ups"] / f["rated"], -f["minutes"]))
    return found[:n]


def summary_context(events: pd.DataFrame, stats: pd.DataFrame, match_values: dict[str, float], baseline: pd.DataFrame,
                    wheel_metrics: list[tuple[str, str, str, bool]], gs: dict[str, Any],
                    player_pages: list[dict[str, Any]] | None, subject: str, opponent: str) -> dict[str, Any]:
    return {"summary": {
        **score_and_scorers(events, subject, opponent),
        "went": how_it_went(gs, stats, subject, opponent),
        "numbers": key_numbers(stats, subject, opponent),
        "season": against_the_season(match_values, baseline, wheel_metrics, subject),
        "standouts": standouts(player_pages or []),
    }}

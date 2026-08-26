"""Charlton's 25/26 season-to-date baselines for the expanded analyst report.

The reference report (matchday 1 of 26/27, no current-season history yet)
compares the reported match against Charlton's full 25/26 season -- see the
"CAFC BASELINE" column on the Match Stats panel and the "percentile vs CAFC
25/26 averages" caption on the Team Performance wheel. Both need one row per
25/26 Charlton fixture with a fixed catalogue of per-match metrics, which
this module builds once (46 Snowflake round-trips) and caches to disk.

Metric definitions not already covered by ``metrics.team_stats`` (progressive
actions, passes into the final third, pressing intensity/PPDA, counter-press
regains) are reconstructed here using standard, documented definitions -- the
original implementation's exact formulas do not survive, so these are
best-effort and flagged as such in RECOVERY_NOTES.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.report import impect_cafcdb_source, metrics

CACHE_DIR = Path.home() / ".cache" / "charlton-post-match-analyst"
CACHE_PATH = CACHE_DIR / "season_baseline_1410.parquet"

# 25/26 Championship season, Charlton Athletic's 46 league fixtures
# (CAFC_DB.IMPECT_RAW.MATCHES, ITERATIONID=1410, home/away contains
# "Charlton Athletic"), oldest first.
SEASON_1410_MATCH_IDS: list[int] = [
    206531, 206543, 206555, 206574, 206590, 206589, 206602, 206617, 206633,
    206639, 206654, 206666, 206675, 206688, 206709, 206712, 206727, 206735,
    206759, 206770, 206784, 206799, 206825, 206832, 206843, 206854, 206874,
    207048, 206926, 206911, 206936, 206748, 207034, 206983, 207057, 206904,
    207033, 206986, 206915, 206905, 207016, 206899, 207050, 207054, 206902,
    207019,
]

# Progressive action: a successful pass or dribble that advances the ball at
# least 10m upfield (adjusted coordinates, so this is direction-agnostic).
_PROGRESSIVE_MIN_M = 10.0
# Final third boundary on a 105m-equivalent adjusted pitch (adjCoordinates
# run -52.5..52.5): the same 17.5m-from-the-defended-goal boundary already
# used for "touches in opposition box" elsewhere in metrics.py.
_FINAL_THIRD_X = 17.5
# Counter-press window: a regain within this many seconds of the team's own
# prior loss counts as a counter-press regain.
_COUNTER_PRESS_WINDOW_S = 5.0


def match_metrics(events: pd.DataFrame, team: str, opponent: str) -> dict[str, float]:
    stats = metrics.team_stats(events, team, opponent) if team < opponent else metrics.team_stats(events, opponent, team)
    row = stats.loc[team]
    opp_row = stats.loc[opponent]

    t = events.loc[events["squadName"] == team].copy()
    o = events.loc[events["squadName"] == opponent].copy()

    successful = t["actionType"].isin(["PASS", "DRIBBLE"]) & (
        (t.get("SUCCESSFUL_PASSES", 0) == 1) | (t["actionType"] == "DRIBBLE")
    )
    gained = pd.to_numeric(t["endAdjCoordinatesX"], errors="coerce") - pd.to_numeric(t["startAdjCoordinatesX"], errors="coerce")
    progressive_actions = int((successful & (gained >= _PROGRESSIVE_MIN_M)).sum())

    passes = t.loc[t["actionType"] == "PASS"]
    start_x = pd.to_numeric(passes["startAdjCoordinatesX"], errors="coerce")
    end_x = pd.to_numeric(passes["endAdjCoordinatesX"], errors="coerce")
    passes_into_final_third = int(
        ((passes.get("SUCCESSFUL_PASSES", 0) == 1) & (start_x < _FINAL_THIRD_X) & (end_x >= _FINAL_THIRD_X)).sum()
    )

    # PPDA: opponent passes completed in their own defensive 60% of the pitch
    # per defensive action the reported team makes in that same zone. Lower
    # is more intense pressing, so "pressing intensity" is reported as
    # -PPDA when ranked (a smaller PPDA should rank higher).
    opp_passes_own_half = o.loc[
        (o["actionType"] == "PASS") & (o.get("SUCCESSFUL_PASSES", 0) == 1)
        & (pd.to_numeric(o["startAdjCoordinatesX"], errors="coerce") < 0)
    ]
    team_def_actions_high = t.loc[
        t["action"].isin(["DUEL", "INTERCEPTION", "FOUL"])
        & (pd.to_numeric(t["startAdjCoordinatesX"], errors="coerce") < 0)
    ]
    ppda = float(len(opp_passes_own_half) / len(team_def_actions_high)) if len(team_def_actions_high) else float("nan")

    # Counter-press regains: the team wins the ball within 5s of its own
    # most recent loss, in the opponent's half (attacking pressure, not a
    # deep block regain).
    t_sorted = t.sort_values("gameTimeInSec")
    losses = t_sorted.loc[
        (t_sorted["result"] != "SUCCESS") & t_sorted["actionType"].isin(["PASS", "DRIBBLE"]), "gameTimeInSec"
    ].to_numpy()
    regains = t_sorted.loc[
        (pd.to_numeric(t_sorted.get("BALL_WIN_NUMBER", 0), errors="coerce") == 1)
        & (pd.to_numeric(t_sorted["startAdjCoordinatesX"], errors="coerce") > 0)
    ]
    counter_press = 0
    for _, r in regains.iterrows():
        rt = r["gameTimeInSec"]
        prior = losses[losses <= rt]
        if len(prior) and (rt - prior[-1]) <= _COUNTER_PRESS_WINDOW_S:
            counter_press += 1

    return {
        "possession_pct": float(row["possession_pct"]),
        "pass_accuracy_pct": float(row["pass_accuracy_pct"]),
        "non_penalty_xg": float(row["non_penalty_xg"]),
        "set_piece_xg": float(row["set_piece_xg"]),
        "shots": float(row["shots"]),
        "packing_xt": float(t["PXT_ATTACK"].sum()),
        # A win-rate, not a raw count: a team that spends the match without
        # the ball (like a 23%-possession Charlton) gets far more chances to
        # contest duels than a raw won-count reflects, so the count alone
        # ranked purely on volume rather than duel quality. Every ground/
        # aerial duel has exactly one winner, so the opponent's own won-duel
        # count is the team's lost-duel count -- no separate query needed.
        "duels_won_pct": float(
            (row["won_ground_duels"] + row["won_aerial_duels"])
            / max(row["won_ground_duels"] + row["won_aerial_duels"]
                  + opp_row["won_ground_duels"] + opp_row["won_aerial_duels"], 1) * 100
        ),
        "opposition_half_regains": float(row["opponent_half_regains"]),
        "progressive_actions": float(progressive_actions),
        "passes_into_final_third": float(passes_into_final_third),
        "pressing_intensity": -ppda if ppda == ppda else float("nan"),
        "counter_press_regains": float(counter_press),
        # Also carry the Match Stats panel's baseline fields.
        "successful_passes": float(row["successful_passes"]),
        "unsuccessful_passes": float(row["unsuccessful_passes"]),
        "passes_forward_pct": float(row["passes_forward_pct"]),
        "shots_on_target": float(row["shots_on_target"]),
        "packing_xg": float(row["packing_xg"]),
        "postshot_xg": float(row["postshot_xg"]),
        "opponents_bypassed": float(row["opponents_bypassed"]),
        "defenders_bypassed": float(row["defenders_bypassed"]),
        "touches_in_opposition_box": float(row["touches_in_opposition_box"]),
        "won_ground_duels": float(row["won_ground_duels"]),
        "won_aerial_duels": float(row["won_aerial_duels"]),
        "second_ball_wins": float(row["second_ball_wins"]),
    }


def build_season_baseline(charlton: str = "Charlton Athletic", refresh: bool = False) -> pd.DataFrame:
    """One row per 25/26 Charlton fixture, columns = per-match metric values."""
    if CACHE_PATH.exists() and not refresh:
        return pd.read_parquet(CACHE_PATH)

    rows = []
    for match_id in SEASON_1410_MATCH_IDS:
        events = impect_cafcdb_source.load_match_events(match_id)
        meta = metrics.match_meta(events)
        opponent = meta.away_team if meta.home_team == charlton else meta.home_team
        row = match_metrics(events, charlton, opponent)
        row["match_id"] = match_id
        row["opponent"] = opponent
        row["kickoff"] = meta.kickoff
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("kickoff").reset_index(drop=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE_PATH)
    return df


def percentile_of(baseline: pd.DataFrame, column: str, value: float) -> float:
    """Percentile rank (0-100) of ``value`` within the season distribution."""
    series = baseline[column].dropna()
    if series.empty:
        return 50.0
    return float((series < value).mean() * 100)

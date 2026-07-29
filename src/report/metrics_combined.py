"""Combines Impect and DVMS metrics into single, best-source-per-metric
panels for the combined board post-match report. Reuses metrics.py
(Impect) and metrics_dvms.py (DVMS) unmodified — this module only decides,
per panel, which source's number to show and merges/reranks where a panel
genuinely needs both.
"""

from __future__ import annotations

import pandas as pd

from src.report import metrics as impect_metrics
from src.report import metrics_dvms
from src.dvms.metrics.line_breaks import line_breaking_passes


def combined_team_stats(impect_events: pd.DataFrame, dvms_match) -> pd.DataFrame:
    """The 13-row match-stats table (metrics.STAT_ROWS / STAT_GLOSS,
    unmodified), with every value from Impect except ``possession_pct``,
    which comes from DVMS's tracked ball-touch share — the one row where
    tracking beats a pass-count proxy (see the design spec).

    Returns the same shape as metrics.team_stats: a DataFrame indexed by
    team name, one column per STAT_ROWS key.
    """
    meta = impect_metrics.match_meta(impect_events)
    home, away = meta.home_team, meta.away_team
    stats = impect_metrics.team_stats(impect_events, home, away).copy()

    for side, team in (("home", home), ("away", away)):
        stats.loc[team, "possession_pct"] = metrics_dvms.team_stat_values(dvms_match, side)["possession_pct"]
    return stats


def line_break_style_split(match, side: str) -> dict[str, float]:
    """Of this team's completed passes that broke an opposition tactical
    line (defence, midfield or attack — see line_breaks.py), the % that did
    so through, over, or around that line: DVMS tracking's answer to "how
    did they get in", shown as a caption under the (Impect-sourced) final
    third & box entries map.

    No ready-made %-split aggregator exists in line_breaks.py — only a
    passer x receiver combination_matrix — so this is new. A pass that
    breaks two lines appears twice in line_breaking_passes' output; dedup on
    event_id (keeping its first-encountered style, matching how
    combination_matrix already dedupes) before taking the split.
    """
    opponent_side = "away" if side == "home" else "home"
    breaks = line_breaking_passes(
        events=match.events,
        tracking=match.frames,
        pitch_meta=match.meta,
        lineups=match.f7.lineups,
        team_id=match.team_id_of(side),
        opponent_team_id=match.team_id_of(opponent_side),
        opponent_is_home=(opponent_side == "home"),
    )
    if breaks.empty:
        return {"through": 0.0, "over": 0.0, "around": 0.0, "n": 0}

    uniq = breaks.drop_duplicates(subset="event_id")
    counts = uniq["style"].value_counts()
    n = int(len(uniq))
    return {
        "through": float(counts.get("through", 0)) / n * 100,
        "over": float(counts.get("over", 0)) / n * 100,
        "around": float(counts.get("around", 0)) / n * 100,
        "n": n,
    }

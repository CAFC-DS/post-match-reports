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

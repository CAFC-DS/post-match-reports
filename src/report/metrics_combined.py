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


def blended_player_contributions(impect_events: pd.DataFrame, dvms_match, top_n: int = 10) -> pd.DataFrame:
    """Composite contribution ranking blending Impect on-ball value with
    DVMS physical output.

    Player identity is joined on lower-cased surname — there is no shared
    player id between Impect and Opta in this codebase (unlike the
    CAFC_PLAYER_ID cross-provider resolution DATA_MODEL.md documents for
    Impect-to-canonical joins; no Impect-to-Opta equivalent exists). A
    duplicate surname within one team's squad would collide silently; this
    is a known limitation, not yet hit in practice.

    Both source functions are called with a large top_n so the join has
    the full squads to work with, not just each source's own top-10 cut —
    re-ranking happens here, after blending, then the result is cut to
    ``top_n``.

    Composite = weighted sum of z-scored components: 40% Impect xT
    (attacking value added, the same metric both existing reports already
    rank by), 15% successful passes, 15% ground+aerial duels won, 10% xG,
    10% distance covered, 10% top speed (the last two from DVMS Second
    Spectrum physical data — the only components tracking-derived).
    Weights are a starting point, expected to need visual tuning against
    known matches; not treated as fixed science.
    """
    impect_all = impect_metrics.player_contributions(impect_events, top_n=1000)
    dvms_all = metrics_dvms.player_contributions_dvms(dvms_match, top_n=1000)

    impect_all = impect_all.assign(_key=impect_all["surname"].str.lower())
    dvms_physical = dvms_all.assign(_key=dvms_all["name"].str.lower())[["_key", "distance", "top_speed"]]

    merged = impect_all.merge(dvms_physical, on="_key", how="left").drop(columns="_key")

    def _z(s: pd.Series) -> pd.Series:
        std = s.std(ddof=0)
        return (s - s.mean()) / std if std else pd.Series(0.0, index=s.index)

    dist_mean = merged["distance"].mean()
    dist = merged["distance"].fillna(dist_mean if not pd.isna(dist_mean) else 0)
    speed_mean = merged["top_speed"].mean()
    speed = merged["top_speed"].fillna(speed_mean if not pd.isna(speed_mean) else 0)

    merged["composite"] = (
        0.40 * _z(merged["xt"])
        + 0.15 * _z(merged["passes"])
        + 0.15 * _z(merged["ground"] + merged["aerial"])
        + 0.10 * _z(merged["xg"])
        + 0.10 * _z(dist)
        + 0.10 * _z(speed)
    )
    return merged.sort_values("composite", ascending=False).head(top_n).reset_index(drop=True)

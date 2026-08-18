"""Provider selection for the canonical one-page post-match report.

Impect is the analytical spine. DVMS may override tracking-specific values
and enrich player rows, but must never change the Impect contribution order.
"""

from __future__ import annotations

import pandas as pd

from src.report import metrics as impect_metrics
from src.report import metrics_dvms
from src.dvms.metrics.line_breaks import line_breaking_passes


def combined_team_stats(impect_events: pd.DataFrame, dvms_match=None) -> pd.DataFrame:
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

    if dvms_match is not None:
        for side, team in (("home", home), ("away", away)):
            stats.loc[team, "possession_pct"] = metrics_dvms.team_stat_values(dvms_match, side)["possession_pct"]
    return stats


def entry_effectiveness(entries: pd.DataFrame) -> dict[str, float | int]:
    """Honest Impect fallback for the DVMS line-break classification."""
    total = int(len(entries))
    successful = int(entries["success"].fillna(False).sum()) if total else 0
    return {
        "total": total,
        "successful": successful,
        "completion_pct": successful / total * 100 if total else 0.0,
        "threat": float(entries["threat"].fillna(0.0).clip(lower=0.0).sum()) if total else 0.0,
    }


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


def enriched_player_contributions(impect_events: pd.DataFrame, dvms_match=None,
                                  top_n: int = 10) -> pd.DataFrame:
    """Rank by Impect xT and optionally attach DVMS physical output.

    Player identity is joined on ``(team, lower-cased surname)`` — there is
    no shared player id between Impect and Opta in this codebase (unlike
    the CAFC_PLAYER_ID cross-provider resolution DATA_MODEL.md documents
    for Impect-to-canonical joins; no Impect-to-Opta equivalent exists).
    The team component is resolved the same way ``combined_team_stats``
    resolves cross-vendor team identity: never by comparing the two
    providers' name strings directly (they can differ, e.g. "Charlton
    Athletic" vs an Opta abbreviation), but via the home/away side, which
    both providers agree on as a fact of the match. Each DVMS row's
    ``team_id`` is mapped to a side via ``dvms_match.side_of``, and that
    side is mapped to the Impect squad name via ``impect_metrics.match_meta``
    — the same pattern render_combined.py's ``side_to_team`` uses.

    Without a team component, a surname shared across *both* squads (e.g.
    two players named "Smith", one per team) would fan out in the merge —
    one Impect row matching DVMS rows from both teams — silently
    duplicating that player in the output and attaching the wrong team's
    physical data to them. Keying on (team, surname) prevents that
    cross-squad collision.

    A genuine surname collision *within* one squad (two same-surname
    players on the same team) is a known, accepted limitation: the
    DVMS-side frame is deduplicated to one row per (team, surname) before
    the merge, so such a collision degrades to one arbitrary match rather
    than fanning out to multiple rows, but the "wrong" of the two players
    may end up with the other's physical data. Not yet hit in practice.

    Physical values are display-only. Missing DVMS data yields the same rows
    in the same order with nullable physical columns.
    """
    impect_all = impect_metrics.player_contributions(impect_events, top_n=1000)
    physical_columns = ["minutes", "distance", "hsr", "sprinting", "top_speed"]
    if dvms_match is None:
        result = impect_all.copy()
        for column in physical_columns:
            result[column] = pd.NA
        result["sc_minutes"] = pd.NA
        result["sc_distance"] = pd.NA
        result["sc_hsr"] = pd.NA
        result["sc_sprint"] = pd.NA
        return result.sort_values("xt", ascending=False).head(top_n).reset_index(drop=True)

    dvms_all = metrics_dvms.player_contributions_dvms(dvms_match, top_n=1000)

    meta = impect_metrics.match_meta(impect_events)
    side_to_team = {"home": meta.home_team, "away": meta.away_team}

    impect_all = impect_all.assign(
        _team_key=impect_all["squadName"].str.strip().str.lower(),
        _name_key=impect_all["surname"].str.lower(),
    )

    dvms_all = dvms_all.assign(
        _team_key=dvms_all["team_id"].map(lambda t: side_to_team[dvms_match.side_of(t)]).str.strip().str.lower(),
        _name_key=dvms_all["name"].str.lower(),
    )
    dvms_all = dvms_all.drop_duplicates(subset=["_team_key", "_name_key"])
    for column in physical_columns:
        if column not in dvms_all:
            dvms_all[column] = pd.NA
    dvms_physical = dvms_all[["_team_key", "_name_key", *physical_columns]]

    merged = impect_all.merge(dvms_physical, on=["_team_key", "_name_key"], how="left")

    # Keep the established presentation names so the renderer does not need
    # to know its source. Unlike the prior SkillCorner-only wiring, these
    # values exist whenever the corresponding DVMS physical feed is present.
    merged["sc_minutes"] = merged["minutes"]
    merged["sc_distance"] = merged["distance"]
    merged["sc_hsr"] = merged["hsr"]
    merged["sc_sprint"] = merged["sprinting"]

    merged = merged.drop(columns=["_team_key", "_name_key"])

    return merged.sort_values("xt", ascending=False).head(top_n).reset_index(drop=True)


# Backwards-compatible import for callers outside this repository. Its
# behaviour intentionally follows the new stable Impect ranking contract.
blended_player_contributions = enriched_player_contributions

"""Assemble the one-page set-piece report (HTML + PDF).

Pulls the match context, computes the metrics, renders the pitch graphics, then
fills a single Jinja2 template laid out horizontally (A4 landscape) in the
``season_story`` editorial style. PDF export uses WeasyPrint, exactly as the
season report does.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Ensure the parent project (src.*) and this package are importable when run as
# a script from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from set_piece_report import pitch  # noqa: E402
from set_piece_report.data import load_match_context  # noqa: E402
from set_piece_report.impect_cafcdb_source import (  # noqa: E402
    load_match_context as load_match_context_cafcdb,
)
from set_piece_report.metrics import (  # noqa: E402
    StatRow,
    build_report_data,
    corner_deliveries,
    fk_deliveries,
    set_piece_shots,
    set_piece_shots_from_events,
    throw_in_deliveries,
)
from set_piece_report.theme import (  # noqa: E402
    contrast_text,
    get_theme,
    resolve_bar_colors,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "set_piece_report"


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def _pct_text(value: float | None) -> dict[str, Any]:
    if value is None:
        return {"text": "—", "color": "muted"}
    sign = "+" if value > 0 else ""
    colour = "up" if value > 0 else ("down" if value < 0 else "muted")
    # Cap the displayed magnitude so a single-match spike stays readable.
    shown = max(min(value, 999), -100)
    return {"text": f"{sign}{shown:.0f}%", "color": colour}


def _bar_widths(home: float, away: float) -> tuple[float, float]:
    """Proportional widths (%) for the split bar, with a visible floor."""
    total = home + away
    if total <= 0:
        return 50.0, 50.0
    hw = home / total * 100.0
    aw = away / total * 100.0
    # keep a sliver visible for non-zero-but-tiny values
    hw = 8.0 + hw * 0.84 if home else 4.0
    aw = 8.0 + aw * 0.84 if away else 4.0
    scale = 100.0 / (hw + aw)
    return hw * scale, aw * scale


def _badge_uri(team: str) -> str | None:
    try:
        from src.visualisation.badges import badge_data_uri

        return badge_data_uri(team)
    except Exception:
        return None


def _bar_row(r, show_comparisons: bool, goal_row=None) -> dict[str, Any]:
    """One bar row's template context, with an optional goal-count badge pulled
    from a sibling ``Goals From X`` row (never added to the bar's own value —
    that row is a separate SHOT/GOAL event in the feed, see metrics.py)."""
    blank_pct = {"text": "-", "color": "muted"}
    hw, aw = _bar_widths(r.home_value, r.away_value)
    home_goals = int(goal_row.home_value) if goal_row and goal_row.home_value else 0
    away_goals = int(goal_row.away_value) if goal_row and goal_row.away_value else 0
    return {
        "label": r.label,
        "home_value": r.fmt(r.home_value),
        "away_value": r.fmt(r.away_value),
        "home_goals": home_goals,
        "away_goals": away_goals,
        "home_per90": f"{r.home_per90:.2f}" if show_comparisons else "-",
        "away_per90": f"{r.away_per90:.2f}" if show_comparisons else "-",
        "home_pct": _pct_text(r.home_pct) if show_comparisons else blank_pct,
        "away_pct": _pct_text(r.away_pct) if show_comparisons else blank_pct,
        "home_width": round(hw, 2),
        "away_width": round(aw, 2),
    }


def _stat_groups_context(report_data, show_comparisons: bool = True) -> list[dict[str, Any]]:
    """Group the flat ``stat_rows`` list (one row per metric) into one block per
    set-piece family (Corners / Throw-ins / Indirect FKs / Direct FKs).

    Each family's "Total X" / "X Taken" count moves into the block's header.
    Every family shows its outcome bars in Goals → xG → Shots order (where a
    shots row exists); the delivery/taken total remains in the section header.
    """
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for r in report_data.stat_rows:
        if r.section:
            current = {"section": r.section, "count_row": None, "shot_row": None,
                       "goal_row": None, "xg_row": None}
            groups.append(current)
        label = r.label
        if label.startswith("Total ") or label.endswith("Taken"):
            current["count_row"] = r
        elif label.startswith("Goals"):
            current["goal_row"] = r
        elif label.startswith("xG"):
            current["xg_row"] = r
        elif label.startswith("Shots"):
            current["shot_row"] = r

    context_groups = []
    for g in groups:
        rows = []
        explicit_goals = g["section"] in {
            "CORNERS", "DIRECT FREE-KICKS", "INDIRECT FREE-KICKS", "THROW-INS"
        }
        if explicit_goals:
            if g["goal_row"]:
                rows.append(_bar_row(g["goal_row"], show_comparisons))
            if g["xg_row"]:
                rows.append(_bar_row(g["xg_row"], show_comparisons))
            if g["shot_row"]:
                rows.append(_bar_row(g["shot_row"], show_comparisons))
        elif g["shot_row"]:
            if g["xg_row"]:
                rows.append(_bar_row(g["xg_row"], show_comparisons))
            rows.append(_bar_row(g["shot_row"], show_comparisons, goal_row=g["goal_row"]))
        elif g["xg_row"]:
            rows.append(_bar_row(g["xg_row"], show_comparisons, goal_row=g["goal_row"]))
        context_groups.append(
            {
                "section": g["section"],
                "home_count": g["count_row"].fmt(g["count_row"].home_value) if g["count_row"] else "",
                "away_count": g["count_row"].fmt(g["count_row"].away_value) if g["count_row"] else "",
                "rows": rows,
            }
        )
    return context_groups


def _stat_groups_with_overall(report_data, ctx) -> list[dict[str, Any]]:
    """The five stat-groups in display order: Overall (leads the column),
    Corners, Direct Free-Kicks, Indirect Free-Kicks, Throw-Ins."""
    show_comparisons = ctx.show_comparisons
    groups = _stat_groups_context(report_data, show_comparisons=show_comparisons)
    # Keep recycled corner outcomes visible rather than hiding them inside the
    # headline corner shot/goal totals. The source loader marks contiguous
    # continuation phases with setPieceSubPhaseIndex >= 1.
    for section, categories, family in (
        ("CORNERS", ("CORNER_LEFT", "CORNER_RIGHT"), "corners"),
        ("INDIRECT FREE-KICKS", ("FREE_KICK",), "indirect free-kicks"),
    ):
        group = next((g for g in groups if g["section"] == section), None)
        if group is None:
            continue
        for action in ("GOAL", "SHOT"):
            group["rows"].append(_bar_row(
                _second_phase_stat_row(ctx, action, categories, family), show_comparisons
            ))
    groups.insert(0, _overall_group_context(report_data, ctx, show_comparisons))
    return groups


def _second_phase_stat_row(ctx, action: str, categories: tuple[str, ...], family: str) -> StatRow:
    def count(events, team):
        raw_phase = events["setPieceSubPhaseIndex"] if "setPieceSubPhaseIndex" in events else pd.Series(0, index=events.index)
        phase = pd.to_numeric(raw_phase, errors="coerce").fillna(0)
        mask = (events.get("actionType") == action) & events["setPieceCategory"].isin(categories) & (phase >= 1)
        return int(((events["attackingSquadName"] == team) & mask).sum())

    hm = count(ctx.match_events, ctx.home_team)
    am = count(ctx.match_events, ctx.away_team)
    hs = count(ctx.home_season_events, ctx.home_team)
    ass = count(ctx.away_season_events, ctx.away_team)
    hmatches = max(int(ctx.home_season_events["matchId"].nunique()), 1)
    amatches = max(int(ctx.away_season_events["matchId"].nunique()), 1)
    return StatRow(
        label=f"2nd-phase {'shots' if action == 'SHOT' else 'goals'} from {family}",
        home_value=hm, away_value=am,
        home_per90=hs / hmatches, away_per90=ass / amatches,
    )


def _overall_group_context(report_data, ctx, show_comparisons: bool) -> dict[str, Any]:
    """The 'Overall' stat-group: match-total set-piece goals / xG / shots, with
    a season per-90 baseline built the same non-double-counting way throughout
    this module — goals and shots come from ``set_piece_shots_from_events`` on
    both the match and season event frames, not summed from the per-family
    rows (which double-count goals, since the feed emits a goal as both a
    SHOT row and a separate GOAL row)."""
    home_shots_m = set_piece_shots(ctx, ctx.home_team)
    away_shots_m = set_piece_shots(ctx, ctx.away_team)
    home_shots_s = set_piece_shots_from_events(ctx.home_season_events, ctx.home_team)
    away_shots_s = set_piece_shots_from_events(ctx.away_season_events, ctx.away_team)
    home_matches = max(int(ctx.home_season_events["matchId"].nunique()), 1)
    away_matches = max(int(ctx.away_season_events["matchId"].nunique()), 1)

    xg_rows = [r for r in report_data.stat_rows if r.label.startswith("xG")]
    xg_home_m = sum(r.home_value for r in xg_rows)
    xg_away_m = sum(r.away_value for r in xg_rows)
    xg_home_s = sum(r.home_per90 for r in xg_rows)
    xg_away_s = sum(r.away_per90 for r in xg_rows)

    home_goals_s = home_shots_s["is_goal"].sum() if not home_shots_s.empty else 0
    away_goals_s = away_shots_s["is_goal"].sum() if not away_shots_s.empty else 0

    goals_row = StatRow(
        label="Set-Piece Goals",
        home_value=int(home_shots_m["is_goal"].sum()) if not home_shots_m.empty else 0,
        away_value=int(away_shots_m["is_goal"].sum()) if not away_shots_m.empty else 0,
        home_per90=home_goals_s / home_matches,
        away_per90=away_goals_s / away_matches,
    )
    xg_row = StatRow(
        label="Set-Piece xG", home_value=xg_home_m, away_value=xg_away_m,
        home_per90=xg_home_s, away_per90=xg_away_s, decimals=2,
    )
    shots_row = StatRow(
        label="Set-Piece Shots",
        home_value=len(home_shots_m), away_value=len(away_shots_m),
        home_per90=len(home_shots_s) / home_matches, away_per90=len(away_shots_s) / away_matches,
    )
    return {
        "section": "Overall",
        "home_count": "",
        "away_count": "",
        "rows": [
            _bar_row(goals_row, show_comparisons),
            _bar_row(xg_row, show_comparisons),
            _bar_row(shots_row, show_comparisons),
        ],
    }


def _side_contact_context(report_data, home_team: str, away_team: str) -> dict[str, Any]:
    """Per-side compact first-contact rows (corners/free-kicks × att/def)."""
    fc = report_data.first_contact

    def cell(cr) -> dict[str, Any]:
        return {
            "n": cr.deliveries, "won": cr.won, "lost": cr.lost,
            "win_rate": f"{cr.win_rate:.0f}%" if cr.win_rate is not None else "—",
        }

    def rows(team: str) -> list[dict[str, Any]]:
        t = fc[team]
        return [
            {"label": "Corners · att", "c": cell(t.attacking_corners)},
            {"label": "Corners · def", "c": cell(t.defending_corners)},
            {"label": "Free-kicks · att", "c": cell(t.attacking_fks)},
            {"label": "Free-kicks · def", "c": cell(t.defending_fks)},
        ]

    return {"home": {"team": home_team, "rows": rows(home_team)},
            "away": {"team": away_team, "rows": rows(away_team)}}


def _player_table_context(report_data, home_team: str, away_team: str, top: int = 12) -> dict[str, Any]:
    """Per-team first-contact winners (players), for the ``players`` variant."""

    def rows(team: str) -> list[dict[str, Any]]:
        players = report_data.player_contacts.get(team, {})
        ranked = sorted(players.values(), key=lambda p: (-p.total, -p.goals, -p.shots, p.player))
        return [
            {
                "player": p.player,
                "corner_att": p.corner_att or "·",
                "corner_def": p.corner_def or "·",
                "fk_att": p.fk_att or "·",
                "fk_def": p.fk_def or "·",
                "total": p.total,
                "shot_goal": f"{p.shots} / {p.goals}" if p.shots else "·",
            }
            for p in ranked[:top]
        ]

    return {"home": {"team": home_team, "rows": rows(home_team)},
            "away": {"team": away_team, "rows": rows(away_team)}}


def _legends_context(thm) -> dict[str, Any]:
    """Per-map legends drawn under each pitch (corner / free-kick / throw-in)."""
    return {
        "corner_types": pitch.corner_legend_items(thm),
        "fk_types": pitch.fk_legend_items(thm),
        "throw_types": pitch.throw_legend_items(thm),
        # First contact = the marker's outline colour (lost / uncontested before won).
        "contact": [
            ("lost", thm.edge_lost),
            ("uncontested", thm.edge_none),
            ("won", thm.edge_won),
        ],
        "throw_outcome": [("retained", thm.edge_won), ("lost", thm.edge_lost)],
        "goal": thm.goal,
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def build_report(
    match_id: int,
    *,
    output_dir: Path | str = DEFAULT_OUTPUT_DIR,
    formats: tuple[str, ...] = ("html", "pdf"),
    refresh: bool = False,
    corner_style: str = "hybrid",
    theme: str = "light",
    tables_style: str = "team",
    source: str = "staging",
) -> dict[str, Path]:
    """Build the set-piece report for ``match_id`` and return output paths.

    ``corner_style`` selects the attacking-corner graphic: ``"hybrid"`` (delivery
    arrows over a danger-zone heatmap) or ``"zones"`` (a 6-cell target-zone grid).
    ``theme`` is ``"light"`` (cream editorial) or ``"dark"``.
    ``tables_style`` is ``"team"`` (aggregate first-contact tables) or ``"players"``
    (per-team first-contact winners by player).
    ``source`` is ``"staging"`` (default: ``IMPECT_EVENTS_STAGING``, Championship
    25/26 only) or ``"cafcdb"`` (``CAFC_DB.IMPECT_RAW``, for fixtures not yet
    loaded into staging -- see ``impect_cafcdb_source.py`` for the set-piece
    field derivation this path relies on).
    """
    thm = get_theme(theme)
    ctx = (load_match_context_cafcdb(match_id) if source == "cafcdb"
           else load_match_context(match_id, refresh=refresh))
    report_data = build_report_data(ctx)

    zonal = corner_style == "zones"
    players = tables_style == "players"
    corner_fn = pitch.corner_zone_overview if zonal else pitch.corner_overview

    panels = {}
    for side, team in (("home", ctx.home_team), ("away", ctx.away_team)):
        panels[side] = {
            "team": team,
            "badge": _badge_uri(team),
            "corner_img": corner_fn(corner_deliveries(ctx, team), thm),
            "fk_img": pitch.free_kick_overview(fk_deliveries(ctx, team), thm),
            "throw_img": pitch.throw_in_overview(throw_in_deliveries(ctx, team), thm),
            "corner_type_counts": report_data.corner_type_counts.get(team, {}),
        }

    home_bar, away_bar = resolve_bar_colors(ctx.home_team, ctx.away_team, thm)
    md = None
    if ctx.matchday:
        md = f"Matchday {ctx.matchday} / {ctx.matchday_total}" if ctx.matchday_total else f"Matchday {ctx.matchday}"

    context = {
        "meta": {
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_goals": ctx.home_goals,
            "away_goals": ctx.away_goals,
            "score": ctx.score_line,
            "competition": ctx.competition,
            "season": ctx.season,
            "matchday": md,
            "date": ctx.date.strftime("%d %B %Y"),
            "home_badge": _badge_uri(ctx.home_team),
            "away_badge": _badge_uri(ctx.away_team),
        },
        "theme": thm.as_css_vars(),
        "theme_name": thm.name,
        "home_bar": home_bar,
        "away_bar": away_bar,
        "home_text": contrast_text(home_bar),
        "away_text": contrast_text(away_bar),
        "panels": panels,
        "stat_groups": _stat_groups_with_overall(report_data, ctx),
        "stats_compact": not ctx.show_comparisons,
        "legends": _legends_context(thm),
        "players_mode": players,
        "side_tables": _side_contact_context(report_data, ctx.home_team, ctx.away_team),
        "player_tables": _player_table_context(report_data, ctx.home_team, ctx.away_team),
        "colors": {"up": thm.green, "down": thm.red},
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("set_piece_report.html.j2").render(**context)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = (
        ("_corner_zones" if zonal else "")
        + ("_players" if players else "")
        + ("_dark" if thm.name == "dark" else "")
    )
    slug = (
        f"{ctx.home_team}_{ctx.away_team}_{ctx.date.strftime('%Y_%m_%d')}_set_piece_report{suffix}"
    ).replace(" ", "_")

    outputs: dict[str, Path] = {}
    if "html" in formats:
        html_path = output_dir / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")
        outputs["html"] = html_path
    if "pdf" in formats:
        from weasyprint import HTML

        pdf_path = output_dir / f"{slug}.pdf"
        HTML(string=html, base_url=str(PROJECT_ROOT)).write_pdf(str(pdf_path))
        outputs["pdf"] = pdf_path
    return outputs

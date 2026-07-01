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

# Ensure the parent project (src.*) and this package are importable when run as
# a script from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jinja2 import Environment, FileSystemLoader, select_autoescape  # noqa: E402

from set_piece_report import pitch  # noqa: E402
from set_piece_report.config import AWAY_BAR, GREEN, HOME_BAR, RED  # noqa: E402
from set_piece_report.data import load_match_context  # noqa: E402
from set_piece_report.metrics import (  # noqa: E402
    build_report_data,
    corner_deliveries,
    fk_deliveries,
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


def _stat_rows_context(report_data) -> list[dict[str, Any]]:
    rows = []
    for r in report_data.stat_rows:
        hw, aw = _bar_widths(r.home_value, r.away_value)
        rows.append(
            {
                "label": r.label,
                "section": r.section,
                "home_value": r.fmt(r.home_value),
                "away_value": r.fmt(r.away_value),
                "home_per90": f"{r.home_per90:.2f}",
                "away_per90": f"{r.away_per90:.2f}",
                "home_pct": _pct_text(r.home_pct),
                "away_pct": _pct_text(r.away_pct),
                "home_width": round(hw, 2),
                "away_width": round(aw, 2),
            }
        )
    return rows


def _contact_table_context(report_data, home_team: str, away_team: str) -> dict[str, Any]:
    """Shape the first-contact tables: corners block and free-kicks block."""

    def cell(cr) -> dict[str, Any]:
        return {
            "n": cr.deliveries,
            "won": cr.won,
            "lost": cr.lost,
            "uncontested": cr.uncontested,
            "win_rate": f"{cr.win_rate:.0f}%" if cr.win_rate is not None else "—",
        }

    fc = report_data.first_contact
    return {
        "corners": [
            {
                "team": team,
                "attacking": cell(fc[team].attacking_corners),
                "defending": cell(fc[team].defending_corners),
            }
            for team in (home_team, away_team)
        ],
        "free_kicks": [
            {
                "team": team,
                "attacking": cell(fc[team].attacking_fks),
                "defending": cell(fc[team].defending_fks),
            }
            for team in (home_team, away_team)
        ],
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
) -> dict[str, Path]:
    """Build the set-piece report for ``match_id`` and return output paths."""
    ctx = load_match_context(match_id, refresh=refresh)
    report_data = build_report_data(ctx)

    panels = {}
    for side, team in (("home", ctx.home_team), ("away", ctx.away_team)):
        panels[side] = {
            "team": team,
            "badge": _badge_uri(team),
            "corner_img": pitch.corner_overview(corner_deliveries(ctx, team)),
            "fk_img": pitch.free_kick_overview(fk_deliveries(ctx, team)),
            "corner_type_counts": report_data.corner_type_counts.get(team, {}),
        }

    context = {
        "meta": {
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_goals": ctx.home_goals,
            "away_goals": ctx.away_goals,
            "score": ctx.score_line,
            "competition": ctx.competition,
            "season": ctx.season,
            "date": ctx.date.strftime("%d %B %Y"),
            "home_badge": _badge_uri(ctx.home_team),
            "away_badge": _badge_uri(ctx.away_team),
        },
        "home_bar": HOME_BAR,
        "away_bar": AWAY_BAR,
        "panels": panels,
        "stat_rows": _stat_rows_context(report_data),
        "corner_legend": pitch.corner_legend_items(),
        "fk_legend": pitch.fk_legend_items(),
        "contact": _contact_table_context(report_data, ctx.home_team, ctx.away_team),
        "colors": {"up": GREEN, "down": RED},
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
    slug = (
        f"{ctx.home_team}_{ctx.away_team}_{ctx.date.strftime('%Y_%m_%d')}_set_piece_report"
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

"""Build the DVMS (Opta + tracking) set-piece report.

Same page grammar as the IMPECT report (three-column: team maps — centre
stat bars — team maps), rendered by the same ``pitch.py`` functions, plus a
second page the IMPECT version could never draw: tracked freeze-frames of
each side's most dangerous corner, with the defending line-drop measured in
metres.

No "/90 · % chg" columns: those compare against a full-season IMPECT
baseline that doesn't exist in the DVMS window. Match values only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from set_piece_report import data_dvms, pitch, pitch_dvms
from set_piece_report.render import _badge_uri, _bar_widths, _legends_context
from set_piece_report.theme import contrast_text, get_theme, resolve_bar_colors
from src.dvms.loaders.fixtures import resolve_fixture

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "set_piece_report"


def _stat_rows_context(ctx) -> list[dict[str, Any]]:
    rows = []
    for section in data_dvms.stat_sections(ctx):
        first = True
        for r in section["rows"]:
            h = section["data"][ctx.home_team][r["key"]]
            a = section["data"][ctx.away_team][r["key"]]
            hw, aw = _bar_widths(float(h), float(a))
            fmt = (lambda v: f"{v:.2f}") if r["key"] == "xg" else (lambda v: f"{int(v)}")
            rows.append({
                "section": section["section"] if first else None,
                "label": r["label"],
                "home_value": fmt(h), "away_value": fmt(a),
                "home_width": round(hw, 2), "away_width": round(aw, 2),
            })
            first = False
    return rows


def build_report(opta_match_id: str, *, output_dir: Path | str = DEFAULT_OUTPUT_DIR,
                 formats: tuple[str, ...] = ("html", "pdf"), theme: str = "light",
                 env_path: str = ".env") -> dict[str, Path]:
    thm = get_theme(theme)
    fixture = resolve_fixture(opta_match_id, env_path=env_path)
    ctx = data_dvms.load_context(fixture, env_path=env_path)

    home_bar, away_bar = resolve_bar_colors(ctx.home_team, ctx.away_team, thm)
    bar_of = {ctx.home_team: home_bar, ctx.away_team: away_bar}

    panels = {}
    freeze = {}
    for side, team in (("home", ctx.home_team), ("away", ctx.away_team)):
        panels[side] = {
            "team": team,
            "corner_img": pitch.corner_overview(data_dvms.corner_deliveries(ctx, team), thm),
            "fk_img": pitch.free_kick_overview(data_dvms.fk_deliveries(ctx, team), thm),
            "throw_img": pitch.throw_in_overview(data_dvms.throw_in_deliveries(ctx, team), thm),
            "contact_rows": data_dvms.first_contact_rows(ctx, team),
        }
        frame, delivery, drop = data_dvms.freeze_frame_data(ctx, team)
        if frame is not None:
            att_side = "home" if team == ctx.home_team else "away"
            freeze[side] = {
                "team": team,
                "img": pitch_dvms.corner_freeze_frame(
                    frame, ctx.meta, att_side, bar_of[team], theme=thm),
                "minute": int(delivery["minute"]),
                "taker": ctx.last_name(delivery["player_id"]),
                "side_taken": delivery["side"],
                "goal": bool(delivery["led_to_goal"]),
                "line_drop": f"{drop:+.1f}m" if drop is not None else "—",
            }

    context = {
        "meta": {
            "home_team": ctx.home_team,
            "away_team": ctx.away_team,
            "home_goals": ctx.f7.home.score,
            "away_goals": ctx.f7.away.score,
            "competition": "Championship",
            "date": fixture.match_date.strftime("%d %B %Y"),
            "home_badge": _badge_uri(ctx.home_team),
            "away_badge": _badge_uri(ctx.away_team),
        },
        "theme": thm.as_css_vars(),
        "home_bar": home_bar,
        "away_bar": away_bar,
        "home_text": contrast_text(home_bar),
        "away_text": contrast_text(away_bar),
        "panels": panels,
        "freeze": freeze,
        "stat_rows": _stat_rows_context(ctx),
        "legends": _legends_context(thm),
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("set_piece_report_dvms.html.j2").render(**context)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = (f"set_piece_report_dvms_{ctx.home_team}_v_{ctx.away_team}"
            f"_{fixture.match_date.strftime('%Y_%m_%d')}").replace(" ", "_")

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

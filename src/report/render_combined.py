"""Assemble the combined Impect + DVMS single-page board report (HTML + PDF).

Sources each panel from whichever provider is authoritative for that metric
(see docs/superpowers/specs/2026-07-29-combined-board-post-match-report-design.md).
Template, CSS and panel layout are copied byte-for-byte from
board-post-match-report's post_match_report_v2.html.j2 — only the data
feeding each panel differs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.db.query_runner import QueryRunner
from src.dvms.loaders.fixtures import resolve_fixture
from src.report import chart, chart_dvms, metrics, metrics_combined, metrics_dvms, palette, pitch
from src.report.metrics import STAT_GLOSS, STAT_ROWS
from src.visualisation.badges import badge_data_uri

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"


class FixtureMismatchError(ValueError):
    """Raised when the given Impect match and DVMS fixture don't look like
    the same real-world game — team names or kickoff date disagree."""


def _normalize(name: str) -> str:
    return name.strip().lower()


def _assert_same_fixture(impect_meta, dvms_fixture) -> None:
    impect_teams = {_normalize(impect_meta.home_team), _normalize(impect_meta.away_team)}
    dvms_teams = {_normalize(dvms_fixture.home_team), _normalize(dvms_fixture.away_team)}
    if impect_teams != dvms_teams:
        raise FixtureMismatchError(
            f"Impect match {impect_meta.home_team} v {impect_meta.away_team} does not match "
            f"DVMS fixture {dvms_fixture.home_team} v {dvms_fixture.away_team}."
        )
    impect_date = impect_meta.kickoff.date()
    dvms_date = dvms_fixture.match_date.date()
    if impect_date != dvms_date:
        raise FixtureMismatchError(
            f"Impect match date {impect_date} does not match DVMS fixture date {dvms_date} "
            f"({impect_meta.home_team} v {impect_meta.away_team})."
        )


def _fmt_stat(key: str, value: float) -> str:
    if key.endswith("_pct"):
        return f"{value:.0f}%"
    if "xg" in key:
        return f"{value:.2f}"
    return f"{int(round(value))}"


def _stat_rows(stats: Any, home: str, away: str, charlton: str) -> list[dict[str, Any]]:
    rows = []
    last_group = None
    for group, key, label in STAT_ROWS:
        h = float(stats.loc[home, key])
        a = float(stats.loc[away, key])
        total = h + a
        h_share = (h / total * 100) if total else 50.0
        rows.append({
            "group": group if group != last_group else None,
            "label": label,
            "home": _fmt_stat(key, h),
            "away": _fmt_stat(key, a),
            "home_share": round(h_share, 1),
            "away_share": round(100 - h_share, 1),
            "home_wins": h > a,
            "away_wins": a > h,
            "home_is_charlton": home == charlton,
            "gloss": STAT_GLOSS.get(key),
        })
        last_group = group
    return rows


def _contribution_rows(df: Any, charlton: str) -> list[dict[str, Any]]:
    return [
        {
            "name": r["surname"],
            "is_charlton": r["squadName"] == charlton,
            "passes": int(r["passes"]),
            "ground": int(r["ground"]),
            "aerial": int(r["aerial"]),
            "ball_wins": int(r["ball_wins"]),
            "shots": int(r["shots"]),
            "xg": f"{r['xg']:.2f}",
            "xt": f"{r['xt']:.2f}",
        }
        for _, r in df.iterrows()
    ]


def build_context(impect_match_id: int, dvms_opta_match_id: str, refresh: bool = False) -> dict[str, Any]:
    runner = QueryRunner()
    events = runner.load_match_events(impect_match_id, refresh=refresh)
    impect_meta = metrics.match_meta(events)

    dvms_fixture = resolve_fixture(dvms_opta_match_id)
    _assert_same_fixture(impect_meta, dvms_fixture)
    dvms_match = metrics_dvms.load_match(dvms_fixture)

    charlton, opponent = impect_meta.charlton_team, impect_meta.opponent_team

    # NOTE on cross-vendor naming: dvms_match.team_name_of(side) returns an
    # Opta/F24-derived team name string, while impect_meta.home_team/away_team
    # are Impect-derived strings. _assert_same_fixture only guarantees the two
    # *sets* of names match case-insensitively for this fixture — it does not
    # guarantee the exact strings are byte-identical (e.g. differing casing or
    # abbreviations would pass that check but fail an exact dict-key lookup).
    # A prior task hit exactly this bug: keying a DataFrame/dict by the DVMS
    # name and then looking it up with the Impect name silently produced
    # phantom/missing entries instead of a loud error.
    #
    # Both providers agree on which physical side ("home"/"away") each team
    # played on — that's a fact of the match, not a spelling — so we build the
    # DVMS-side <-> Impect-team-name mapping via home/away, and use that
    # mapping everywhere instead of ever comparing or keying by the two
    # providers' name strings directly.
    side_to_team = {"home": impect_meta.home_team, "away": impect_meta.away_team}
    team_to_side = {impect_meta.home_team: "home", impect_meta.away_team: "away"}

    stats = metrics_combined.combined_team_stats(events, dvms_match)
    goals = metrics.goal_events(events)
    shots = metrics.shot_events(events)
    entries = {team: metrics.zone_entries(events, team) for team in (charlton, opponent)}
    entries_style_split = {
        side_to_team[side]: metrics_combined.line_break_style_split(dvms_match, side)
        for side in ("home", "away")
    }
    wave = metrics_dvms.territory_wave(dvms_match)
    dvms_goal_markers = metrics_dvms.goal_markers(dvms_match)
    # goal_markers() labels each goal's "team" field using the DVMS/Opta name
    # (f24.home_team_name/away_team_name) — chart_dvms.territory_chart then
    # compares that field against the charlton/opponent strings we pass it,
    # which are Impect-derived. Remap DVMS name -> Impect name via home/away
    # side (both names come from the same DvmsMatch object, so this lookup is
    # internally consistent) rather than trusting the two providers' strings
    # to match exactly — see the cross-vendor naming note above.
    dvms_name_to_side = {dvms_match.team_name_of(s): s for s in ("home", "away")}
    for marker in dvms_goal_markers:
        marker["team"] = side_to_team[dvms_name_to_side[marker["team"]]]
    season = metrics.season_context(runner.load_season_results(refresh=refresh), charlton, impect_meta.kickoff)
    contributions = metrics_combined.blended_player_contributions(events, dvms_match, top_n=10)
    chances = metrics.chance_sources(events, impect_meta.home_team, impect_meta.away_team)

    avg_pos_in_possession = {
        team: metrics_dvms.avg_position_frame(dvms_match, team_to_side[team], "in_possession")
        for team in (charlton, opponent)
    }
    line_height_in_possession = {
        team: metrics_dvms.line_height_m(dvms_match, team_to_side[team], "in_possession")
        for team in (charlton, opponent)
    }

    max_threat = max((float(e["threat"].max()) if not e.empty else 0.0) for e in entries.values())

    def side(team: str) -> dict[str, Any]:
        is_charlton = team == charlton
        color = palette.CHARLTON_RED if is_charlton else palette.OPPONENT_GREY
        return {
            "team": team,
            "is_charlton": is_charlton,
            "badge": badge_data_uri(team),
            "goals": impect_meta.charlton_goals if is_charlton else impect_meta.opponent_goals,
            "scorers": [{"player": g.player, "minute": g.minute_label} for g in goals if g.team == team],
            "shot_map": pitch.shot_map(shots.loc[shots["squadName"] == team], color),
            "shot_summary": metrics.shot_summary(shots, team),
            "entries": pitch.entry_map(entries[team], max_threat),
            "entries_style_split": entries_style_split[team],
            "avg_pos_map": pitch.average_position_map(
                avg_pos_in_possession[team], color, line_height_in_possession[team], vertical=True),
        }

    context: dict[str, Any] = {
        "generated_date": dt.date.today().strftime("%d %B %Y"),
        "sides": [side(impect_meta.home_team), side(impect_meta.away_team)],
        "meta": {
            "charlton_team": charlton,
            "opponent_team": opponent,
            "home_team": impect_meta.home_team,
            "away_team": impect_meta.away_team,
            "venue": "Away" if charlton == impect_meta.away_team else "Home",
            "competition": impect_meta.competition,
            "season": impect_meta.season,
            "date": impect_meta.kickoff.strftime("%d/%m/%Y"),
            "result": impect_meta.result,
        },
        "form": [
            {"result": r, "opponent": o, "is_last": i == len(season.form) - 1}
            for i, (r, o) in enumerate(zip(season.form, season.form_opponents))
        ],
        "stat_rows": _stat_rows(stats, impect_meta.home_team, impect_meta.away_team, charlton),
        "territory_img": chart_dvms.territory_chart(wave, dvms_goal_markers, charlton, opponent),
        "chance_source_img": chart.chance_source_bars(chances, charlton, opponent),
        "contributions": _contribution_rows(contributions, charlton),
        "match_id": impect_match_id,
    }
    return context


def render_report(impect_match_id: int, dvms_opta_match_id: str,
                   output_dir: Path | str = DEFAULT_OUTPUT_DIR,
                   formats: tuple[str, ...] = ("html", "pdf"), refresh: bool = False) -> dict[str, Path]:
    context = build_context(impect_match_id, dvms_opta_match_id, refresh=refresh)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("post_match_report_combined.html.j2").render(**context)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = (f"post_match_report_combined_{context['meta']['charlton_team']}"
            f"_v_{context['meta']['opponent_team']}"
            f"_{context['meta']['date'].replace('/', '-')}").replace(" ", "_")

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

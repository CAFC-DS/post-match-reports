import collections
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.report.expanded.pages import build_page_plan

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "report" / "expanded" / "templates"


def test_page_counts_match_the_recovered_report():
    assert build_page_plan(True)["total"] == 16
    assert build_page_plan(False)["total"] == 15


def test_pages_are_numbered_contiguously_with_section_labels():
    plan = build_page_plan(True)
    numbers = [plan["pages"][key]["n"] for key in plan["order"]]
    assert numbers == list(range(1, plan["total"] + 1))
    assert plan["pages"]["div_ip"]["label"] == "DIVIDER"
    assert plan["pages"]["ip_shots"]["label"] == "PAGE 6/6"
    assert plan["pages"]["oop_regains"]["label"] == "PAGE 3/3"
    assert plan["sections"]["in_possession"] == {"first": 4, "last": 10}


def test_untracked_layout_merges_the_shape_pages():
    plan = build_page_plan(False)
    assert "shapes" in plan["pages"] and "shapes_0" not in plan["pages"]
    assert plan["pages"]["ip_shots"]["label"] == "PAGE 5/5"


def _stub_context(tracked: bool) -> dict:
    teams = ["Charlton Athletic", "Cardiff City"]
    plan = build_page_plan(tracked)
    ctx = collections.defaultdict(lambda: "")
    ctx.update(
        tracked_shapes=tracked,
        page_plan=plan,
        subject=teams[0],
        opponent=teams[1],
        team_order=teams,
        sides=[
            {"team": t, "badge": "", "is_charlton": i == 0, "goals": i,
             "shot_map": "", "shot_summary": {"shots": 1, "on_target": 1, "xg": .5, "xg_per_shot": .5}}
            for i, t in enumerate(teams)
        ],
        meta={"date": "19/09/2026", "competition": "Championship", "home_team": teams[1], "away_team": teams[0]},
        network={t: "" for t in teams},
        network_scale_threat=0.5,
        side_by_team={t: {"avg_pos_in": "", "avg_pos_out": "", "avg_pos_in_lh": 0, "avg_pos_out_lh": 0, "entries": ""}
                      for t in teams},
        player_threat_ranking_totals={t: 0 for t in teams},
        big_chances={t: [] for t in teams},
        chance_source_kpis={k: "" for k in ("charlton_top_source", "charlton_total",
                                             "opponent_top_source", "opponent_total")},
        pressure_kpis={k: 0 for k in ("pressure_n", "forced_pct", "opp_third_n", "per_min", "top_name", "top_n")},
        duel_split_kpis={"aerial_pct": 0, "ground_pct": 0, "most_involved": ""},
        regain_kpis={k: 0 for k in ("n", "baseline_avg", "baseline_delta", "baseline_n", "shot_pct", "shot_n")},
        second_ball_kpis={k: 0 for k in ("won_n", "n", "baseline_avg", "baseline_delta", "baseline_n", "won_pct")},
        transition_kpis={k: 0 for k in ("high_losses_n", "counterpress_n", "shot_n", "shot_pct")},
        stat_rows_expanded=[],
        match_highlights=[],
    )
    return ctx


def test_template_footers_follow_the_registry():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    for tracked in (True, False):
        html = env.get_template("expanded.html.j2").render(**_stub_context(tracked))
        total = build_page_plan(tracked)["total"]
        footers = re.findall(r'<div class="foot">(\d+)/(\d+)</div>', html)
        assert [int(n) for n, _ in footers] == list(range(1, total + 1))
        assert {int(t) for _, t in footers} == {total}
        assert html.count('<section class="sheet') == total

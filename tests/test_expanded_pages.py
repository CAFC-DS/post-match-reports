import collections
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.report.expanded.pages import build_contents, build_page_plan, section_info

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "report" / "expanded" / "templates"


def test_page_counts():
    # The recovered report was 16 / 15 pages; the contents page, the team-sheet
    # page (needs DVMS lineups) and the receptions / threat pages add three.
    assert build_page_plan(True)["total"] == 24
    assert build_page_plan(False)["total"] == 23
    assert build_page_plan(True, has_team_sheet=False)["total"] == 24
    assert "ov_sheet" not in build_page_plan(True, has_team_sheet=False)["pages"]


def test_pages_are_numbered_contiguously_with_section_labels():
    plan = build_page_plan(True)
    numbers = [plan["pages"][key]["n"] for key in plan["order"]]
    assert numbers == list(range(1, plan["total"] + 1))
    assert plan["pages"]["contents"]["n"] == 1
    assert plan["pages"]["div_ip"]["label"] == "DIVIDER"
    assert plan["pages"]["ov_sheet"]["label"] == "PAGE 2/4"
    assert plan["pages"]["pl_defenders"]["label"] == "PAGE 1/3" and plan["pages"]["pl_attackers"]["label"] == "PAGE 3/3"
    assert plan["order"][-4:] == ["div_players", "pl_defenders", "pl_midfielders", "pl_attackers"]
    assert plan["pages"]["net"]["label"] == "PAGE 1/7"
    assert plan["pages"]["ip_receptions"]["label"] == "PAGE 4/7"
    assert plan["pages"]["ip_threat_zones"]["label"] == "PAGE 5/7"
    assert plan["pages"]["ip_shots"]["label"] == "PAGE 7/7"
    assert "ip_shot_placement" not in plan["pages"]
    assert "net_0" not in plan["pages"] and "ip_player_threat" not in plan["pages"]
    assert "oop_duel_maps" not in plan["pages"]
    assert plan["pages"]["oop_regains"]["label"] == "PAGE 3/3"
    assert "oop_second_balls" not in plan["pages"]
    assert plan["sections"]["in_possession"] == {"first": 7, "last": 14}


def test_untracked_layout_merges_the_shape_pages():
    plan = build_page_plan(False)
    assert "shapes" in plan["pages"] and "shapes_0" not in plan["pages"]
    assert plan["pages"]["ip_shots"]["label"] == "PAGE 6/6"


def _stub_context(tracked: bool, team_sheet: bool = True) -> dict:
    teams = ["Charlton Athletic", "Cardiff City"]
    plan = build_page_plan(tracked, team_sheet)
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
        side_by_team={t: {"avg_pos_in": "", "avg_pos_out": "", "avg_pos_in_lh": 0, "avg_pos_out_lh": 0, "entries": "",
                          "entries_style_split": {"through": 50.0, "over": 30.0, "around": 20.0, "n": 10,
                                                  "successful": 5, "total": 8, "completion_pct": 62.5, "threat": .4}}
                      for t in teams},
        player_threat_ranking_totals={t: 0 for t in teams},
        big_chances={t: [] for t in teams},
        chance_source_kpis={k: "" for k in ("charlton_top_source", "charlton_total",
                                             "opponent_top_source", "opponent_total")},
        pressing_kpis={t: {"n": 10, "forced": 3, "forced_pct": 30, "opp_half": 4, "opp_third": 2, "per_min": 0.1} for t in teams},
        pressure_heat_img={t: "" for t in teams},
        pressing_img={t: "" for t in teams},
        duel_totals={t: {k: {"won": 3, "total": 5, "pct": 60} for k in ("all", "AERIAL", "GROUND")} for t in teams},
        duel_map_img={t: {"AERIAL": "", "GROUND": ""} for t in teams},
        regain_img={t: "" for t in teams},
        regain_players_img={t: "" for t in teams},
        second_ball_img={t: "" for t in teams},
        regain_ctx={t: {"n": 5, "counts": [1, 2, 2], "pcts": [20, 40, 40], "shots": 1, "shot_pct": 20, "losses": [3, 2, 1],
                        "losses_n": 6} for t in teams},
        second_ball_kpis={t: {k: 0 for k in ("won_n", "n", "baseline_avg", "baseline_delta", "baseline_n", "won_pct")} for t in teams},
        transition_kpis={k: 0 for k in ("high_losses_n", "counterpress_n", "shot_n", "shot_pct")},
        stat_rows_expanded=[],
        baseline_matches=46,
        summary={"home": teams[1], "score": {teams[0]: 1, teams[1]: 3}, "half_time": {teams[0]: 1, teams[1]: 2},
                 "scorers": {teams[0]: [{"who": "Campbell", "minute": "28'"}], teams[1]: [{"who": "Moylan", "minute": "7'"}]},
                 "went": ["Charlton Athletic spent 7 minutes level and 89 minutes trailing and never led."],
                 "numbers": [{"label": "Possession", "subject": "41%", "opponent": "59%"}],
                 "season": {"above": ["Duels won: 61% against an average of 50% (80th percentile of 46 matches)"],
                            "below": ["Shots: 6 against an average of 12 (10th percentile of 46 matches)"]},
                 "standouts": [{"name": "Campbell", "position": "wingers", "minutes": 96, "ups": 8, "rated": 13,
                                "best": ["Goals 1", "Expected goals (xG) 0.28"]}]},
        section_info=section_info(teams[0], tracked, team_sheet),
        progression_img={t: "" for t in teams},
        progression_kpis={t: {"total": 10, "actions": 5, "defenders": 3} for t in teams},
        threat_density_img={t: "" for t in teams},
        threat_density_kpis={t: {"pxt": "1.00", "actions": 7} for t in teams},
        threat_zone_img={t: "" for t in teams},
        threat_zone_kpis={t: {"total": "1.00", "actions": 5} for t in teams},
        reception_ctx={t: {"img": "", "total": 3, "bypassed": 2,
                           "categories": [{"label": "Out wide", "n": 3}],
                           "players": [{"name": "One", "receptions": 3, "bypassed": 2, "by_category": {"Out wide": 3}}]} for t in teams},
        player_threat_ctx={t: {"img": "", "created": "0.54", "passing": "0.39", "carrying": "0.15",
                               "receiving": "0.44"} for t in teams},
        entry_givers_ctx={t: {"img": "", "n_final_third": 1, "n_box": 1} for t in teams},
        placement_img={t: "" for t in teams},
        placement_ctx={t: {"placed": 4, "on_target": 2, "goals": 1, "woodwork": 0, "xgot": "0.80"} for t in teams},
        gamestate={"states": [{"key": "leading", "label": "Leading", "minutes": 30.0, "small": False, "xg_for": .4,
                               "xg_against": .1, "shots_for": 3, "shots_against": 1, "possession": 55,
                               "pressures_per_min": 2.1, "regains": 4}],
                   "other": [{"label": "First half", "minutes": 45.0, "small": True, "xg_for": .4, "xg_against": .1,
                              "shots_for": 3, "shots_against": 1, "possession": None, "pressures_per_min": 2.0,
                              "regains": 3}], "end": 96.0, "first_goal": (20.0, "Charlton Athletic", "C Campbell")},
        gamestate_band_img="",
        gamestate_scales={"xg": .5, "pressures": 40, "shots": 5},
        gamestate_data={"periods": [{"label": "0–15'", "state": "leading", "state_label": "Leading by 1", "goals": ["Campbell 7'"],
                                     "xg": (.4, .1), "pressures": (30, 20), "possession": (45, 55), "shots": (3, 1)}]},
        flow_timeline_img="",
        timeline_img="",
        line_breaks_available=True,
        contents=build_contents(plan, teams[0], tracked, team_sheet),
    )
    ctx.update(
        player_pages=[{"key": g, "label": g_label,
                       "columns": [{"role": "Midfielders", "name": "Moylan", "shirt": 8, "minutes": 82, "rated": True},
                                   {"role": "Midfielders", "name": "Grant", "shirt": 9, "minutes": 10,
                                    "rated": False}] if g == "midfielders" else [],
                       "physical": [],
                       "rows": [{"key": "passes", "label": "Passes completed", "desc": "Successful passes",
                                 "cells": [{"text": "31", "own": "28.4", "league": "35.0", "v_own": "up", "v_league": "down",
                                            "v_both": "mixed"},
                                           {"text": "4", "own": "–", "league": "35.0", "v_own": "", "v_league": "",
                                            "v_both": ""}]}]}
                      for g, g_label in (("defenders", "Goalkeepers & Defenders"), ("midfielders", "Midfielders"),
                                         ("attackers", "Wingers & Forwards"))],
        player_baseline_matches=6,
    )
    if team_sheet:
        row = {"shirt": 1, "name": "A Player", "role": "GK", "minutes": 96, "marks": [{"kind": "goal", "text": "7'"}]}
        ctx.update(
            team_sheets=[{"name": t, "is_charlton": i == 0, "formation": "4-2-3-1", "lineup_img": "",
                          "starters": [row], "subs": [row], "unused": 2, "unused_names": ["Keeper", "Spare"],
                          "score": 1 - i, "ht": 1, "goals": [{"who": "Scorer", "min": "28'", "assist": "Setter"}]}
                         for i, t in enumerate(teams)],
        )
    return ctx


def test_template_footers_follow_the_registry():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    for tracked, team_sheet in ((True, True), (False, True), (True, False)):
        html = env.get_template("expanded.html.j2").render(**_stub_context(tracked, team_sheet))
        total = build_page_plan(tracked, team_sheet)["total"]
        footers = re.findall(r'<div class="foot">(\d+)/(\d+)</div>', html)
        assert [int(n) for n, _ in footers] == list(range(1, total + 1))
        assert {int(t) for _, t in footers} == {total}
        assert html.count('<section class="sheet') == total


def test_contents_page_lists_every_section_with_its_page_span():
    plan = build_page_plan(True)
    rows = build_contents(plan, "Charlton Athletic", True, True)
    assert [r["title"] for r in rows] == ["Overview", "In Possession", "Out of Possession", "Transition", "Player Performances"]
    assert rows[0]["pages"] == "pages 2\u20136"
    assert "Where players received the ball" in rows[1]["items"]
    assert "Team sheet, lineups & timeline" in rows[0]["items"]
    assert "Team-by-team tracked phase shapes" in rows[1]["items"]
    assert "Combined event-data average locations" in build_contents(
        build_page_plan(False), "Charlton Athletic", False, True)[1]["items"]


def test_template_renders_contents_and_team_sheet():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    assert "what's in this report and where to find it" in html
    assert "Team Sheet, Lineups & Timeline" in html
    assert "Substitutes used" in html
    without = env.get_template("expanded.html.j2").render(**_stub_context(True, team_sheet=False))
    assert "Team Sheet, Lineups" not in without


def test_template_renders_the_in_possession_panels():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    for text in ("Passing Networks & Progression", "PROGRESSION", "3 defenders", "Where Players Received The Ball",
                 "Who received it", "Threat Creation & Player Threat", "Threat density", "Threat by role zone",
                 "Player threat", "Final Third & Box Entries", "WHO GOT THE BALL THERE",
                 "Match Flow & Territory", "Shot Placement &amp; Biggest Chances"):
        assert text in html, text
    assert "<b>50%</b> through" in html and "<b>30%</b> over" in html and "<b>20%</b> around" in html
    assert html.count("Match Timeline") == 1          # one timeline panel: on the team-sheet page
    assert "Opponents bypassed</th>" in html and "Match Flow &amp; Territory" in html or "Match Flow & Territory" in html
    assert html.count("Player Threat") == 1          # one page, no separate player-threat page


def test_team_sheet_page_has_scorers_in_each_card():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    assert "half-time 1 – 1" in html
    assert "<b>28'</b> Scorer" in html and "assist Setter" in html
    assert "Unused substitutes: Keeper, Spare" in html


def test_entries_fall_back_to_completion_when_there_is_no_line_break_data():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    ctx = _stub_context(True)
    ctx["line_breaks_available"] = False
    html = env.get_template("expanded.html.j2").render(**ctx)
    assert "through" not in html.split("Final Third & Box Entries")[1].split("WHO GOT THE BALL THERE")[0].replace(
        "route · outcome · destination", "")
    assert "<b>5/8</b> completed (62%)" in html or "<b>5/8</b> completed (63%)" in html


def test_player_performance_pages_are_one_per_position_with_players_as_columns():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    assert html.count("Player Performance ·") == 3
    assert "Player Performance · Midfielders" in html and "6 earlier matches" in html
    assert 'class="val tstart v-mixed"' in html and 'class="avg a-up"' in html and 'class="avg a-down"' in html
    assert ">Today<" in html and ">Season /90<" in html and ">League /90<" in html
    assert "<b>Passes completed</b><small>Successful passes</small>" in html
    assert "No goalkeepers & defenders played for Charlton Athletic" in html          # empty groups keep their page
    assert "Cardiff" not in html.split("Player Performance · Midfielders")[1].split("</section>")[0]


def test_game_state_page_renders_the_slice_table():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    assert "Game State & Phases" in html and "gsp gsp-leading" in html and "Campbell 7" in html
    assert "First half*" in html and "Leading by 1" in html


def test_match_summary_page_is_first_and_has_the_four_panels_without_the_old_highlights_card():
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    html = env.get_template("expanded.html.j2").render(**_stub_context(True))
    for text in ("Match Summary", "How the game went", "Key numbers", "season average",
                 "Standout performers", "Half-time 2 – 1", "better than both averages in 8 of 13 measures"):
        assert text in html, text
    assert "Match Highlights" not in html
    plan = build_page_plan(True)
    assert plan["order"].index("ov_summary") < plan["order"].index("ov_sheet") and plan["pages"]["ov_summary"]["label"] == "PAGE 1/4"

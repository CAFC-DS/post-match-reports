import json

import pandas as pd

from src.report.expanded import player_baseline as pb


def test_minute_of_maps_the_second_half_offset():
    assert pb.minute_of(600) == 10.0
    assert pb.minute_of(10000) == 45.0
    assert abs(pb.minute_of(10997.621) - 61.627) < 0.01
    assert abs(pb.minute_of(12700) - 90.0) < 1e-9


def test_player_minutes_cover_starters_substitutes_and_those_taken_off():
    starting = json.dumps([{"playerId": 1}, {"playerId": 2}])
    subs = json.dumps([
        {"playerId": 2, "substitutionType": "SUB_OFF", "gameTime": {"gameTimeInSec": 10997.621}},
        {"playerId": 3, "substitutionType": "SUB_ON", "gameTime": {"gameTimeInSec": 10997.621}},
        {"playerId": 1, "substitutionType": "POSITION_CHANGE", "gameTime": {"gameTimeInSec": 12259.0}},   # not an exit
    ])
    out = pb.player_minutes({"starting": starting, "subs": subs}, 96.0)
    assert out[1] == 96.0 and round(out[2], 1) == 61.6 and round(out[3], 1) == 34.4
    assert pb.player_minutes({"starting": None, "subs": None}, 90.0) == {}


def test_verdict_uses_a_five_percent_band_and_respects_lower_is_better():
    assert pb.verdict(1.2, 1.0, True) == "up" and pb.verdict(0.8, 1.0, True) == "down"
    assert pb.verdict(1.03, 1.0, True) == "level"
    assert pb.verdict(0.8, 1.0, False) == "up"            # fewer ball losses is better
    assert pb.verdict(None, 1.0, True) == "" and pb.verdict(1.0, None, True) == ""
    assert pb.verdict(0.0, 0.0, True) == "level"


def _row(match, player, group, minutes, squad=1, **kpis):
    base = {c: 0.0 for c in pb.VALUE_COLUMNS}
    return {"matchId": match, "playerId": player, "position": "CENTRAL_MIDFIELD", "group": group, "squadId": squad,
            "minutes": minutes, "shirt": player, "kickoff": f"2026-09-{match:02d}", **{**base, **kpis}}


def test_collapse_positions_sums_kpis_and_keeps_the_busiest_position():
    frame = pd.DataFrame([
        {**_row(1, 7, "MF", 90, SUCCESSFUL_PASSES=30.0), "position": "CENTRAL_MIDFIELD"},
        {**_row(1, 7, "W", 90, SUCCESSFUL_PASSES=5.0), "position": "LEFT_WINGER"},
    ]).drop(columns=["group"] + pb.ACTOR_COLUMNS)
    out = pb.collapse_positions(frame)
    assert len(out) == 1 and out.iloc[0]["SUCCESSFUL_PASSES"] == 35.0
    assert out.iloc[0]["position"] == "CENTRAL_MIDFIELD" and out.iloc[0]["group"] == "MF"


def test_rate_pools_numerators_and_minutes_and_percentages_use_their_denominator():
    frame = pd.DataFrame([_row(1, 7, "MF", 90, SUCCESSFUL_PASSES=40.0, UNSUCCESSFUL_PASSES=10.0, PXT_ATTACK=0.9),
                          _row(2, 7, "MF", 45, SUCCESSFUL_PASSES=10.0, UNSUCCESSFUL_PASSES=0.0, PXT_ATTACK=0.0)])
    assert pb._rate(frame, "pass_pct") == 50.0 / 60.0 * 100
    assert abs(pb._rate(frame, "xt") - 0.9 / 135 * 90) < 1e-9
    assert pb._rate(frame.iloc[0:0], "xt") is None
    assert pb._today(frame.iloc[[0]], "passes") == 40.0           # today is the raw count, not per 90
    assert pb._today(frame.iloc[[0]], "pass_pct") == 40 / 50 * 100


def test_build_player_tables_shows_raw_today_but_rates_the_per_90_equivalent():
    history = pd.DataFrame([
        _row(1, 7, "MF", 90, BALL_WIN_NUMBER=6.0), _row(2, 7, "MF", 90, BALL_WIN_NUMBER=6.0),    # 6 wins per 90
        _row(1, 8, "MF", 90, squad=2, BALL_WIN_NUMBER=6.0), _row(2, 8, "MF", 90, squad=2, BALL_WIN_NUMBER=6.0),
    ])
    today = pd.DataFrame([_row(3, 7, "MF", 45, BALL_WIN_NUMBER=4.0),       # 4 in 45' = 8 per 90: better than 6
                          _row(3, 9, "MF", 10, BALL_WIN_NUMBER=5.0),       # cameo: shown, not rated
                          _row(3, 10, "MF", 90, BALL_WIN_NUMBER=5.0)])     # 5 per 90: worse than 6, no history
    groups = pb.build_player_tables(history, today, 1)
    assert [g["group"] for g in groups] == ["MF"] and [p["playerId"] for p in groups[0]["players"]] == [10, 7, 9]
    wins = lambda p: next(c for c in p["cells"] if c["key"] == "wins")
    by_id = {p["playerId"]: p for p in groups[0]["players"]}
    assert wins(by_id[7])["today"] == 4.0 and wins(by_id[7])["season"] == "up" and wins(by_id[7])["league"] == "up"
    assert wins(by_id[9])["today"] == 5.0 and wins(by_id[9])["season"] == "" and wins(by_id[9])["league"] == ""
    assert wins(by_id[10])["season"] == "" and wins(by_id[10])["league"] == "down"          # no earlier minutes: no season


def test_lower_is_better_metrics_flip_the_verdict():
    history = pd.DataFrame([_row(1, 7, "MF", 90, BALL_LOSS_NUMBER=10.0), _row(1, 8, "MF", 90, squad=2, BALL_LOSS_NUMBER=10.0)])
    today = pd.DataFrame([_row(2, 7, "MF", 90, BALL_LOSS_NUMBER=5.0)])
    cell = next(c for c in pb.build_player_tables(history, today, 1)[0]["players"][0]["cells"] if c["key"] == "losses")
    assert cell["season"] == "up" and cell["league"] == "up"


def test_both_verdict_combines_the_two_comparisons():
    assert pb._both("up", "up") == "up" and pb._both("down", "down") == "down"
    assert pb._both("up", "down") == "mixed" and pb._both("up", "level") == "up"
    assert pb._both("level", "level") == "level" and pb._both("", "down") == "down" and pb._both("", "") == ""


def passes_row_unrated(page):
    return next(r for r in page["rows"] if r["label"] == "Passes completed")["cells"][1]["v_both"] == ""


def test_players_context_is_charlton_only_with_a_page_per_position():
    history = pd.DataFrame([_row(1, 7, "MF", 90, PXT_ATTACK=0.9, SUCCESSFUL_PASSES=40.0),
                            _row(2, 7, "MF", 90, PXT_ATTACK=0.9, SUCCESSFUL_PASSES=40.0),
                            _row(1, 8, "MF", 90, squad=2), _row(2, 8, "MF", 90, squad=2)])
    today = pd.DataFrame([_row(3, 7, "MF", 90, PXT_ATTACK=1.8, SUCCESSFUL_PASSES=44.0), _row(3, 9, "MF", 10, squad=1),
                          _row(3, 8, "MF", 90, squad=2, PXT_ATTACK=0.0)])
    events = pd.DataFrame([dict(playerId=7, playerName="A Seven", squadName="Home", squadId=1),
                           dict(playerId=9, playerName="C Nine", squadName="Home", squadId=1),
                           dict(playerId=8, playerName="B Eight", squadName="Away", squadId=2)])
    ctx = pb.players_context(pd.concat([history, today], ignore_index=True), events, "Home", 3)
    pages = {p["key"]: p for p in ctx["player_pages"]}
    assert list(pages) == ["defenders", "midfielders", "attackers"] and ctx["player_baseline_matches"] == 2
    assert pages["defenders"]["columns"] == [] and pages["attackers"]["rows"] == []        # empty pages are kept
    mf = pages["midfielders"]
    assert [(c["name"], c["rated"]) for c in mf["columns"]] == [("Seven", True), ("Nine", False)]   # no Away players
    labels = [r["label"] for r in mf["rows"]]
    assert labels[:3] == ["Touches", "Passes completed", "Pass accuracy"] and "Threat created (xT)" in labels
    assert all(r["desc"] != "" for r in mf["rows"] if r["label"] == "Threat created (xT)")
    passes = next(r for r in mf["rows"] if r["label"] == "Passes completed")["cells"][0]
    assert passes["text"] == "44" and passes["own"] == "40.0" and passes["v_both"] == "up"   # raw today, per-90 averages
    xt = next(r for r in mf["rows"] if r["label"] == "Threat created (xT)")["cells"][0]
    assert xt["text"] == "1.80" and xt["own"] == "0.90"
    assert passes_row_unrated(mf)                                                          # 10 minutes: not rated


def test_every_position_has_metrics_defined_and_actor_sql_covers_every_actor_column():
    assert set(pb.GROUP_METRICS) == set(pb.GROUP_ORDER)
    assert all(k in pb.METRICS for keys in pb.GROUP_METRICS.values() for k in keys)
    needed = {c for m in pb.METRICS.values() for c in (*m.num, *(m.den or ()))}
    assert needed <= set(pb.VALUE_COLUMNS)
    sql = pb._actor_sql("e.MATCH_ID in (1)", 2114)
    assert all(f'"{c}"' in sql for c in pb.ACTOR_COLUMNS)


def test_players_are_grouped_by_their_natural_position_not_the_one_played_today():
    history = pd.DataFrame([_row(1, 7, "CF", 90, SHOT_XG=0.4), _row(2, 7, "CF", 90, SHOT_XG=0.4),
                            _row(1, 8, "MF", 90, squad=2), _row(1, 9, "MF", 90, squad=1)])
    today = pd.DataFrame([_row(3, 7, "MF", 26, SHOT_XG=0.0), _row(3, 9, "MF", 90), _row(3, 11, "W", 30)])
    groups = {g["group"]: g["players"] for g in pb.build_player_tables(history, today, 1)}
    assert [p["playerId"] for p in groups["CF"]] == [7] and groups["CF"][0]["played_as"] == "Midfielders"
    assert [p["playerId"] for p in groups["MF"]] == [9] and groups["MF"][0]["played_as"] == ""
    assert [p["playerId"] for p in groups["W"]] == [11]                      # no history: today's position
    assert pb.natural_group(history[history["playerId"] == 7]) == "CF" and pb.natural_group(history.iloc[0:0]) is None
    xg = next(c for c in groups["CF"][0]["cells"] if c["key"] == "xg")
    assert xg["league_value"] is not None                                    # compared with the forward average


def test_physical_by_shirt_joins_tracking_to_the_team_sheet_and_filters_by_team():
    class Match:
        physical = pd.DataFrame([dict(opta_player_id=1, distance=10500.0, hsr=420.0, sprinting=90.0,
                                      n_high_intensity_runs=41.0, top_speed=31.2),
                                 dict(opta_player_id=2, distance=9000.0, hsr=300.0, sprinting=50.0,
                                      n_high_intensity_runs=30.0, top_speed=29.0)])

        class f7:
            lineups = pd.DataFrame([dict(player_id="1", team_id="A", shirt_number=8),
                                    dict(player_id="2", team_id="B", shirt_number=8)])

        def side_of(self, team_id):
            return team_id

        def team_name_of(self, side):
            return {"A": "Charlton Athletic", "B": "Cardiff City"}[side]

    out = pb.physical_by_shirt(Match(), "Charlton Athletic")
    assert list(out) == [8] and out[8]["distance"] == 10.5 and out[8]["top_speed"] == 31.2
    assert pb.physical_by_shirt(type("M", (), {"physical": pd.DataFrame(), "f7": Match.f7})(), "Charlton Athletic") == {}


def test_merge_pages_keeps_listed_rows_and_blanks_metrics_of_other_roles():
    def page(key, names, rows):
        return {"key": key, "label": key, "columns": [{"role": key, "name": n} for n in names], "physical": [],
                "rows": [{"key": k, "label": k, "desc": "", "cells": [{"text": f"{k}-{n}", "own": "", "league": "",
                                                                     "v_own": "", "v_league": "", "v_both": ""}
                                                                    for n in names]} for k in rows]}

    merged = {p["key"]: p for p in pb.merge_pages([
        page("gk", ["Keeper"], ["saves", "passes", "clearances"]),
        page("cb", ["A", "B"], ["passes", "interceptions"]), page("fb", [], []), page("mf", ["M"], ["passes"]),
        page("w", [], []), page("cf", [], [])])}
    assert list(merged) == ["defenders", "midfielders", "attackers"]
    d = merged["defenders"]
    assert [c["name"] for c in d["columns"]] == ["Keeper", "A", "B"]
    labels = [r["label"] for r in d["rows"]]
    assert labels == [k for k in pb.PAGE_ROWS["defenders"] if k in {"saves", "passes", "clearances", "interceptions"}]
    saves = next(r for r in d["rows"] if r["key"] == "saves")["cells"]
    assert saves[0]["text"] == "saves-Keeper" and [c["text"] for c in saves[1:]] == ["–", "–"]    # outfielders: no value
    assert merged["attackers"]["columns"] == [] and merged["midfielders"]["columns"][0]["name"] == "M"

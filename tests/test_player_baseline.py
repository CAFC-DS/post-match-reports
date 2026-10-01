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
    base = {c: 0.0 for c in pb.KPI_COLUMNS}
    return {"matchId": match, "playerId": player, "position": "CENTRAL_MIDFIELD", "group": group, "squadId": squad,
            "minutes": minutes, "shirt": player, "kickoff": f"2026-09-{match:02d}", **{**base, **kpis}}


def test_collapse_positions_sums_kpis_and_keeps_the_busiest_position():
    frame = pd.DataFrame([
        {**_row(1, 7, "MF", 90, SUCCESSFUL_PASSES=30.0), "position": "CENTRAL_MIDFIELD"},
        {**_row(1, 7, "W", 90, SUCCESSFUL_PASSES=5.0), "position": "LEFT_WINGER"},
    ]).drop(columns="group")
    out = pb.collapse_positions(frame)
    assert len(out) == 1 and out.iloc[0]["SUCCESSFUL_PASSES"] == 35.0
    assert out.iloc[0]["position"] == "CENTRAL_MIDFIELD" and out.iloc[0]["group"] == "MF"


def test_rate_pools_numerators_and_minutes_and_percentages_use_their_denominator():
    frame = pd.DataFrame([_row(1, 7, "MF", 90, SUCCESSFUL_PASSES=40.0, UNSUCCESSFUL_PASSES=10.0, PXT_ATTACK=0.9),
                          _row(2, 7, "MF", 45, SUCCESSFUL_PASSES=10.0, UNSUCCESSFUL_PASSES=0.0, PXT_ATTACK=0.0)])
    assert pb._rate(frame, "pass_pct") == 50.0 / 60.0 * 100
    assert abs(pb._rate(frame, "xt") - 0.9 / 135 * 90) < 1e-9
    assert pb._rate(frame.iloc[0:0], "xt") is None


def test_build_player_tables_rates_against_own_history_and_the_league_group():
    history = pd.DataFrame([
        _row(1, 7, "MF", 90, PXT_ATTACK=0.9), _row(2, 7, "MF", 90, PXT_ATTACK=0.9),         # player: 0.9 / 90
        _row(1, 8, "MF", 90, PXT_ATTACK=0.0, squad=2), _row(2, 8, "MF", 90, PXT_ATTACK=0.0, squad=2),
    ])
    today = pd.DataFrame([_row(3, 7, "MF", 90, PXT_ATTACK=1.8),                                # twice his average
                          _row(3, 9, "MF", 10, PXT_ATTACK=0.5),                                # cameo: not rated
                          _row(3, 8, "MF", 90, squad=2)])
    groups = pb.build_player_tables(history, today, 1)
    assert [g["group"] for g in groups] == ["MF"] and [p["playerId"] for p in groups[0]["players"]] == [7, 9]
    xt = lambda p: next(c for c in p["cells"] if c["key"] == "xt")
    assert xt(groups[0]["players"][0])["season"] == "up" and xt(groups[0]["players"][0])["league"] == "up"
    assert xt(groups[0]["players"][1])["season"] == "" and xt(groups[0]["players"][1])["league"] == ""

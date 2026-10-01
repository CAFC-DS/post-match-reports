from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.report.expanded import overview as ov


def _f24(rows):
    cols = ["type_id", "period_id", "minute", "second", "seq", "player_id", "team_id", "qualifiers"]
    return pd.DataFrame([{**{"qualifiers": {}, "second": 0, "period_id": 2}, **r} for r in rows], columns=cols)


def _f7():
    def lineup(team, side, start, subs):
        rows = []
        for i, (pid, name, pos) in enumerate(start, start=1):
            rows.append(dict(player_id=pid, team_id=team, side=side, full_name=name, last_name=name.split()[-1],
                             shirt_number=i, position=pos, formation_place=i, status="Start", sub_position=None))
        for j, (pid, name, cls) in enumerate(subs, start=12):
            rows.append(dict(player_id=pid, team_id=team, side=side, full_name=name, last_name=name.split()[-1],
                             shirt_number=j, position="Substitute", formation_place=0, status="Sub", sub_position=cls))
        return rows

    # 4-4-2 style: GK + 4 DEF + 4 MID + 2 STR = 11 starters
    home_start = [("h1", "Gus Keeper", "Goalkeeper")] + \
        [(f"hd{i}", f"Def{i}", "Defender") for i in range(1, 5)] + \
        [(f"hm{i}", f"Mid{i}", "Midfielder") for i in range(1, 5)] + \
        [(f"hs{i}", f"Str{i}", "Striker") for i in range(1, 3)]
    home_subs = [("hb1", "Ben Sub", "Forward"), ("hb2", "Unused Sub", "Defender")]
    lineups = pd.DataFrame(lineup("1", "home", home_start, home_subs) + lineup("2", "away", [("a1", "Al Keeper", "Goalkeeper")], []))
    goals = [SimpleNamespace(minute=10, second=0, scorer_id="hs1", assist_id="hm2", team_id="1")]
    return SimpleNamespace(
        home=SimpleNamespace(team_id="1", name="Home FC", formation="442"),
        away=SimpleNamespace(team_id="2", name="Away FC", formation="4231"),
        goals=goals, lineups=lineups)


def test_formation_rows_and_role_labels():
    assert ov.formation_rows("4231") == [4, 2, 3, 1]
    assert ov.formation_rows("442") == [4, 4, 2]
    assert ov.formation_rows("") is None and ov.formation_rows("999") is None
    labels = ov.role_labels([4, 2, 3, 1])
    assert labels[0] == ["LB", "LCB", "RCB", "RB"]
    assert labels[1] == ["LDM", "RDM"] and labels[2] == ["LW", "AM", "RW"] and labels[3] == ["CF"]
    assert ov.role_labels([3, 5, 2])[1][0] == "LM"


def test_substitutions_are_paired_off_then_on_and_cards_classified():
    f24 = _f24([
        dict(type_id=18, minute=62, second=30, seq=1, player_id="hm1", team_id="1"),
        dict(type_id=19, minute=62, second=30, seq=2, player_id="hb1", team_id="1"),
        dict(type_id=18, minute=70, second=0, seq=3, player_id="x", team_id="2"),   # other team
        dict(type_id=17, minute=33, seq=4, player_id="hd1", team_id="1", qualifiers={31: None}),
        dict(type_id=17, minute=80, seq=5, player_id="hd2", team_id="1", qualifiers={33: None}),
        dict(type_id=17, minute=81, seq=6, player_id="hd3", team_id="1", qualifiers={}),
    ])
    assert ov.substitution_pairs(f24, "1") == [{"off": "hm1", "on": "hb1", "minute": 62.5}]
    assert ov.card_events(f24, "1") == [
        {"player": "hd1", "kind": "yellow", "minute": 33}, {"player": "hd2", "kind": "red", "minute": 80}]


def _positions(sheet):
    """Deterministic tracking-style positions: depth by class, lateral left to right."""
    depth = {"Defender": -20.0, "Midfielder": 0.0, "Striker": 20.0}
    out, lateral = {}, {"Defender": 0, "Midfielder": 0, "Striker": 0}
    for p in sheet.starters:
        if p.pos_class == "Goalkeeper":
            continue
        lateral[p.pos_class] += 1
        out[p.player_id] = (depth[p.pos_class], 30.0 - 12.0 * lateral[p.pos_class])   # first listed = leftmost
    return out


def test_team_sheet_minutes_events_and_inherited_roles():
    f24 = _f24([
        dict(type_id=18, minute=60, seq=1, player_id="hm1", team_id="1"),
        dict(type_id=19, minute=60, seq=2, player_id="hb1", team_id="1"),
        dict(type_id=1, period_id=2, minute=95, second=0, seq=9, player_id="hd1", team_id="1"),
        dict(type_id=17, minute=33, seq=4, player_id="hd1", team_id="1", qualifiers={31: None}),
    ])
    sheets, end = ov.build_team_sheets(_f7(), f24)
    assert end == 95.0
    home = sheets["home"]
    by_id = {p.player_id: p for p in home.players}
    assert by_id["hm1"].minutes(end) == 60 and by_id["hb1"].minutes(end) == 35
    assert by_id["hb2"].played is False and by_id["hb2"].minutes(end) == 0
    assert by_id["hs1"].goals == [10] and by_id["hm2"].assists == [10]
    assert by_id["hd1"].yellows == [33]
    assert by_id["hb1"].replaced == "hm1"
    assert [p.player_id for p in home.substitutes if p.played] == ["hb1"]
    kinds = [(e["kind"], e["player"]) for e in ov.timeline_events(home)]
    assert ("goal", "1") in [(k, "1") for k, _ in kinds] and ("sub", "Sub") in kinds


def test_lineup_slots_use_class_then_depth_and_subs_inherit_role():
    sheets, _ = ov.build_team_sheets(_f7(), _f24([
        dict(type_id=18, minute=60, seq=1, player_id="hm1", team_id="1"),
        dict(type_id=19, minute=60, seq=2, player_id="hb1", team_id="1"),
    ]))
    home = sheets["home"]
    slots = ov.lineup_slots(home, _positions(home))
    assert [s["role"] for s in slots if s["row"] == 1] == ["LB", "LCB", "RCB", "RB"]
    assert [s["role"] for s in slots if s["row"] == 2] == ["LM", "LCM", "RCM", "RM"]
    assert [s["role"] for s in slots if s["row"] == 3] == ["LS", "RS"]
    assert slots[0]["role"] == "GK" and len(slots) == 11
    ov._assign_roles(home, _positions(home))
    by_id = {p.player_id: p for p in home.players}
    assert by_id["hm1"].role == "LM"
    assert by_id["hb1"].role == "LM"          # came on for hm1
    # No positions (or a formation that does not fit) means no lineup graphic.
    assert ov.lineup_slots(home, None) == []


def test_impect_positions_match_players_by_name():
    sheets, _ = ov.build_team_sheets(_f7(), _f24([]))
    home = sheets["home"]
    events = pd.DataFrame({
        "squadName": ["Home FC"] * 4,
        "playerName": ["Def1", "Def1", "Str2", "Somebody Else"],
        "startAdjCoordinatesX": [-30.0, -20.0, 25.0, 0.0],
        "startAdjCoordinatesY": [10.0, 20.0, -5.0, 0.0],
    })
    pos = ov.impect_positions(events, home)
    assert pos["hd1"] == (-25.0, 15.0) and pos["hs2"] == (25.0, -5.0)
    assert "hm1" not in pos
    assert ov.impect_positions(None, home) is None


def test_team_goals_and_half_time_score_use_the_right_period():
    f7 = _f7()
    f7.goals.append(SimpleNamespace(minute=45, second=0, scorer_id="hs2", assist_id=None, team_id="1"))   # 45+ stoppage
    f7.goals.append(SimpleNamespace(minute=70, second=0, scorer_id="a1", assist_id="a1", team_id="2"))
    f24 = _f24([
        dict(type_id=16, minute=10, period_id=1, seq=1, player_id="hs1", team_id="1"),
        dict(type_id=16, minute=46, period_id=1, seq=2, player_id="hs2", team_id="1"),   # first-half stoppage
        dict(type_id=16, minute=70, period_id=2, seq=3, player_id="a1", team_id="2"),
    ])
    goals = ov.team_goals(f7, "1")
    assert [(g["who"], g["min"]) for g in goals] == [("Str1", "10'"), ("Str2", "45'")] and goals[0]["assist"] == "Mid2"
    assert ov.team_goals(f7, "2") == [{"who": "Keeper", "min": "70'", "assist": "Keeper"}]
    assert ov.half_time_score(f7, f24) == {"1": 2, "2": 0}


def test_simultaneous_substitutions_share_one_label():
    events = [
        {"minute": 81.7, "kind": "sub", "player": "Scanlon"},
        {"minute": 82.0, "kind": "sub", "player": "Lawlor"},
        {"minute": 82.0, "kind": "yellow", "player": "Bagan"},
        {"minute": 90.0, "kind": "sub", "player": "Ashford"},
    ]
    merged = ov._merge_substitutions(events)
    assert [e["player"] for e in merged] == ["Scanlon / Lawlor", "Bagan", "Ashford"]
    assert [e["kind"] for e in merged] == ["sub", "yellow", "sub"]


def test_flow_and_timeline_charts_render_with_late_events_and_share_the_xg_axis():
    x = np.linspace(0, 96, 97)
    y = 20 * np.sin(x / 9)
    events = [("Charlton Athletic", True, [{"minute": 28.0, "kind": "goal", "player": "Campbell"},
                                           {"minute": 95.0, "kind": "yellow", "player": "Colwill"},
                                           {"minute": 96.0, "kind": "yellow", "player": "Another"}]),
              ("Cardiff City", False, [{"minute": 60.0, "kind": "goal", "player": "Moylan"},
                                       {"minute": 81.7, "kind": "sub", "player": "Scanlon"},
                                       {"minute": 82.0, "kind": "sub", "player": "Lawlor"}])]
    assert ov.flow_timeline_chart(x, y).startswith("data:image/png;base64,")
    assert ov.flow_timeline_chart(x, y * 0, y_label="Net threat").startswith("data:image/png")
    assert ov.timeline_chart(events).startswith("data:image/png;base64,")
    assert ov.timeline_chart([("Charlton Athletic", True, []), ("Cardiff City", False, [])]).startswith("data:image/png")
    assert ov.X_AXIS_MAX > 96 and ov.X_AXIS_TICKS[-1] == 90

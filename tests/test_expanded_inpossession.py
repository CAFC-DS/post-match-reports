import numpy as np
import pandas as pd

from src.report.expanded import inpossession as ip

CHA, OPP = "Charlton Athletic", "Cardiff City"


def _events(rows):
    base = dict(squadName=CHA, playerName="Some Player", actionType="PASS", action="LOW_PASS", result="SUCCESS",
                startAdjCoordinatesX=0.0, startAdjCoordinatesY=0.0, endAdjCoordinatesX=0.0, endAdjCoordinatesY=0.0,
                startPitchPosition="MIDDLE", endPitchPosition="MIDDLE", startPackingZone="CMC", endPackingZone="CMC",
                BYPASSED_OPPONENTS=0.0, BYPASSED_DEFENDERS=0.0, BYPASSED_OPPONENTS_RECEIVING=0.0, BYPASSED_DEFENDERS_RECEIVING=0.0, PXT_ATTACK=0.0,
                eventId=0)
    return pd.DataFrame([{**base, **r, "eventId": i} for i, r in enumerate(rows)])


def test_progression_zones_group_by_role_and_count_opponents_bypassed():
    events = _events([
        dict(endPackingZone="DMC", BYPASSED_OPPONENTS=2.0),
        dict(endPackingZone="DML", BYPASSED_OPPONENTS=1.0, actionType="DRIBBLE"),       # DML and DMC are one role group
        dict(endPackingZone="AMR", BYPASSED_OPPONENTS=3.0),
        dict(endPackingZone="OPP_CBC", BYPASSED_OPPONENTS=4.0),                          # lost: opposition zone, dropped
        dict(endPackingZone="WL", BYPASSED_OPPONENTS=0.0),                               # bypassed nothing
        dict(endPackingZone="CMC", BYPASSED_OPPONENTS=5.0, result="FAIL"),               # lost
        dict(endPackingZone="CMC", BYPASSED_OPPONENTS=5.0, squadName=OPP),               # other team
        dict(endPackingZone=None, BYPASSED_OPPONENTS=1.0),                               # untagged
    ])
    out = ip.progression_zones(events, CHA)
    assert out["values"] == {"DM": 3.0, "AM": 3.0}
    assert out["total"] == 6.0 and out["actions"] == 5      # OPP_ and untagged rows still count as actions
    assert out["defenders"] == {"DM": 0.0, "AM": 0.0} and out["defenders_total"] == 0.0


def test_progression_zones_count_defenders_bypassed_separately():
    events = _events([
        dict(endPackingZone="AMC", BYPASSED_OPPONENTS=3.0, BYPASSED_DEFENDERS=2.0),
        dict(endPackingZone="AMC", BYPASSED_OPPONENTS=1.0, BYPASSED_DEFENDERS=np.nan),   # missing counts as none
        dict(endPackingZone="DMC", BYPASSED_OPPONENTS=2.0, BYPASSED_DEFENDERS=0.0),       # past forwards only
    ])
    out = ip.progression_zones(events, CHA)
    assert out["values"] == {"AM": 4.0, "DM": 2.0}
    assert out["defenders"] == {"AM": 2.0, "DM": 0.0} and out["defenders_total"] == 2.0


def test_threat_zone_values_keep_positive_open_play_threat_only():
    events = _events([
        dict(endPackingZone="AMC", PXT_ATTACK=0.05),
        dict(endPackingZone="AMC", PXT_ATTACK=-0.03),                              # threat lost: ignored
        dict(endPackingZone="AMC", PXT_ATTACK=0.40, action="GOAL"),                # goals excluded
        dict(endPackingZone="IBC", PXT_ATTACK=0.20, actionType="SHOT"),            # not a pass or carry
        dict(endPackingZone="OPP_AMC", PXT_ATTACK=0.10),                           # opposition zone: dropped
        dict(endPackingZone="WR", PXT_ATTACK=np.nan),
    ])
    out = ip.threat_zone_values(events, CHA)
    assert {k: v for k, v in out["values"].items() if v} == {"AM": 0.05} and abs(out["total"] - 0.05) < 1e-9


def test_reception_summary_categories_roles_and_players():
    rec = dict(actionType="RECEPTION")
    events = _events([
        dict(rec, action="AVAILABILITY_BTL", playerName="A One", startPackingZone="AMC", BYPASSED_OPPONENTS_RECEIVING=2.0, BYPASSED_DEFENDERS_RECEIVING=1.0, PXT_ATTACK=0.03),
        dict(rec, action="AVAILABILITY_BTL", playerName="A One", startPackingZone="AML", BYPASSED_OPPONENTS_RECEIVING=1.0, PXT_ATTACK=-0.01),
        dict(rec, action="AVAILABILITY_OUT_WIDE", playerName="B Two", startPackingZone="WL"),
        dict(rec, action="HOLD_UP_PLAY", playerName="B Two", startPackingZone="IBC", BYPASSED_OPPONENTS_RECEIVING=1.0),
        dict(rec, action="AVAILABILITY_FDR", playerName="C Three", startPackingZone="IBC"),
        dict(rec, action="AVAILABILITY_IN_THE_BACK", playerName="D Four", startPackingZone="CBC"),   # build-up: excluded
        dict(rec, action="HEADER", playerName="D Four", startPackingZone="CBC"),                       # header: excluded
        dict(rec, action="AVAILABILITY_BTL", playerName="E Five", squadName=OPP),
    ])
    out = ip.reception_summary(events, CHA)
    assert out["total"] == 5 and out["bypassed"] == 4
    assert out["counts"]["Between the lines"] == 2 and out["counts"]["In behind"] == 1
    assert {k: v for k, v in out["values"].items() if v} == {"AM": 3.0, "IB": 1.0}
    assert out["receptions_by_role"]["AM"] == 2.0 and out["receptions_by_role"]["WL"] == 1.0
    assert [p["name"] for p in out["players"]] == ["One", "Two", "Three"]      # by bypassed, then receptions
    top = out["players"][0]
    assert top["receptions"] == 2 and top["bypassed"] == 3 and abs(top["xt"] - 0.03) < 1e-9   # negative xT not counted
    assert out["defenders"] == 1 and out["defenders_by_role"]["AM"] == 1.0 and top["defenders"] == 1
    assert out["top_opponents"].to_dict() == {"One": 3.0, "Two": 1.0}      # players who bypassed nobody are left out
    assert out["top_defenders"].to_dict() == {"One": 1.0}


def test_reception_summary_tolerates_missing_kpi_column_and_no_receptions():
    events = _events([dict(actionType="RECEPTION", action="HOLD_UP_PLAY", playerName="A One")])
    out = ip.reception_summary(events.drop(columns=["BYPASSED_OPPONENTS_RECEIVING", "BYPASSED_DEFENDERS_RECEIVING"]), CHA)
    assert out["total"] == 1 and out["bypassed"] == 0 and out["defenders"] == 0 and len(out["top_opponents"]) == 0
    empty = ip.reception_summary(_events([dict(action="LOW_PASS")]), CHA)
    assert empty["total"] == 0 and empty["players"] == [] and empty["values"] == {}


def test_player_threat_panels_split_by_action_on_the_same_positive_basis():
    events = _events([
        dict(playerName="A One", actionType="PASS", PXT_ATTACK=0.30),
        dict(playerName="A One", actionType="PASS", PXT_ATTACK=-0.10),               # threat lost: ignored
        dict(playerName="A One", actionType="DRIBBLE", PXT_ATTACK=0.10),
        dict(playerName="B Two", actionType="DRIBBLE", PXT_ATTACK=0.20),
        dict(playerName="B Two", actionType="RECEPTION", PXT_ATTACK=0.15),
        dict(playerName="A One", actionType="PASS", PXT_ATTACK=0.90, action="GOAL"),  # goals excluded
        dict(playerName="C Three", actionType="PASS", PXT_ATTACK=0.40, squadName=OPP),
    ])
    out = ip.player_threat_panels(events, CHA)
    assert out["passing"].to_dict() == {"One": 0.30}
    assert out["carrying"].to_dict() == {"Two": 0.20, "One": 0.10}
    assert out["receiving"].to_dict() == {"Two": 0.15}
    assert abs(out["created_total"] - 0.60) < 1e-9       # passing + carrying, the existing "threat created" measure
    assert abs(out["receiving_total"] - 0.15) < 1e-9
    assert len(ip.player_threat_panels(events, CHA, top=1)["carrying"]) == 1


def test_role_values_drop_opposition_and_untagged_zones():
    frame = _events([dict(endPackingZone="GKC"), dict(endPackingZone="OPP_GKC"), dict(endPackingZone=None),
                     dict(endPackingZone="IBWL")])
    assert ip._role_values(frame, "endPackingZone", pd.Series([1.0, 1.0, 1.0, 1.0])) == {"GK": 1.0, "IBWL": 1.0}


def test_entry_givers_counts_completed_entries_by_player():
    events = _events([
        dict(playerName="A One", startPitchPosition="MIDDLE", endPitchPosition="FINAL_THIRD"),
        dict(playerName="A One", startPitchPosition="MIDDLE", endPitchPosition="FINAL_THIRD", actionType="DRIBBLE"),
        dict(playerName="B Two", startPitchPosition="FINAL_THIRD", endPitchPosition="OPPONENT_BOX"),
        dict(playerName="B Two", startPitchPosition="MIDDLE", endPitchPosition="FINAL_THIRD", result="FAIL"),  # lost
        dict(playerName="C Three", startPitchPosition="MIDDLE", endPitchPosition="FINAL_THIRD", squadName=OPP),
    ])
    out = ip.entry_givers(events, CHA)
    assert out["final_third"].to_dict() == {"One": 2} and out["box"].to_dict() == {"Two": 1}
    assert out["n_final_third"] == 2 and out["n_box"] == 1
    none = ip.entry_givers(_events([dict(playerName="A One")]), CHA)
    assert none["n_final_third"] == 0 and none["n_box"] == 0


def test_charts_render_to_data_uris():
    values = {"GK": 2.0, "CB": 6.0, "DM": 101.0, "CM": 81.0, "WL": 26.0, "AM": 80.0, "IB": 21.0}
    assert ip.packing_zone_chart(values, "#d01012", vmax=101.0).startswith("data:image/png;base64,")
    assert ip.packing_zone_chart(values, "#7d7869", vmax=101.0, sub={"DM": "29 received"}).startswith("data:image/png")
    assert ip.packing_zone_chart({}, "#7d7869", vmax=0.0, decimals=2).startswith("data:image/png")
    assert ip.packing_zone_chart(values, "#d01012", vmax=101.0, label_prefix="To ", small=True).startswith(
        "data:image/png")
    summary = ip.reception_summary(_events([dict(actionType="RECEPTION", action="HOLD_UP_PLAY", playerName="A One",
                                                 BYPASSED_OPPONENTS_RECEIVING=2.0)]), CHA)
    assert ip.reception_bars_chart(summary, "#d01012").startswith("data:image/png")
    givers = ip.entry_givers(_events([dict(playerName="A One", endPitchPosition="FINAL_THIRD")]), CHA)
    assert ip.entry_givers_chart(givers, "#d01012").startswith("data:image/png")
    panels = ip.player_threat_panels(_events([dict(playerName="A One", PXT_ATTACK=0.1)]), CHA)
    assert ip.player_threat_chart(panels, "#d01012").startswith("data:image/png")
    empty = ip.player_threat_panels(_events([dict(action="LOW_PASS", squadName=OPP)]), CHA)
    assert ip.player_threat_chart(empty, "#d01012").startswith("data:image/png")


def test_inpossession_context_shares_scales_and_covers_both_teams():
    events = _events([
        dict(endPackingZone="DMC", BYPASSED_OPPONENTS=2.0, PXT_ATTACK=0.1),
        dict(endPackingZone="DMC", BYPASSED_OPPONENTS=8.0, PXT_ATTACK=0.2, squadName=OPP),
        dict(actionType="RECEPTION", action="AVAILABILITY_BTL", startPackingZone="AMC", playerName="A One"),
    ])
    ctx = ip.inpossession_context(events, CHA, OPP)
    for key in ("progression_img", "progression_kpis", "threat_zone_img", "threat_zone_kpis", "reception_ctx",
                "entry_givers_ctx", "player_threat_ctx"):
        assert set(ctx[key]) == {CHA, OPP}, key
    assert ctx["progression_kpis"][CHA] == {"total": 2, "actions": 1, "defenders": 0}
    assert ctx["progression_kpis"][OPP]["total"] == 8
    assert ctx["reception_ctx"][CHA]["players"][0]["name"] == "One"

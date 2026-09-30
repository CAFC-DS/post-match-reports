import numpy as np
import pandas as pd

from src.report.expanded import inpossession as ip

CHA, OPP = "Charlton Athletic", "Cardiff City"


def _events(rows):
    base = dict(squadName=CHA, playerName="Some Player", actionType="PASS", action="LOW_PASS", result="SUCCESS",
                startAdjCoordinatesX=0.0, startAdjCoordinatesY=0.0, endAdjCoordinatesX=0.0, endAdjCoordinatesY=0.0,
                startPitchPosition="MIDDLE", endPitchPosition="MIDDLE", BYPASSED_OPPONENTS=0.0,
                BYPASSED_OPPONENTS_RECEIVING=0.0, PXT_ATTACK=0.0, eventId=0)
    frame = pd.DataFrame([{**base, **r, "eventId": i} for i, r in enumerate(rows)])
    return frame


def test_progression_zones_bin_by_end_location_and_count_opponents_bypassed():
    events = _events([
        dict(endAdjCoordinatesX=-50, endAdjCoordinatesY=-30, BYPASSED_OPPONENTS=2.0),   # own goal line, bottom
        dict(endAdjCoordinatesX=50, endAdjCoordinatesY=30, BYPASSED_OPPONENTS=3.0),     # far end, top
        dict(endAdjCoordinatesX=50, endAdjCoordinatesY=30, BYPASSED_OPPONENTS=1.0, actionType="DRIBBLE"),
        dict(endAdjCoordinatesX=10, endAdjCoordinatesY=0, BYPASSED_OPPONENTS=0.0),       # bypassed nothing
        dict(endAdjCoordinatesX=10, endAdjCoordinatesY=0, BYPASSED_OPPONENTS=4.0, result="FAIL"),  # lost
        dict(endAdjCoordinatesX=10, endAdjCoordinatesY=0, BYPASSED_OPPONENTS=4.0, squadName=OPP),  # other team
    ])
    out = ip.progression_zones(events, CHA)
    grid = out["grid"]
    assert grid.shape == (3, 6)
    assert grid[0, 0] == 2.0 and grid[2, 5] == 4.0
    assert out["total"] == 6.0 and out["actions"] == 3
    # Coordinates on the pitch edge clip into the last cell instead of falling off the grid.
    edge = _events([dict(endAdjCoordinatesX=52.5, endAdjCoordinatesY=34.0, BYPASSED_OPPONENTS=1.0)])
    assert ip.progression_zones(edge, CHA)["grid"][2, 5] == 1.0


def test_threat_zone_grid_keeps_positive_open_play_threat_only():
    events = _events([
        dict(endAdjCoordinatesX=40, endAdjCoordinatesY=0, PXT_ATTACK=0.05),
        dict(endAdjCoordinatesX=40, endAdjCoordinatesY=0, PXT_ATTACK=-0.03),               # threat lost: ignored
        dict(endAdjCoordinatesX=40, endAdjCoordinatesY=0, PXT_ATTACK=0.40, action="GOAL"),  # goals excluded
        dict(endAdjCoordinatesX=40, endAdjCoordinatesY=0, PXT_ATTACK=0.20, actionType="SHOT"),  # not a pass/carry
        dict(endAdjCoordinatesX=-40, endAdjCoordinatesY=0, PXT_ATTACK=np.nan),
    ])
    out = ip.threat_zone_grid(events, CHA)
    assert abs(out["total"] - 0.05) < 1e-9
    assert out["grid"][1, 5] == 0.05


def test_reception_summary_categories_exclude_buildup_and_headers():
    rec = dict(actionType="RECEPTION", startAdjCoordinatesX=20.0, startAdjCoordinatesY=5.0)
    events = _events([
        dict(rec, action="AVAILABILITY_BTL", playerName="A One", BYPASSED_OPPONENTS_RECEIVING=2.0),
        dict(rec, action="AVAILABILITY_BTL", playerName="A One", BYPASSED_OPPONENTS_RECEIVING=1.0),
        dict(rec, action="AVAILABILITY_OUT_WIDE", playerName="B Two"),
        dict(rec, action="HOLD_UP_PLAY", playerName="B Two", BYPASSED_OPPONENTS_RECEIVING=1.0),
        dict(rec, action="AVAILABILITY_FDR", playerName="C Three"),
        dict(rec, action="AVAILABILITY_IN_THE_BOX", playerName="C Three"),
        dict(rec, action="AVAILABILITY_IN_THE_BACK", playerName="D Four"),   # build-up: excluded
        dict(rec, action="HEADER", playerName="D Four"),                      # header: excluded
        dict(rec, action="AVAILABILITY_BTL", playerName="E Five", squadName=OPP),
    ])
    out = ip.reception_summary(events, CHA)
    assert out["total"] == 6 and out["bypassed"] == 4
    assert out["counts"]["Between the lines"] == 2 and out["counts"]["In behind"] == 1
    assert [p["name"] for p in out["players"]] == ["One", "Two", "Three"]      # by bypassed, then receptions
    assert out["players"][0]["bypassed"] == 3 and out["players"][0]["counts"][0] == 2
    assert len(out["points"]) == 6


def test_reception_summary_tolerates_missing_kpi_column_and_no_receptions():
    events = _events([dict(actionType="RECEPTION", action="HOLD_UP_PLAY", playerName="A One")])
    out = ip.reception_summary(events.drop(columns=["BYPASSED_OPPONENTS_RECEIVING"]), CHA)
    assert out["total"] == 1 and out["bypassed"] == 0
    empty = ip.reception_summary(_events([dict(action="LOW_PASS")]), CHA)
    assert empty["total"] == 0 and empty["players"] == []


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
    grid = np.arange(18, dtype=float).reshape(3, 6)
    assert ip.zone_grid_chart(grid, "#d01012", vmax=17.0).startswith("data:image/png;base64,")
    assert ip.zone_grid_chart(np.zeros((3, 6)), "#7d7869", vmax=0.0, decimals=2).startswith("data:image/png")
    events = _events([dict(actionType="RECEPTION", action="AVAILABILITY_BTL", BYPASSED_OPPONENTS_RECEIVING=2.0)])
    assert ip.reception_map(ip.reception_summary(events, CHA)["points"]).startswith("data:image/png")
    givers = ip.entry_givers(_events([dict(playerName="A One", endPitchPosition="FINAL_THIRD")]), CHA)
    assert ip.entry_givers_chart(givers, "#d01012").startswith("data:image/png")

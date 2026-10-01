import pandas as pd

from src.report.expanded import outofpossession as ooc

CHA, OPP = "Charlton Athletic", "Cardiff City"


def _duels():
    return pd.DataFrame([
        dict(eventId=1, squadName=CHA, playerName="A One", duel_type="AERIAL", outcome="WON",
             startAdjCoordinatesX=10.0, startAdjCoordinatesY=5.0),
        dict(eventId=1, squadName=OPP, playerName="B Two", duel_type="AERIAL", outcome="LOST",    # loser: other frame
             startAdjCoordinatesX=10.0, startAdjCoordinatesY=5.0),
        dict(eventId=2, squadName=OPP, playerName="B Two", duel_type="GROUND", outcome="WON",
             startAdjCoordinatesX=-3.0, startAdjCoordinatesY=1.0),
    ])


def _events():
    return pd.DataFrame([dict(eventId=1, squadName=CHA, result="SUCCESS"), dict(eventId=2, squadName=OPP, result="FAIL")])


def test_orient_duels_flips_the_row_of_the_team_that_did_not_act():
    out = ooc.orient_duels(_duels(), _events())
    assert list(zip(out["x"], out["y"])) == [(10.0, 5.0), (-10.0, -5.0), (-3.0, 1.0)]


def test_duel_totals_count_won_total_and_percentage_by_type():
    totals = ooc.duel_totals(_duels(), OPP)
    assert totals["all"] == {"won": 1, "total": 2, "pct": 50}
    assert totals["AERIAL"] == {"won": 0, "total": 1, "pct": 0} and totals["GROUND"]["pct"] == 100
    assert ooc.duel_totals(_duels(), "Nobody")["all"] == {"won": 0, "total": 0, "pct": 0}


def test_pressing_summary_counts_forced_turnovers_and_orients_pressures():
    pressure = pd.DataFrame([
        dict(eventId=1, squadName=CHA, playerName="A One", startAdjCoordinatesX=-30.0, startAdjCoordinatesY=0.0),
        dict(eventId=2, squadName=CHA, playerName="A One", startAdjCoordinatesX=-5.0, startAdjCoordinatesY=0.0),
        dict(eventId=2, squadName=OPP, playerName="B Two", startAdjCoordinatesX=-5.0, startAdjCoordinatesY=0.0),
    ])
    events = pd.DataFrame([dict(eventId=1, result="SUCCESS"), dict(eventId=2, result="FAIL")])
    out = ooc.pressing_summary(pressure, events, CHA)
    assert (out["n"], out["forced"], out["forced_pct"]) == (2, 1, 50)
    assert out["opp_half"] == 2 and out["opp_third"] == 1       # carrier frame is negated: -30 -> +30 (final third)
    assert out["top_pressures"].to_dict() == {"One": 2} and out["top_forced"].to_dict() == {"One": 1}
    assert ooc.pressing_summary(pressure.iloc[0:0], events, CHA)["n"] == 0


def test_context_renders_both_teams_with_empty_inputs():
    events, duels = _events(), _duels()
    pressure = pd.DataFrame(columns=["eventId", "squadName", "playerName", "startAdjCoordinatesX", "startAdjCoordinatesY"])
    ctx = ooc.outofpossession_context(events, duels, pressure, CHA, OPP)
    assert set(ctx["duel_totals"]) == set(ctx["pressing_img"]) == set(ctx["duel_map_img"]) == {CHA, OPP}
    assert ctx["duel_map_img"][CHA]["AERIAL"].startswith("data:image/png")
    assert ctx["pressing_kpis"][CHA]["n"] == 0

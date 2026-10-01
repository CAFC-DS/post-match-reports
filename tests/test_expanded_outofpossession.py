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
    return pd.DataFrame([dict(eventId=1, squadName=CHA, result="SUCCESS", gameTimeInSec=10, BALL_WIN_NUMBER=0.0,
                              SHOT_AT_GOAL_NUMBER=0.0, BALL_LOSS_NUMBER=0.0, startAdjCoordinatesX=0.0),
                         dict(eventId=2, squadName=OPP, result="FAIL", gameTimeInSec=20, BALL_WIN_NUMBER=0.0,
                              SHOT_AT_GOAL_NUMBER=0.0, BALL_LOSS_NUMBER=0.0, startAdjCoordinatesX=0.0)])


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


def _regain_events():
    def row(i, squad, t, x, win=0.0, shot=0.0, loss=0.0, player="A One"):
        return dict(eventId=i, squadName=squad, playerName=player, gameTimeInSec=t, startAdjCoordinatesX=x,
                    startAdjCoordinatesY=0.0, BALL_WIN_NUMBER=win, SHOT_AT_GOAL_NUMBER=shot, BALL_LOSS_NUMBER=loss,
                    result="SUCCESS")
    return pd.DataFrame([
        row(1, CHA, 10, -30, win=1.0),                                   # defensive third
        row(2, CHA, 100, 0, win=1.0, player="B Two"),                    # middle third, then a shot 5s later: counted
        row(3, CHA, 105, 30, shot=1.0),
        row(4, CHA, 200, 40, win=1.0, player="B Two"),                   # attacking third, shot at 208 but the
        row(5, OPP, 204, 10),                                            #   opponent touched it first: not counted
        row(6, CHA, 208, 45, shot=1.0),
        row(7, CHA, 300, -40, loss=1.0),
        row(8, CHA, 310, 20, loss=1.0),
        row(9, OPP, 320, 5, win=1.0),
    ])


def test_regains_are_split_by_third_and_shot_after_regain_needs_unbroken_possession():
    out = ooc.regain_summary(_regain_events(), CHA)
    assert out["n"] == 3 and out["counts"] == [1, 1, 1] and out["pcts"] == [33, 33, 33]
    assert out["shots"] == 1 and out["shot_pct"] == 33
    assert out["losses"] == [1, 0, 1] and out["losses_n"] == 2
    assert out["players"] == [("Two", [0, 1, 1]), ("One", [1, 0, 0])]
    assert ooc.regain_summary(_regain_events(), OPP)["counts"] == [0, 1, 0]
    assert ooc.regain_summary(_regain_events().iloc[0:0], CHA)["n"] == 0


def test_regain_charts_render_even_without_regains():
    for events in (_regain_events(), _regain_events().iloc[0:0]):
        summary = ooc.regain_summary(events, CHA)
        assert ooc.regain_map_chart(summary).startswith("data:image/png")
        assert ooc.regain_players_chart(summary).startswith("data:image/png")

import pandas as pd

from src.report.expanded import gamestate as gs

HOME, AWAY = "Cardiff City", "Charlton Athletic"


def _ev(i, squad, time, period=1, **kw):
    base = dict(eventId=i, squadName=squad, playerName="A Player", actionType="PASS", action="LOW_PASS",
                gameTime=time, gameTimeInSec=0.0, periodId=period, homeSquadName=HOME, awaySquadName=AWAY,
                SHOT_AT_GOAL_NUMBER=0.0, SHOT_XG=0.0, BALL_WIN_NUMBER=0.0, startAdjCoordinatesX=0.0)
    return {**base, **kw}


def _events():
    rows = [
        _ev(1, AWAY, "10:00.000", gameTimeInSec=600),
        _ev(2, AWAY, "20:00.000", gameTimeInSec=1200, actionType="SHOT", action="GOAL", SHOT_AT_GOAL_NUMBER=1.0, SHOT_XG=.3,
            playerName="C Campbell"),                                                        # Charlton lead 1-0 at 20'
        _ev(3, HOME, "30:00.000", gameTimeInSec=1800, actionType="SHOT", action="MID_RANGE_SHOT", SHOT_AT_GOAL_NUMBER=1.0,
            SHOT_XG=.1),
        _ev(4, HOME, "50:00.000", 2, gameTimeInSec=10300, actionType="SHOT", action="GOAL", SHOT_AT_GOAL_NUMBER=1.0,
            SHOT_XG=.5, playerName="M Moylan"),                                              # 1-1 at 50'
        _ev(5, AWAY, "70:00.000", 2, gameTimeInSec=11500, actionType="OWN_GOAL", action="OWN_GOAL",
            playerName="O Gal"),                                                             # own goal: credited to Cardiff
        _ev(6, HOME, "80:00.000", 2, gameTimeInSec=12000, BALL_WIN_NUMBER=1.0, startAdjCoordinatesX=20.0),
        _ev(7, HOME, "90:00.0000 (+05:00.0000)", 2, gameTimeInSec=12900),
    ]
    return pd.DataFrame(rows)


def test_minutes_and_period_bins_fold_stoppage_into_the_half():
    ev = gs.with_minutes(pd.concat([_events(), pd.DataFrame([_ev(8, HOME, "45:00.0000 (+02:00.0000)", 1)])]))
    assert ev.loc[ev["eventId"] == 8, "period_bin"].iloc[0] == 2           # first-half stoppage stays in 30-45
    assert ev.loc[ev["eventId"] == 7, "period_bin"].iloc[0] == 5           # 95' stays in 75-90
    assert ev.loc[ev["eventId"] == 4, "period_bin"].iloc[0] == 3


def test_goal_timeline_credits_own_goals_to_the_other_side():
    goals = gs.goal_minutes(gs.with_minutes(_events()))
    assert [(round(m), t) for m, t, _ in goals] == [(20, AWAY), (50, HOME), (70, HOME)]


def test_state_intervals_follow_the_score_and_cover_the_whole_match():
    goals = gs.goal_minutes(gs.with_minutes(_events()))
    ivs = gs.state_intervals(goals, AWAY, 95.0)
    assert [i["state"] for i in ivs] == ["level", "leading", "level", "trailing"]
    assert abs(sum(i["end"] - i["start"] for i in ivs) - 95.0) < 1e-9
    assert [i["diff"] for i in ivs] == [0, 1, 0, -1]
    assert gs.state_intervals([], AWAY, 90.0) == [{"start": 0.0, "end": 90.0, "state": "level", "diff": 0}]


def test_slices_measure_both_teams_and_flag_small_samples():
    pressure = pd.DataFrame([dict(eventId=1, squadName=AWAY), dict(eventId=6, squadName=AWAY),
                             dict(eventId=3, squadName=HOME)])
    out = gs.game_state_tables(_events(), pressure, AWAY, HOME, first_sub_minute=60.0)
    states = {s["key"]: s for s in out["states"]}
    assert set(states) == {"leading", "level", "trailing"}
    leading = states["leading"]            # after 20' up to 50': Cardiff's 30' shot (0.1) and their 50' equaliser (0.5)
    assert leading["minutes"] == 30.0 and leading["xg_against"] == 0.6 and leading["xg_for"] == 0.0
    assert states["level"]["xg_for"] == 0.3 and states["level"]["xg_against"] == 0.0     # Charlton's goal at 20' is "level"
    assert states["level"]["minutes"] == 40.0 and not states["level"]["small"]
    labels = [r["label"] for r in out["other"]]
    assert labels[:2] == ["First half", "Second half"] and "After the first substitution" in labels
    assert out["end"] > 94 and out["first_goal"][1] == AWAY
    assert len(out["periods"]) == 6 and out["periods"][3]["xg"] == (0.0, 0.5)             # 45-60: Cardiff 0.5
    assert gs.game_state_tables(_events(), pressure, AWAY, HOME)["other"][-1]["label"] == "Second half"   # no sub: 2 rows


def test_charts_and_context_render():
    pressure = pd.DataFrame([dict(eventId=1, squadName=AWAY)])
    ctx = gs.gamestate_context(_events(), pressure, AWAY, HOME, 60.0)
    assert ctx["gamestate_band_img"].startswith("data:image/png")
    assert len(ctx["gamestate_data"]["periods"]) == 6 and set(ctx["gamestate_scales"]) == {"xg", "pressures", "shots"}
    assert set(ctx["gamestate"]) == {"states", "other", "end", "first_goal"} and "periods" in ctx["gamestate_data"]



def test_periods_carry_the_score_state_and_the_goals_of_their_block():
    pressure = pd.DataFrame(columns=["eventId", "squadName"])
    data = gs.game_state_tables(_events(), pressure, AWAY, HOME)
    periods = {p["label"]: p for p in data["periods"]}
    assert periods["0–15'"]["state_label"] == "Level" and periods["0–15'"]["goals"] == []
    assert periods["15–30'"]["state_label"] == "Leading by 1" and periods["15–30'"]["goals"] == ["Campbell 20'"]
    assert periods["45–60'"]["state_label"] == "Level" and periods["45–60'"]["goals"] == ["Moylan 50'"]
    assert periods["75–90'"]["state_label"] == "Trailing by 1"      # the own goal at 70' counts for Cardiff
    assert gs.state_text("trailing", 2) == "Trailing by 2" and gs.state_text("level", 0) == "Level"

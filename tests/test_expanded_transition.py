import pandas as pd

from src.report.expanded import transition as tr

A, B = "Alpha", "Beta"


def _e(t, squad, player="P Q", period=1, **kw):
    base = dict(periodId=period, gameTimeInSec=float(t), squadName=squad, playerName=player, BALL_LOSS_NUMBER=0.0,
                BALL_WIN_NUMBER=0.0, SHOT_AT_GOAL_NUMBER=0.0, SHOT_XG=0.0, startAdjCoordinatesX=-30.0,
                startAdjCoordinatesY=0.0, startPackingZone="CBC")
    return {**base, **kw}


def _events():
    return pd.DataFrame([
        _e(10, A, "A One", BALL_LOSS_NUMBER=1.0),                              # loss, won back after 4 s (counter-press)
        _e(14, A, "A Two", BALL_WIN_NUMBER=1.0),
        _e(30, A, "A One", BALL_LOSS_NUMBER=1.0, startPackingZone="DMC", startAdjCoordinatesX=0.0),
        _e(33, B, "B One", SHOT_AT_GOAL_NUMBER=1.0, SHOT_XG=0.3),              # shot 3 s after the loss, no A touch between
        _e(60, A, "A One", BALL_LOSS_NUMBER=1.0),                              # never won back; B touches, A touches, B shoots
        _e(62, B, "B One"),
        _e(64, A, "A One"),
        _e(66, B, "B One", SHOT_AT_GOAL_NUMBER=1.0, SHOT_XG=0.5),              # A had the ball in between: not caused by the loss
        _e(80, B, "B Two", BALL_WIN_NUMBER=1.0),                               # B regain, shot 6 s later
        _e(86, B, "B One", SHOT_AT_GOAL_NUMBER=1.0, SHOT_XG=0.2),
    ])


def test_losses_record_speed_zone_and_what_the_opponent_got():
    frame = tr.losses(_events(), A, B)
    assert frame.loc[0, "regain_s"] == 4.0 and frame["regain_s"].iloc[1:].isna().all()
    assert frame.loc[0, "regainer"] == "Two" and frame.loc[0, "xg"] == 0
    assert frame.loc[1, "zone"] == "DM" and frame.loc[1, "xg"] == 0.3 and frame.loc[1, "shots"] == 1
    assert frame.loc[2, "xg"] == 0.0                                         # A touched the ball again before the shot


def test_regain_speed_buckets_and_counterpress():
    speed = tr.regain_speed(tr.losses(_events(), A, B))
    assert speed["n"] == 3 and speed["counterpress_n"] == 1
    assert {b["label"]: b["n"] for b in speed["buckets"]}["3–5 s"] == 1
    assert {b["label"]: b["n"] for b in speed["buckets"]}["not won back"] == 2
    assert tr.counterpress_players(tr.losses(_events(), A, B)) == [{"name": "Two", "n": 1}]


def test_punished_orders_costliest_losses_and_groups_by_zone_and_third():
    out = tr.punished(tr.losses(_events(), A, B))
    assert out["xg"] == 0.3 and out["shots"] == 1 and out["costliest"][0]["zone"] == "DM"
    assert out["xg_by_zone"]["DM"] == 0.3 and out["by_third"][0]["losses"] == 2     # two losses in the defensive third


def test_attacking_counts_regains_that_became_shots():
    out = tr.attacking(tr.regains(_events(), B, A))
    assert out["n"] == 1 and out["with_shot"] == 1 and out["xg"] == 0.2 and out["median_first_shot_s"] == 6.0
    assert out["starters"] == [{"name": "Two", "n": 1}]


def test_empty_events_do_not_break_the_summaries():
    empty = tr.losses(_events().iloc[0:0], A, B)
    assert tr.regain_speed(empty)["median_s"] is None and tr.punished(empty)["xg"] == 0
    assert tr.attacking(tr.regains(_events().iloc[0:0], A, B))["n"] == 0


def test_losers_counts_players_whose_losses_were_followed_by_a_shot():
    frame = tr.losses(_events(), A, B)
    assert tr.losers(frame) == [{"name": "One", "n": 1}]

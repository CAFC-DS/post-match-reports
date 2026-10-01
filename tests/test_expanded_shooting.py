import pandas as pd

from src.report.expanded import shooting

CHA, OPP = "Charlton Athletic", "Cardiff City"


def _shots(rows):
    base = dict(squadName=CHA, playerName="Some Player", actionType="SHOT", action="MID_RANGE_SHOT", result="FAIL",
                gameTime="12:00", SHOT_AT_GOAL_NUMBER=1.0, SHOT_AT_GOAL_NUMBER_SUCCESS=0.0,
                SHOT_AT_GOAL_NUMBER_BLOCKED=0.0, SHOT_AT_GOAL_NUMBER_ON_TARGET=0.0, SHOT_AT_GOAL_NUMBER_OTHER=0.0,
                SHOT_XG=0.1, POSTSHOT_XG=0.0, targetY=0.0, targetZ=0.5, woodwork=None)
    return pd.DataFrame([{**base, **r} for r in rows])


def test_placed_shots_drop_blocked_shots_and_shots_without_a_target_point():
    events = _shots([
        dict(SHOT_AT_GOAL_NUMBER_ON_TARGET=1.0),
        dict(SHOT_AT_GOAL_NUMBER_BLOCKED=1.0, targetY=None, targetZ=None),
        dict(targetY=None, targetZ=None),                                  # off target with no target point
        dict(SHOT_AT_GOAL_NUMBER_OTHER=1.0, targetY=5.0, targetZ=1.0),     # folded into off target
        dict(squadName=OPP, SHOT_AT_GOAL_NUMBER_ON_TARGET=1.0),
    ])
    out = shooting.placed_shots(events, CHA)
    assert list(out["category"]) == ["On target", "Off target"]
    assert shooting.placed_shots(events.drop(columns=["targetY", "targetZ"]), CHA).empty


def test_placement_summary_counts_post_shot_xg_and_lists_on_target_and_woodwork():
    events = _shots([
        dict(SHOT_AT_GOAL_NUMBER_SUCCESS=1.0, result="SUCCESS", SHOT_XG=0.24, POSTSHOT_XG=0.6, playerName="A Campbell",
             gameTime="28:10"),
        dict(SHOT_AT_GOAL_NUMBER_ON_TARGET=1.0, SHOT_XG=0.3, POSTSHOT_XG=0.2, playerName="B Kelman", gameTime="70:00"),
        dict(woodwork="RIGHT_POST", targetY=-3.7, targetZ=1.0, SHOT_XG=0.1, playerName="C Grant"),
        dict(targetY=6.0, targetZ=3.0, playerName="D Wide"),                # off target: counted, not listed
    ])
    out = shooting.placement_summary(events, CHA)
    assert (out["placed"], out["on_target"], out["goals"], out["woodwork"]) == (4, 2, 1, 1)
    assert abs(out["xgot"] - 0.8) < 1e-9
    assert [r["player"] for r in out["rows"]] == ["Campbell", "Kelman", "Grant"]       # by xGOT, woodwork last
    assert [r["result"] for r in out["rows"]] == ["Goal", "Saved", "Post"]
    assert out["rows"][0]["minute"] == "28'" and out["rows"][0]["type"] == "Mid range"


def test_charts_and_context_render_for_both_teams_even_without_shots():
    events = _shots([dict(SHOT_AT_GOAL_NUMBER_ON_TARGET=1.0, targetY=3.9, targetZ=4.0), dict(squadName=OPP)])
    ctx = shooting.shooting_context(events, CHA, OPP, {CHA: "#d01012", OPP: "#7d7869"})
    assert set(ctx["placement_img"]) == set(ctx["placement_ctx"]) == {CHA, OPP}
    assert all(v.startswith("data:image/png") for v in ctx["placement_img"].values())
    assert ctx["placement_ctx"][OPP]["xgot"] == "0.00"
    assert shooting.shot_placement_chart(shooting.placed_shots(events.iloc[0:0], CHA), "#d01012").startswith("data:image")

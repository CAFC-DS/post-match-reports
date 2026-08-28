import pandas as pd

from src.report.expanded.working import _post_duel_control


def _event(event_id, number, seconds, team, action_type, action, result=None, period=1):
    return {
        "eventId": event_id,
        "eventNumber": number,
        "periodId": period,
        "gameTimeInSec": seconds,
        "squadName": team,
        "actionType": action_type,
        "action": action,
        "result": result,
    }


def _participants(event_id, winner="Team A", loser="Team B"):
    return [
        {"eventId": event_id, "duel_type": "AERIAL", "squadName": winner,
         "playerName": f"{winner} Player", "outcome": "WON"},
        {"eventId": event_id, "duel_type": "AERIAL", "squadName": loser,
         "playerName": f"{loser} Player", "outcome": "LOST"},
    ]


def test_post_aerial_control_resolves_success_recovery_shot_and_unknown():
    events = pd.DataFrame([
        _event(100, 1, 0.0, "Team A", "RECEPTION", "HEADER"),
        _event(101, 2, 0.1, "Team A", "PASS", "HEADER", "SUCCESS"),
        _event(200, 10, 10.0, "Team A", "RECEPTION", "HEADER"),
        _event(201, 11, 10.1, "Team A", "PASS", "HEADER", "NEUTRAL"),
        _event(202, 12, 12.0, "Team B", "LOOSE_BALL_REGAIN", "LOOSE_BALL_REGAIN"),
        _event(300, 20, 20.0, "Team A", "RECEPTION", "HEADER"),
        _event(301, 21, 20.1, "Team A", "SHOT", "HEADER", "SUCCESS"),
        _event(400, 30, 30.0, "Team A", "RECEPTION", "HEADER"),
        _event(401, 31, 30.1, "Team A", "PASS", "HEADER", "FAIL"),
        _event(402, 32, 36.0, "Team B", "LOOSE_BALL_REGAIN", "LOOSE_BALL_REGAIN"),
    ])
    duels = pd.DataFrame(sum((_participants(event_id) for event_id in (100, 200, 300, 400)), []))

    result = _post_duel_control(events, duels, "AERIAL", window_s=5.0)

    for event_id, control_team in ((100, "Team A"), (200, "Team B"), (300, "Team A")):
        contest = result.loc[result["eventId"] == event_id]
        assert contest["control_resolved"].all()
        assert set(contest["control_team"]) == {control_team}
        assert bool(contest.loc[contest["squadName"] == control_team, "team_controlled"].iloc[0])
        assert not bool(contest.loc[contest["squadName"] != control_team, "team_controlled"].iloc[0])

    unresolved = result.loc[result["eventId"] == 400]
    assert not unresolved["control_resolved"].any()
    assert unresolved["control_team"].isna().all()
    assert unresolved["team_controlled"].isna().all()


def test_post_aerial_control_never_crosses_period_boundary():
    events = pd.DataFrame([
        _event(500, 40, 44.0, "Team A", "RECEPTION", "HEADER", period=1),
        _event(501, 41, 44.1, "Team A", "PASS", "HEADER", "NEUTRAL", period=1),
        _event(502, 42, 0.5, "Team B", "LOOSE_BALL_REGAIN", "LOOSE_BALL_REGAIN", period=2),
    ])

    result = _post_duel_control(events, pd.DataFrame(_participants(500)), "AERIAL")

    assert not result["control_resolved"].any()


def test_post_duel_control_supports_ground_duels():
    events = pd.DataFrame([
        _event(600, 50, 50.0, "Team A", "GROUND_DUEL", "DUEL"),
        _event(601, 51, 50.1, "Team A", "DRIBBLE", "DRIBBLE", "SUCCESS"),
    ])
    participants = pd.DataFrame(_participants(600)).assign(duel_type="GROUND")

    result = _post_duel_control(events, participants, "GROUND")

    assert result["control_resolved"].all()
    assert set(result["control_team"]) == {"Team A"}

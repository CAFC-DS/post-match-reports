from unittest.mock import patch

import pandas as pd

from src.report import metrics_combined


class _FakeDvmsMatch:
    """Stands in for metrics_dvms.DvmsMatch: combined_team_stats only calls
    team_name_of() on it directly, and metrics_dvms.team_stat_values() is
    monkeypatched below, so nothing else needs to be real."""

    def team_name_of(self, side: str) -> str:
        return {"home": "Charlton Athletic", "away": "Swansea City"}[side]


def _minimal_impect_events() -> pd.DataFrame:
    """One row per team with the exact columns metrics.team_stats reads."""
    return pd.DataFrame([
        {
            "squadName": "Charlton Athletic", "SUCCESSFUL_PASSES": 40, "UNSUCCESSFUL_PASSES": 10,
            "endAdjCoordinatesX": 5.0, "startAdjCoordinatesX": 0.0, "BALL_WIN_NUMBER": 3,
            "action": "PASS", "SHOT_XG": 0.3, "phase": "IN_POSSESSION",
            "startPitchPosition": "MIDFIELD", "OFFENSIVE_TOUCHES": 2,
            "WON_GROUND_DUELS": 4, "WON_AERIAL_DUELS": 2, "SECOND_BALL_WIN": 1,
            "SHOT_AT_GOAL_NUMBER": 1, "SHOT_AT_GOAL_NUMBER_ON_TARGET": 1,
            "PACKING_XG": 0.1, "POSTSHOT_XG": 0.25,
            "homeSquadName": "Charlton Athletic", "awaySquadName": "Swansea City",
            "matchId": 123, "dateTime": "2024-01-15 15:00:00",
            "competitionName": "Championship", "season": "2023/24",
        },
        {
            "squadName": "Swansea City", "SUCCESSFUL_PASSES": 30, "UNSUCCESSFUL_PASSES": 15,
            "endAdjCoordinatesX": 3.0, "startAdjCoordinatesX": 0.0, "BALL_WIN_NUMBER": 5,
            "action": "PASS", "SHOT_XG": 0.5, "phase": "SET_PIECE",
            "startPitchPosition": "OPPONENT_BOX", "OFFENSIVE_TOUCHES": 1,
            "WON_GROUND_DUELS": 6, "WON_AERIAL_DUELS": 3, "SECOND_BALL_WIN": 2,
            "SHOT_AT_GOAL_NUMBER": 2, "SHOT_AT_GOAL_NUMBER_ON_TARGET": 1,
            "PACKING_XG": 0.2, "POSTSHOT_XG": 0.45,
            "homeSquadName": "Charlton Athletic", "awaySquadName": "Swansea City",
            "matchId": 123, "dateTime": "2024-01-15 15:00:00",
            "competitionName": "Championship", "season": "2023/24",
        },
    ])


def test_combined_team_stats_overrides_possession_with_dvms_tracked_value():
    events = _minimal_impect_events()
    dvms_match = _FakeDvmsMatch()

    with patch.object(metrics_combined.metrics_dvms, "team_stat_values") as mocked:
        mocked.side_effect = lambda match, side: {
            "home": {"possession_pct": 61.5},
            "away": {"possession_pct": 38.5},
        }[side]
        combined = metrics_combined.combined_team_stats(events, dvms_match)

    assert combined.loc["Charlton Athletic", "possession_pct"] == 61.5
    assert combined.loc["Swansea City", "possession_pct"] == 38.5
    # Every other Impect-sourced column is untouched.
    assert combined.loc["Charlton Athletic", "successful_passes"] == 40
    assert combined.loc["Swansea City", "won_aerial_duels"] == 3
    # Verify no phantom rows were created (index should be exactly these two teams).
    assert len(combined) == 2
    assert list(combined.index) == ["Charlton Athletic", "Swansea City"]

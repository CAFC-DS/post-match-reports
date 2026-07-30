from unittest.mock import patch

import pandas as pd
import pytest

from src.report import metrics_combined


class _FakeDvmsMatch:
    """Stands in for metrics_dvms.DvmsMatch: combined_team_stats only calls
    team_name_of() on it directly, and metrics_dvms.team_stat_values() is
    monkeypatched below, so nothing else needs to be real."""

    def team_name_of(self, side: str) -> str:
        # Deliberately different strings than the Impect fixture uses below
        # ("Charlton Athletic" / "Swansea City"): if combined_team_stats were
        # reverted to indexing by team_name_of() instead of Impect's own
        # home/away names, this test must fail, not silently pass.
        return {"home": "Charlton Athletic FC", "away": "Swansea City AFC"}[side]


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


class _FakeDvmsMatchForBreaks:
    def __init__(self):
        self.events = pd.DataFrame()   # unused: line_breaking_passes is mocked below
        self.frames = pd.DataFrame()
        self.meta = object()

    def team_id_of(self, side: str) -> str:
        return {"home": "H1", "away": "A1"}[side]

    class _F7:
        lineups = pd.DataFrame()

    f7 = _F7()


def test_line_break_style_split_percentages():
    match = _FakeDvmsMatchForBreaks()
    breaks = pd.DataFrame([
        {"event_id": 1, "style": "through"},
        {"event_id": 1, "style": "over"},   # same pass breaking a 2nd line — dedup keeps first row
        {"event_id": 2, "style": "over"},
        {"event_id": 3, "style": "around"},
        {"event_id": 4, "style": "through"},
    ])

    with patch.object(metrics_combined, "line_breaking_passes", return_value=breaks) as mocked:
        result = metrics_combined.line_break_style_split(match, "home")

    mocked.assert_called_once_with(
        events=match.events, tracking=match.frames, pitch_meta=match.meta,
        lineups=match.f7.lineups, team_id="H1", opponent_team_id="A1",
        opponent_is_home=False,
    )
    assert result["n"] == 4  # 5 event_ids, deduped to 4 unique
    assert result["through"] == pytest.approx(50.0)
    assert result["over"] == pytest.approx(25.0)
    assert result["around"] == pytest.approx(25.0)


def test_line_break_style_split_handles_no_breaks():
    match = _FakeDvmsMatchForBreaks()
    with patch.object(metrics_combined, "line_breaking_passes", return_value=pd.DataFrame()):
        result = metrics_combined.line_break_style_split(match, "away")
    assert result == {"through": 0.0, "over": 0.0, "around": 0.0, "n": 0}


class _FakeMatchMeta:
    home_team = "Charlton Athletic"
    away_team = "Swansea City"


class _FakeDvmsMatchForContributions:
    """Stands in for metrics_dvms.DvmsMatch: blended_player_contributions only
    calls side_of() on it directly (metrics_dvms.player_contributions_dvms is
    monkeypatched below), so nothing else needs to be real."""

    def side_of(self, team_id) -> str:
        return {"home": "home", "away": "away"}[team_id]


def test_blended_player_contributions_ranks_by_composite_and_keeps_impect_columns():
    impect_df = pd.DataFrame([
        {"playerName": "Alfie May", "squadName": "Charlton Athletic", "surname": "May",
         "passes": 20, "ground": 2, "aerial": 5, "ball_wins": 1, "shots": 3, "xg": 0.9, "xt": 0.30},
        {"playerName": "Terrell Egbri", "squadName": "Charlton Athletic", "surname": "Egbri",
         "passes": 60, "ground": 4, "aerial": 0, "ball_wins": 3, "shots": 0, "xg": 0.0, "xt": 0.05},
    ])
    dvms_df = pd.DataFrame([
        {"name": "May", "team_id": "home", "distance": 9500.0, "top_speed": 31.2},
        {"name": "Egbri", "team_id": "home", "distance": 11200.0, "top_speed": 28.4},
    ])

    with patch.object(metrics_combined.impect_metrics, "player_contributions", return_value=impect_df), \
         patch.object(metrics_combined.metrics_dvms, "player_contributions_dvms", return_value=dvms_df), \
         patch.object(metrics_combined.impect_metrics, "match_meta", return_value=_FakeMatchMeta()):
        result = metrics_combined.blended_player_contributions(
            pd.DataFrame(), _FakeDvmsMatchForContributions(), top_n=10
        )

    assert list(result.columns[:9]) == [
        "playerName", "squadName", "surname", "passes", "ground", "aerial", "ball_wins", "shots", "xg",
    ] or set(["playerName", "squadName", "surname", "passes", "ground", "aerial", "ball_wins", "shots", "xg", "xt", "composite"]) <= set(result.columns)
    assert "composite" in result.columns
    assert len(result) == 2
    # composite is descending
    assert result.iloc[0]["composite"] >= result.iloc[1]["composite"]
    # physical data attached to the right players
    may_row = result[result["surname"] == "May"].iloc[0]
    assert may_row["distance"] == 9500.0


def test_blended_player_contributions_handles_unmatched_dvms_player():
    impect_df = pd.DataFrame([
        {"playerName": "Alfie May", "squadName": "Charlton Athletic", "surname": "May",
         "passes": 20, "ground": 2, "aerial": 5, "ball_wins": 1, "shots": 3, "xg": 0.9, "xt": 0.30},
    ])
    dvms_df = pd.DataFrame(columns=["name", "team_id", "distance", "top_speed"])  # no physical match at all

    with patch.object(metrics_combined.impect_metrics, "player_contributions", return_value=impect_df), \
         patch.object(metrics_combined.metrics_dvms, "player_contributions_dvms", return_value=dvms_df), \
         patch.object(metrics_combined.impect_metrics, "match_meta", return_value=_FakeMatchMeta()):
        result = metrics_combined.blended_player_contributions(
            pd.DataFrame(), _FakeDvmsMatchForContributions(), top_n=10
        )

    assert len(result) == 1
    assert result.iloc[0]["composite"] == 0.0  # only component with any signal (xt) has zero std across n=1


def test_blended_player_contributions_does_not_dupe_cross_squad_surname_collision():
    """Regression test for the cross-squad surname collision bug: two players
    named "Smith", one per team, must not fan out into duplicate rows, and
    each must get their OWN team's physical data — never the opponent's."""
    impect_df = pd.DataFrame([
        {"playerName": "John Smith", "squadName": "Charlton Athletic", "surname": "Smith",
         "passes": 20, "ground": 2, "aerial": 5, "ball_wins": 1, "shots": 3, "xg": 0.9, "xt": 0.30},
        {"playerName": "Dave Smith", "squadName": "Swansea City", "surname": "Smith",
         "passes": 10, "ground": 1, "aerial": 2, "ball_wins": 2, "shots": 1, "xg": 0.1, "xt": 0.10},
    ])
    dvms_df = pd.DataFrame([
        {"name": "Smith", "team_id": "home", "distance": 9500.0, "top_speed": 31.2},
        {"name": "Smith", "team_id": "away", "distance": 12000.0, "top_speed": 33.5},
    ])

    with patch.object(metrics_combined.impect_metrics, "player_contributions", return_value=impect_df), \
         patch.object(metrics_combined.metrics_dvms, "player_contributions_dvms", return_value=dvms_df), \
         patch.object(metrics_combined.impect_metrics, "match_meta", return_value=_FakeMatchMeta()):
        result = metrics_combined.blended_player_contributions(
            pd.DataFrame(), _FakeDvmsMatchForContributions(), top_n=10
        )

    # No duplicate rows: still exactly one row per Impect player.
    assert len(result) == 2

    charlton_smith = result[result["squadName"] == "Charlton Athletic"].iloc[0]
    swansea_smith = result[result["squadName"] == "Swansea City"].iloc[0]

    # Each Smith gets their OWN team's physical data, not the other's.
    assert charlton_smith["distance"] == 9500.0
    assert charlton_smith["top_speed"] == 31.2
    assert swansea_smith["distance"] == 12000.0
    assert swansea_smith["top_speed"] == 33.5

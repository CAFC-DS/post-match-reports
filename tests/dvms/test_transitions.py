"""Tests for the transitions.py POC — episode grouping over phases.py's
transition windows, plus per-episode distance/final-third/shot summaries.

Uses synthetic phases/tracking/events throughout (no full tracking file is
available in this environment to exercise a real match end to end); the
grouping and join logic is fully unit-testable against manufactured frames.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.dvms.metrics.transitions import (
    SHOT_JOIN_BUFFER_SECONDS,
    transition_episodes,
    transition_quality,
    transition_summary,
)


@dataclass
class FakePitchMeta:
    pitch_length: float = 100.0
    pitch_width: float = 64.0
    home_team_id: str = "H"
    away_team_id: str = "A"


def _phase_row(period, frame_idx, game_clock, phase, ball_x_att=0.0):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "phase": phase, "build_up": False, "ball_x_att": ball_x_att,
    }


class TestTransitionEpisodes:
    def test_two_separate_runs_become_two_episodes(self):
        phases = pd.DataFrame([
            _phase_row(1, 0, 0.0, "transition_to_attack"),
            _phase_row(1, 1, 1.0, "transition_to_attack"),
            _phase_row(1, 2, 2.0, "in_possession"),
            _phase_row(1, 3, 3.0, "transition_to_attack"),
            _phase_row(1, 4, 4.0, "transition_to_attack"),
        ])
        out = transition_episodes(phases, "transition_to_attack")
        assert len(out) == 2
        assert out.iloc[0]["start_frame_idx"] == 0
        assert out.iloc[0]["end_frame_idx"] == 1
        assert out.iloc[0]["duration_s"] == pytest.approx(1.0)
        assert out.iloc[1]["start_frame_idx"] == 3
        assert out.iloc[1]["end_frame_idx"] == 4

    def test_period_change_never_merges_into_one_episode(self):
        phases = pd.DataFrame([
            _phase_row(1, 40, 40.0, "transition_to_defend"),
            _phase_row(1, 41, 41.0, "transition_to_defend"),
            _phase_row(2, 0, 0.0, "transition_to_defend"),
            _phase_row(2, 1, 1.0, "transition_to_defend"),
        ])
        out = transition_episodes(phases, "transition_to_defend")
        assert len(out) == 2
        assert set(out["period"]) == {1, 2}

    def test_other_phase_frames_are_ignored(self):
        phases = pd.DataFrame([
            _phase_row(1, 0, 0.0, "in_possession"),
            _phase_row(1, 1, 1.0, "out_of_possession"),
        ])
        out = transition_episodes(phases, "transition_to_attack")
        assert out.empty

    def test_empty_input(self):
        cols = ["period", "frame_idx", "game_clock", "phase", "build_up", "ball_x_att"]
        out = transition_episodes(pd.DataFrame(columns=cols), "transition_to_attack")
        assert out.empty


def _tracking_row(period, frame_idx, game_clock, opta_id, speed):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": True, "last_touch": "home", "team": "home", "opta_id": opta_id,
        "number": None, "x": 0.0, "y": 0.0, "z": 0.0, "speed": speed,
    }


def _shot_event(event_id, minute, second, team_id="H"):
    return {
        "event_id": event_id, "type_id": 16, "period_id": 1,
        "minute": minute, "second": second, "team_id": team_id,
        "is_shot": True, "is_pass": False,
    }


class TestTransitionQuality:
    def _phases_with_one_episode(self, end_ball_x_att):
        return pd.DataFrame([
            _phase_row(1, 0, 100.0, "transition_to_attack", ball_x_att=10.0),
            _phase_row(1, 1, 101.0, "transition_to_attack", ball_x_att=end_ball_x_att),
        ])

    def test_reached_final_third_when_ball_crosses_threshold(self):
        # pitch_length=100 -> final third boundary at x=100/6≈16.67.
        phases = self._phases_with_one_episode(end_ball_x_att=20.0)
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 5.0),
            _tracking_row(1, 1, 101.0, "p1", 5.0),
        ])
        events = pd.DataFrame(columns=["event_id", "type_id", "period_id",
                                       "minute", "second", "team_id",
                                       "is_shot", "is_pass"])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert bool(out.iloc[0]["reached_final_third"]) is True

    def test_does_not_reach_final_third_below_threshold(self):
        phases = self._phases_with_one_episode(end_ball_x_att=5.0)
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 5.0),
            _tracking_row(1, 1, 101.0, "p1", 5.0),
        ])
        events = pd.DataFrame(columns=["event_id", "type_id", "period_id",
                                       "minute", "second", "team_id",
                                       "is_shot", "is_pass"])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert bool(out.iloc[0]["reached_final_third"]) is False

    def test_distance_covered_uses_inferred_dt(self):
        phases = self._phases_with_one_episode(end_ball_x_att=5.0)
        # dt inferred from phases' game_clock spacing = 1.0s; one player at
        # constant 4 m/s over 2 frames -> 4m/frame * 2 frames = 8m.
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 4.0),
            _tracking_row(1, 1, 101.0, "p1", 4.0),
        ])
        events = pd.DataFrame(columns=["event_id", "type_id", "period_id",
                                       "minute", "second", "team_id",
                                       "is_shot", "is_pass"])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert out.iloc[0]["distance_covered_m"] == pytest.approx(8.0)

    def test_shot_within_buffer_after_episode_counts(self):
        phases = self._phases_with_one_episode(end_ball_x_att=5.0)
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 1.0),
            _tracking_row(1, 1, 101.0, "p1", 1.0),
        ])
        # Episode ends at game_clock=101s; a shot at minute=1,second=42 is
        # 102s cumulative -> period-1 clock 102s, i.e. 1s after episode end,
        # inside the SHOT_JOIN_BUFFER_SECONDS=2.0 window.
        events = pd.DataFrame([_shot_event(1, minute=1, second=42, team_id="H")])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert bool(out.iloc[0]["ended_in_shot"]) is True
        assert out.iloc[0]["regain_to_shot_s"] == pytest.approx(2.0)

    def test_shot_beyond_buffer_does_not_count(self):
        phases = self._phases_with_one_episode(end_ball_x_att=5.0)
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 1.0),
            _tracking_row(1, 1, 101.0, "p1", 1.0),
        ])
        # 111s cumulative -> 10s after episode end, well beyond the buffer.
        events = pd.DataFrame([_shot_event(1, minute=1, second=51, team_id="H")])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert bool(out.iloc[0]["ended_in_shot"]) is False
        assert np.isnan(out.iloc[0]["regain_to_shot_s"])

    def test_opponent_shots_are_not_counted(self):
        phases = self._phases_with_one_episode(end_ball_x_att=5.0)
        tracking = pd.DataFrame([
            _tracking_row(1, 0, 100.0, "p1", 1.0),
            _tracking_row(1, 1, 101.0, "p1", 1.0),
        ])
        events = pd.DataFrame([_shot_event(1, minute=1, second=42, team_id="A")])
        out = transition_quality(events, tracking, phases, FakePitchMeta(), "home")
        assert bool(out.iloc[0]["ended_in_shot"]) is False


class TestTransitionSummary:
    def test_rollup_of_multiple_episodes(self):
        quality = pd.DataFrame([
            {"episode_id": 0, "duration_s": 4.0, "distance_covered_m": 10.0,
             "reached_final_third": True, "ended_in_shot": True,
             "regain_to_shot_s": 1.5},
            {"episode_id": 1, "duration_s": 6.0, "distance_covered_m": 20.0,
             "reached_final_third": False, "ended_in_shot": False,
             "regain_to_shot_s": np.nan},
        ])
        out = transition_summary(quality)
        assert out["n_episodes"] == 2
        assert out["median_duration_s"] == pytest.approx(5.0)
        assert out["pct_reaching_final_third"] == pytest.approx(50.0)
        assert out["pct_ending_in_shot"] == pytest.approx(50.0)
        assert out["median_distance_m"] == pytest.approx(15.0)

    def test_empty_input(self):
        out = transition_summary(pd.DataFrame())
        assert out["n_episodes"] == 0
        assert np.isnan(out["median_duration_s"])

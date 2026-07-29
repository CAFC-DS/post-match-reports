"""Tests for avg_positions.average_positions — tracked (not touch-based) mean
positions per player per phase, previously with zero dedicated coverage."""

from __future__ import annotations

import pandas as pd
import pytest

from src.dvms.metrics.avg_positions import average_positions


def _player_row(period, frame_idx, game_clock, opta_id, x, y):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": True, "last_touch": "home", "team": "home", "opta_id": opta_id,
        "number": None, "x": x, "y": y, "z": 0.0, "speed": 0.0,
    }


class TestAveragePositions:
    def _fixture(self, pitch_meta):
        # Player "p1" sits at two known points across two frames one second
        # apart -> mean position and dt/minutes are both hand-checkable.
        rows = [
            _player_row(1, 0, 0.0, "p1", -10.0, -5.0),
            _player_row(1, 1, 1.0, "p1", 10.0, 5.0),
        ]
        tracking = pd.DataFrame(rows)
        phases = pd.DataFrame([
            {"period": 1, "frame_idx": 0, "game_clock": 0.0,
             "phase": "in_possession", "build_up": True},
            {"period": 1, "frame_idx": 1, "game_clock": 1.0,
             "phase": "in_possession", "build_up": False},
        ])
        return tracking, phases

    def test_mean_position_and_frame_count(self, pitch_meta):
        tracking, phases = self._fixture(pitch_meta)
        out = average_positions(tracking, phases, pitch_meta, "home")
        in_poss = out[out["phase"] == "in_possession"].iloc[0]
        assert in_poss["x"] == pytest.approx(0.0)
        assert in_poss["y"] == pytest.approx(0.0)
        assert in_poss["n_frames"] == 2

    def test_minutes_scales_with_inferred_dt(self, pitch_meta):
        tracking, phases = self._fixture(pitch_meta)
        out = average_positions(tracking, phases, pitch_meta, "home")
        dt = float(phases["game_clock"].diff().median())
        in_poss = out[out["phase"] == "in_possession"].iloc[0]
        assert in_poss["minutes"] == pytest.approx(in_poss["n_frames"] * dt / 60.0)

    def test_build_up_is_separate_row_from_single_frame(self, pitch_meta):
        tracking, phases = self._fixture(pitch_meta)
        out = average_positions(tracking, phases, pitch_meta, "home")
        bu = out[out["phase"] == "build_up"].iloc[0]
        assert bu["n_frames"] == 1
        assert bu["x"] == pytest.approx(-10.0)
        assert bu["y"] == pytest.approx(-5.0)

    def test_positions_within_pitch_bounds(self, pitch_meta):
        tracking, phases = self._fixture(pitch_meta)
        out = average_positions(tracking, phases, pitch_meta, "home")
        half_len = pitch_meta.pitch_length / 2.0
        half_wid = pitch_meta.pitch_width / 2.0
        assert (out["x"].abs() <= half_len).all()
        assert (out["y"].abs() <= half_wid).all()

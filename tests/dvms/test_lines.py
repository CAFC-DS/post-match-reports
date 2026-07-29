"""Tests for lines.py — unit assignment, team shape timeseries and the
convex-hull compactness area, none of which had dedicated coverage despite
being live in the sample pack."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.dvms.metrics.lines import (
    _hull_area,
    summarize_by_phase,
    team_shape_timeseries,
    unit_map,
)


class TestUnitMap:
    def test_unit_map_from_real_lineups(self, f7):
        units = unit_map(f7.lineups)
        # Every mapped id lands on one of the four known units.
        assert set(units.values()) <= {"goalkeeper", "defence", "midfield", "attack"}
        # Starters use `position`; subs use `sub_position` when set — every
        # named player in the sample lineup has one or the other.
        assert len(units) == len(f7.lineups)

    def test_substitute_uses_sub_position_not_placeholder(self, f7):
        subs = f7.lineups[f7.lineups["status"] == "Sub"]
        units = unit_map(f7.lineups)
        for _, r in subs.iterrows():
            # "Substitute" itself is not a real unit — the sub_position must
            # have been consulted, not the placeholder `position` column.
            assert units[str(r["player_id"])] != "Substitute"


class TestHullArea:
    def test_unit_square(self):
        xs = np.array([0.0, 1.0, 1.0, 0.0])
        ys = np.array([0.0, 0.0, 1.0, 1.0])
        assert _hull_area(xs, ys) == pytest.approx(1.0)

    def test_right_triangle(self):
        xs = np.array([0.0, 4.0, 0.0])
        ys = np.array([0.0, 0.0, 3.0])
        assert _hull_area(xs, ys) == pytest.approx(6.0)

    def test_collinear_points_have_zero_area(self):
        xs = np.array([0.0, 1.0, 2.0])
        ys = np.array([0.0, 1.0, 2.0])
        assert _hull_area(xs, ys) == pytest.approx(0.0)


def _shape_row(period, frame_idx, game_clock, **metrics):
    row = {"period": period, "frame_idx": frame_idx, "game_clock": game_clock}
    row.update(metrics)
    return row


class TestSummarizeByPhase:
    def test_includes_build_up_row_alongside_canonical_phases(self):
        shape = pd.DataFrame([
            _shape_row(1, 0, 0.0, def_line_m=10.0, mid_line_m=30.0, att_line_m=50.0,
                       depth_m=40.0, width_m=30.0, def_mid_gap_m=20.0,
                       compactness_area_m2=100.0),
            _shape_row(1, 1, 1.0, def_line_m=12.0, mid_line_m=32.0, att_line_m=52.0,
                       depth_m=40.0, width_m=30.0, def_mid_gap_m=20.0,
                       compactness_area_m2=110.0),
        ])
        phases = pd.DataFrame([
            {"period": 1, "frame_idx": 0, "phase": "in_possession", "build_up": True},
            {"period": 1, "frame_idx": 1, "phase": "in_possession", "build_up": False},
        ])
        out = summarize_by_phase(shape, phases)
        assert set(out["phase"]) == {"in_possession", "build_up"}
        bu = out[out["phase"] == "build_up"].iloc[0]
        assert bu["n_frames"] == 1
        assert bu["def_line_m"] == pytest.approx(10.0)


def _player_row(period, frame_idx, game_clock, opta_id, x, y):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": True, "last_touch": "home", "team": "home", "opta_id": opta_id,
        "number": None, "x": x, "y": y, "z": 0.0, "speed": 0.0,
    }


class TestTeamShapeTimeseries:
    def test_line_ordering_and_hull_area_on_a_known_shape(self, pitch_meta):
        # Home attacks +x in period 1 (real sample metadata) -> no flip, so
        # height_m = x + half_len is directly checkable.
        units = {
            "d1": "defence", "d2": "defence",
            "m1": "midfield", "m2": "midfield",
            "a1": "attack", "a2": "attack",
        }
        rows = [
            _player_row(1, 0, 0.0, "d1", -30.0, -10.0),
            _player_row(1, 0, 0.0, "d2", -30.0, 10.0),
            _player_row(1, 0, 0.0, "m1", 0.0, -10.0),
            _player_row(1, 0, 0.0, "m2", 0.0, 10.0),
            _player_row(1, 0, 0.0, "a1", 30.0, -10.0),
            _player_row(1, 0, 0.0, "a2", 30.0, 10.0),
        ]
        tracking = pd.DataFrame(rows)
        out = team_shape_timeseries(tracking, pitch_meta, "home", units)
        assert len(out) == 1
        row = out.iloc[0]
        assert row["def_line_m"] < row["mid_line_m"] < row["att_line_m"]
        half_len = pitch_meta.pitch_length / 2.0
        assert row["def_line_m"] == pytest.approx(-30.0 + half_len)
        assert row["width_m"] == pytest.approx(20.0)
        assert row["depth_m"] == pytest.approx(60.0)
        # Outfield players form a 60x20 rectangle -> hull area 1200.
        assert row["compactness_area_m2"] == pytest.approx(1200.0)

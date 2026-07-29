"""Tests for phases.classify_phases — the frame-level possession/transition
classifier every other tracking-derived metric (lines, avg_positions,
line_breaks, transitions) is built on top of.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.dvms.metrics.phases import PHASES, TRANSITION_SECONDS, classify_phases


def _ball_frame(period, frame_idx, game_clock, live, last_touch, x=0.0):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": live, "last_touch": last_touch, "team": "ball",
        "opta_id": None, "number": None, "x": x, "y": 0.0, "z": 0.0,
        "speed": 0.0,
    }


def _tracking(rows) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestPhaseWindow:
    """The 7-second transition window is the single boundary transitions.py
    will depend on entirely — pin it with a manufactured flip."""

    def _flip_at_10(self):
        rows = []
        # clocks 0..9: home has the ball. Flip to away at clock 10, holds to 20.
        for clock in range(0, 21):
            touch = "home" if clock < 10 else "away"
            rows.append(_ball_frame(1, clock, float(clock), True, touch))
        return _tracking(rows)

    def test_transition_window_is_seven_seconds(self, pitch_meta):
        tracking = self._flip_at_10()
        out = classify_phases(tracking, pitch_meta, "home")
        by_clock = out.set_index("game_clock")["phase"]
        # Settles in_possession once since_flip reaches 7 (clocks 0..6 transition
        # since it's also the start of the data, in_possession from 7..9).
        assert by_clock[6.0] == "transition_to_attack"
        assert by_clock[7.0] == "in_possession"
        assert by_clock[9.0] == "in_possession"
        # Flip at clock=10 resets the window: transition_to_defend 10..16,
        # settled out_of_possession from clock=17.
        assert by_clock[10.0] == "transition_to_defend"
        assert by_clock[16.0] == "transition_to_defend"
        assert by_clock[17.0] == "out_of_possession"

    def test_phases_exhaustive_and_mutually_exclusive(self, pitch_meta):
        tracking = self._flip_at_10()
        out = classify_phases(tracking, pitch_meta, "home")
        assert set(out["phase"].unique()) <= set(PHASES)
        assert out["phase"].notna().all()

    def test_dead_ball_frames_dropped(self, pitch_meta):
        rows = self._flip_at_10().to_dict("records")
        rows.append(_ball_frame(1, 21, 21.0, False, "home"))
        rows.append(_ball_frame(1, 22, 22.0, False, "away"))
        tracking = _tracking(rows)
        out = classify_phases(tracking, pitch_meta, "home")
        assert set(out["frame_idx"]) == set(range(0, 21))

    def test_flip_never_leaks_across_half_time(self, pitch_meta):
        rows = []
        # Period 1 ends mid-transition-window (flip at clock 40, period ends 44).
        for clock in range(38, 45):
            touch = "home" if clock < 40 else "away"
            rows.append(_ball_frame(1, clock, float(clock), True, touch))
        # Period 2 starts with the SAME last_touch ("away") — if the flip
        # leaked across half-time this frame would inherit period 1's
        # since_flip (already large) and read as settled out_of_possession,
        # not a fresh transition.
        rows.append(_ball_frame(2, 0, 0.0, True, "away"))
        rows.append(_ball_frame(2, 1, 1.0, True, "away"))
        tracking = _tracking(rows)
        out = classify_phases(tracking, pitch_meta, "home")
        p2 = out[out["period"] == 2].set_index("frame_idx")["phase"]
        assert p2.loc[0] == "transition_to_defend"

    def test_build_up_is_strict_subset_of_in_possession_own_half(self, pitch_meta):
        rows = []
        # Long settled in_possession stretch, ball crossing the halfway line
        # partway through (period 1, home attacks +x per the real pitch_meta).
        for clock in range(0, 30):
            x = -10.0 if clock < 15 else 10.0
            rows.append(_ball_frame(1, clock, float(clock), True, "home", x=x))
        tracking = _tracking(rows)
        out = classify_phases(tracking, pitch_meta, "home")
        in_poss = out[out["phase"] == "in_possession"]
        assert (out.loc[out["build_up"], "phase"] == "in_possession").all()
        assert set(out[out["build_up"]].index) <= set(in_poss.index)
        assert (out.loc[out["build_up"], "ball_x_att"] < 0).all()
        # In-possession rows in the opponent's half exist and are NOT build_up
        # — build_up is a strict subset, not a synonym for in_possession.
        attacking_half_in_poss = in_poss[in_poss["ball_x_att"] >= 0]
        assert not attacking_half_in_poss.empty
        assert not attacking_half_in_poss["build_up"].any()

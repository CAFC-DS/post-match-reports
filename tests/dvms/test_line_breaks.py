"""Tests for line_breaks.line_breaking_passes / combination_matrix.

Uses synthetic single-frame tracking rather than the real match, since a
full tracking file (needed for nearest_frame_index to find a frame near an
event's clock across 90 minutes) isn't available in this environment — only
the truncated peek. The geometry/classification logic is fully unit-testable
against one manufactured frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd
import pytest

from src.dvms.metrics.line_breaks import combination_matrix, line_breaking_passes


@dataclass
class FakePitchMeta:
    pitch_length: float = 100.0
    pitch_width: float = 64.0
    _att_positive: dict = field(default_factory=lambda: {1: True})

    def home_att_positive(self, period):
        return self._att_positive.get(period)


def _lineups(team_id, positions):
    rows = []
    for i, pos in enumerate(positions):
        rows.append({
            "player_id": f"{team_id}{i}", "team_id": team_id,
            "position": pos, "sub_position": None,
        })
    return pd.DataFrame(rows)


def _ball_row(period, frame_idx, game_clock):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": True, "last_touch": "home", "team": "ball", "opta_id": None,
        "number": None, "x": 0.0, "y": 0.0, "z": 0.0, "speed": 0.0,
    }


def _defender_row(period, frame_idx, game_clock, opta_id, x, y):
    return {
        "period": period, "frame_idx": frame_idx, "game_clock": game_clock,
        "live": True, "last_touch": "home", "team": "away", "opta_id": opta_id,
        "number": None, "x": x, "y": y, "z": 0.0, "speed": 0.0,
    }


def _pass_event(event_id, x, y, end_x, end_y, minute, second, quals=None,
                team_id="H"):
    return {
        "event_id": event_id, "player_id": f"p{event_id}", "team_id": team_id,
        "outcome": 1, "is_pass": True, "x": x, "y": y, "end_x": end_x,
        "end_y": end_y, "qualifiers": quals or {}, "period_id": 1,
        "minute": minute, "second": second,
    }


class TestLineBreakingPasses:
    """Two opponent defenders at metres x=30 (y=-10 and y=10), giving a
    defence-line height of 30 and an occupied width span of roughly [-11, 11]
    (unit_map's own-width padding is +-1m)."""

    def _base(self):
        tracking = pd.DataFrame([
            _ball_row(1, 0, 10.0),
            _defender_row(1, 0, 10.0, "A0", 30.0, -10.0),
            _defender_row(1, 0, 10.0, "A1", 30.0, 10.0),
        ])
        lineups = _lineups("A", ["Defender", "Defender"])
        return tracking, lineups

    def test_through_ball_splits_the_line(self):
        tracking, lineups = self._base()
        # sx=10 (opta x=60), ex=50 (opta x=100), y=0 throughout -> inside the
        # defenders' occupied width, no long-ball/chip qualifier -> "through".
        events = pd.DataFrame([_pass_event(1, 60, 50, 100, 50, 0, 10)])
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert len(out) == 1
        assert out.iloc[0]["style"] == "through"
        assert out.iloc[0]["line"] == "defence"

    def test_long_ball_qualifier_is_over(self):
        tracking, lineups = self._base()
        events = pd.DataFrame([_pass_event(1, 60, 50, 100, 50, 0, 10, quals={1: None})])
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert out.iloc[0]["style"] == "over"

    def test_pass_wide_of_the_block_is_around(self):
        tracking, lineups = self._base()
        # opta y=70 -> metres y=(70-50)/100*64=12.8m, outside the defenders'
        # padded occupied span of [-11, 11]m.
        events = pd.DataFrame([_pass_event(1, 60, 70, 100, 70, 0, 10)])
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert out.iloc[0]["style"] == "around"

    def test_no_break_when_pass_does_not_cross_the_line(self):
        tracking, lineups = self._base()
        # Both start and end are short of the defence line at metres x=30
        # (opta x=60 -> metres 10, opta x=70 -> metres 20; line at 30 uncrossed).
        events = pd.DataFrame([_pass_event(1, 60, 50, 70, 50, 0, 10)])
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert out.empty

    def test_receiver_is_next_same_team_event_within_window(self):
        tracking, lineups = self._base()
        events = pd.DataFrame([
            _pass_event(1, 60, 50, 100, 50, 0, 10, team_id="H"),
            {"event_id": 2, "player_id": "opp1", "team_id": "A", "outcome": 1,
             "is_pass": True, "x": 50.0, "y": 50.0, "end_x": None, "end_y": None,
             "qualifiers": {}, "period_id": 1, "minute": 0, "second": 11},
            {"event_id": 3, "player_id": "receiver", "team_id": "H", "outcome": 1,
             "is_pass": True, "x": 90.0, "y": 50.0, "end_x": None, "end_y": None,
             "qualifiers": {}, "period_id": 1, "minute": 0, "second": 12},
        ])
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert out.iloc[0]["receiver_id"] == "receiver"

    def test_receiver_none_beyond_lookahead_window(self):
        tracking, lineups = self._base()
        rows = [_pass_event(1, 60, 50, 100, 50, 0, 10, team_id="H")]
        # Six opponent events in between push the eventual same-team event
        # past the 5-event lookahead window in line_breaking_passes.
        for i in range(2, 8):
            rows.append({
                "event_id": i, "player_id": f"opp{i}", "team_id": "A",
                "outcome": 1, "is_pass": True, "x": 50.0, "y": 50.0,
                "end_x": None, "end_y": None, "qualifiers": {}, "period_id": 1,
                "minute": 0, "second": 10 + i,
            })
        rows.append({
            "event_id": 8, "player_id": "too_late", "team_id": "H",
            "outcome": 1, "is_pass": True, "x": 90.0, "y": 50.0,
            "end_x": None, "end_y": None, "qualifiers": {}, "period_id": 1,
            "minute": 0, "second": 20,
        })
        events = pd.DataFrame(rows)
        out = line_breaking_passes(events, tracking, FakePitchMeta(), lineups,
                                   team_id="H", opponent_team_id="A",
                                   opponent_is_home=False)
        assert out.iloc[0]["receiver_id"] is None


class TestCombinationMatrix:
    def test_dedupes_a_pass_that_breaks_two_lines(self):
        breaks = pd.DataFrame([
            {"event_id": 1, "player_id": "p1", "receiver_id": "r1", "line": "defence"},
            {"event_id": 1, "player_id": "p1", "receiver_id": "r1", "line": "midfield"},
            {"event_id": 2, "player_id": "p1", "receiver_id": "r1", "line": "defence"},
        ])
        out = combination_matrix(breaks)
        row = out[(out["player_id"] == "p1") & (out["receiver_id"] == "r1")].iloc[0]
        assert row["passes"] == 2

    def test_empty_input_returns_empty(self):
        assert combination_matrix(pd.DataFrame()).empty

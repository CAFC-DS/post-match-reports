"""Coordinate conversion and event-frame clock alignment tests."""

import numpy as np
import pandas as pd
import pytest

from src.dvms.coords import metres_to_opta, normalize_attack_direction, opta_to_metres
from src.dvms.sync import (
    event_game_clock,
    nearest_frame_index,
    period_offset_seconds,
)

L, W = 104.68, 65.42


class TestCoords:
    def test_anchor_points(self):
        # Centre spot.
        assert opta_to_metres(50, 50, L, W) == (0.0, 0.0)
        # Attacked goal line, centre.
        x, y = opta_to_metres(100, 50, L, W)
        assert x == pytest.approx(L / 2)
        assert y == pytest.approx(0.0)
        # Opta y=0 is the attacker's right touchline -> NEGATIVE y (facing +x,
        # the left hand points to +y). Verified against real corner events.
        _, y = opta_to_metres(50, 0, L, W)
        assert y == pytest.approx(-W / 2)

    def test_round_trip(self):
        xs = np.array([0.0, 12.3, 50.0, 99.5])
        ys = np.array([0.5, 21.1, 78.9, 100.0])
        xm, ym = opta_to_metres(xs, ys, L, W)
        xr, yr = metres_to_opta(xm, ym, L, W)
        assert np.allclose(xr, xs)
        assert np.allclose(yr, ys)

    def test_direction_normalisation_rotates_both_axes(self):
        df = pd.DataFrame({"period": [1, 1, 2], "x": [10.0, -5.0, 10.0], "y": [3.0, 8.0, 3.0]})
        # Home attacks positive in P1 -> home rows untouched.
        out = normalize_attack_direction(df, period=1, home_att_positive=True, team_is_home=True)
        assert out.equals(df)
        # Away in the same period must be rotated 180° (both axes), P2 untouched.
        out = normalize_attack_direction(df, period=1, home_att_positive=True, team_is_home=False)
        assert out.loc[0, "x"] == -10.0 and out.loc[0, "y"] == -3.0
        assert out.loc[2, "x"] == 10.0 and out.loc[2, "y"] == 3.0


class TestClock:
    def test_period_offsets(self):
        assert period_offset_seconds(1) == 0
        assert period_offset_seconds(2) == 2700
        assert period_offset_seconds(3) == 5400
        assert period_offset_seconds(4) == 6300
        with pytest.raises(ValueError):
            period_offset_seconds(16)

    def test_event_game_clock_restarts_each_period(self):
        ev = pd.DataFrame({
            "period_id": [1, 1, 2, 2],
            "minute":    [0, 45, 45, 90],   # P1 stoppage overshoots 45'
            "second":    [0, 30, 0, 15],
        })
        clock = event_game_clock(ev)
        assert clock.tolist() == [0.0, 2730.0, 0.0, 2715.0]

    def test_event_game_clock_real_feed(self, f24):
        # Restrict to the real halves: the parser deliberately keeps Opta's
        # pre/post-match pseudo-periods (14/16), whose clocks are undefined.
        ev = f24.events[f24.events["period_id"].isin([1, 2])]
        clock = event_game_clock(ev)
        by_period = clock.groupby(ev["period_id"])
        # Both halves start at (or within seconds of) zero and run ~45min+.
        assert by_period.min().max() < 5
        assert (by_period.max() > 45 * 60).all()

    def test_nearest_frame(self):
        index = {1: np.array([0.0, 0.2, 0.4, 100.0]), 2: np.array([0.0, 50.0])}
        assert nearest_frame_index(0.19, 1, index) == 1
        assert nearest_frame_index(0.31, 1, index) == 2
        assert nearest_frame_index(999.0, 1, index) == 3      # clamps to last
        assert nearest_frame_index(10.0, 3, index) == -1      # unknown period
        out = nearest_frame_index(np.array([0.0, 49.0]), np.array([1, 2]), index)
        assert out.tolist() == [0, 1]


@pytest.mark.integration
def test_validate_sync_full_file(f24, pitch_meta):
    """Ball-position agreement over a full tracking file (env-gated).

    Run with a real tracking file:
        DVMS_TRACKING_FILE=/path/to/match.jsonl.gz pytest -m integration
    """
    import os

    from src.dvms.parsers.tracking import frames_to_long_df, iter_frames
    from src.dvms.sync import validate_sync

    path = os.environ.get("DVMS_TRACKING_FILE")
    if not path:
        pytest.skip("DVMS_TRACKING_FILE not set")

    tracking = frames_to_long_df(iter_frames(path), every_n=5)
    report = validate_sync(f24.events, tracking, pitch_meta)
    summary = report.attrs["summary"]
    assert summary["n"] > 500
    # 3m gate: ~2.5m is the 5Hz sampling floor on a correctly-synced match.
    assert summary["median"] < 3.0, f"sync median ball error {summary['median']:.2f}m"

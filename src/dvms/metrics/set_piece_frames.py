"""Set-piece freeze-frames: where all 22 players stood at the delivery.

The panel event data cannot draw: for each corner (or box free kick), the
tracking frame nearest the delivery gives every player's true position — the
attacking screen positions, the defending block, keeper depth — plus a
line-drop number (how far the defending back line retreated as the ball
came in).

Frame choice: nearest frame by game clock, then refined within ±1.5s to the
frame where the tracked ball sits closest to the event's delivery point —
Opta's minute/second is only whole-second, and 1.5s of 25fps frames is
enough to land on the actual strike of the ball.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..coords import opta_to_metres
from ..sync import event_game_clock, nearest_frame_index
from .lines import unit_map as build_unit_map

REFINE_WINDOW_S = 1.5


def _ball_index(tracking: pd.DataFrame):
    ball = tracking[tracking["team"] == "ball"]
    index, ids, frames = {}, {}, {}
    for p, grp in ball.groupby("period"):
        grp = grp.sort_values("game_clock").reset_index(drop=True)
        index[int(p)] = grp["game_clock"].to_numpy(dtype=float)
        ids[int(p)] = grp["frame_idx"].to_numpy()
        frames[int(p)] = grp
    return index, ids, frames


def delivery_freeze_frame(delivery: pd.Series, events: pd.DataFrame,
                          tracking: pd.DataFrame, pitch_meta) -> pd.DataFrame | None:
    """All tracked entities at the moment one delivery was struck.

    ``delivery`` is a row from ``opta_setpiece_map.corners``/``free_kicks``.
    Returns the tracking rows (players + ball) of the chosen frame, or None
    when the delivery can't be located in the tracking timeline.
    """
    L, W = pitch_meta.pitch_length, pitch_meta.pitch_width
    period = int(delivery["period_id"])
    index, ids, ball_frames = _ball_index(tracking)
    if period not in index:
        return None

    clock = float(delivery["minute"] * 60 + delivery["second"])
    from ..sync import period_offset_seconds
    clock -= period_offset_seconds(period)

    pos = nearest_frame_index(clock, period, index)
    if pos < 0:
        return None

    # Refine within the window: the frame where the ball is nearest the
    # delivery start point is the strike frame.
    grp = ball_frames[period]
    lo = np.searchsorted(index[period], clock - REFINE_WINDOW_S)
    hi = np.searchsorted(index[period], clock + REFINE_WINDOW_S)
    window = grp.iloc[max(lo, 0):hi]
    if not window.empty:
        ex, ey = opta_to_metres(delivery["x"], delivery["y"], L, W)
        hap = pitch_meta.home_att_positive(period)
        # Event coords are in the delivering team's attacking-positive frame;
        # rotate the candidate ball positions into it for the comparison.
        # (Sign resolution mirrors sync.validate_sync.)
        d = np.hypot(window["x"].to_numpy(dtype=float) - ex,
                     window["y"].to_numpy(dtype=float) - ey)
        d_flipped = np.hypot(-window["x"].to_numpy(dtype=float) - ex,
                             -window["y"].to_numpy(dtype=float) - ey)
        best = int(np.argmin(np.minimum(d, d_flipped)))
        frame_idx = window.iloc[best]["frame_idx"]
    else:
        frame_idx = ids[period][pos]

    return tracking[(tracking["period"] == period)
                    & (tracking["frame_idx"] == frame_idx)].copy()


def corner_line_drop(delivery: pd.Series, events: pd.DataFrame,
                     tracking: pd.DataFrame, pitch_meta,
                     lineups: pd.DataFrame, defending_team_id: str,
                     defending_is_home: bool,
                     before_seconds: float = 5.0) -> float | None:
    """Metres the defending back line dropped in the run-up to a corner.

    Median defender height ``before_seconds`` before delivery minus at
    delivery, positive = the line retreated toward its own goal.
    """
    units = build_unit_map(lineups[lineups["team_id"].astype(str) == str(defending_team_id)])
    def_ids = {pid for pid, u in units.items() if u == "defence"}
    side = "home" if defending_is_home else "away"
    half_len = pitch_meta.pitch_length / 2.0

    frame_now = delivery_freeze_frame(delivery, events, tracking, pitch_meta)
    if frame_now is None:
        return None
    before = delivery.copy()
    total = delivery["minute"] * 60 + delivery["second"] - before_seconds
    before["minute"], before["second"] = int(total // 60), int(total % 60)
    frame_before = delivery_freeze_frame(before, events, tracking, pitch_meta)
    if frame_before is None:
        return None

    def _line_height(frame: pd.DataFrame) -> float | None:
        rows = frame[(frame["team"] == side) & frame["opta_id"].isin(def_ids)]
        if len(rows) < 2:
            return None
        hap = pitch_meta.home_att_positive(int(delivery["period_id"]))
        attacks_positive = hap if defending_is_home else not hap
        x = rows["x"].astype(float)
        if not attacks_positive:
            x = -x
        return float(x.median() + half_len)

    h_now, h_before = _line_height(frame_now), _line_height(frame_before)
    if h_now is None or h_before is None:
        return None
    return h_before - h_now

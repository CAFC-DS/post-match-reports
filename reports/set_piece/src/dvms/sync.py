"""Event ↔ tracking synchronisation.

Opta events carry a *cumulative match minute* (period 2 minutes keep counting
from 45+, period 1 stoppage overshoots 45, etc.), while Second Spectrum frames
carry a per-period ``gameClock`` that restarts each period. To line an event up
with a tracking frame we convert the event's minute/second to the same
per-period seconds clock, then find the nearest frame within that period.

The clock maths is exact and fully unit-testable. The ball-distance sanity check
(``validate_sync``) needs a real, full tracking file — it cannot be exercised
against the truncated peek — so its integration test is env-gated.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

# Cumulative seconds at the start of each period (regulation + extra time).
_PERIOD_OFFSETS = {1: 0, 2: 45 * 60, 3: 90 * 60, 4: 105 * 60}


def period_offset_seconds(period_id: int) -> int:
    """Cumulative match seconds at the start of ``period_id``.

    P1=0, P2=2700, P3=5400, P4=6300. Raises ``ValueError`` for any other period
    (e.g. Opta's ``16`` pre-match/formation marker) rather than guessing.
    """
    try:
        return _PERIOD_OFFSETS[int(period_id)]
    except KeyError:
        raise ValueError(f"no game-clock offset defined for period_id={period_id!r}")


def event_game_clock(events_df: pd.DataFrame) -> pd.Series:
    """Per-period seconds clock for each event row.

    ``minute * 60 + second - period_offset``. Opta's ``minute`` is the
    cumulative match minute, so subtracting the period offset yields seconds
    since the period kicked off — directly comparable to a frame's ``gameClock``.
    Rows in a period without a defined offset (e.g. 16) get ``NaN``.
    """
    offsets = events_df["period_id"].map(_PERIOD_OFFSETS)
    clock = events_df["minute"] * 60 + events_df["second"] - offsets
    return clock.astype("float64")


def nearest_frame_index(game_clock, period, frame_index: Dict[int, np.ndarray]):
    """Nearest-frame lookup against a per-period sorted game-clock index.

    ``frame_index`` maps ``period -> sorted 1-D array of frame gameClocks``.
    For each query ``(game_clock[i], period[i])`` the nearest clock in that
    period's array is found (binary search + neighbour compare) and its
    **position within the period array** returned. Scalars in, scalar out;
    arrays in, ``np.intp`` array out. Queries for an absent/empty period return
    ``-1``.
    """
    scalar = np.ndim(game_clock) == 0
    clocks = np.atleast_1d(np.asarray(game_clock, dtype=float))
    periods = np.atleast_1d(np.asarray(period))
    if periods.shape != clocks.shape:
        periods = np.broadcast_to(periods, clocks.shape)

    result = np.full(clocks.shape, -1, dtype=np.intp)
    for p in np.unique(periods):
        arr = frame_index.get(int(p))
        rows = np.where(periods == p)[0]
        if arr is None or len(arr) == 0:
            continue
        arr = np.asarray(arr, dtype=float)
        pos = np.searchsorted(arr, clocks[rows])
        pos = np.clip(pos, 0, len(arr) - 1)
        left = np.clip(pos - 1, 0, len(arr) - 1)
        choose_left = np.abs(arr[left] - clocks[rows]) <= np.abs(arr[pos] - clocks[rows])
        result[rows] = np.where(choose_left, left, pos)

    return int(result[0]) if scalar else result


def _frame_index(tracking_df: pd.DataFrame):
    """Build ``period -> (sorted clocks, sorted frame subframe)`` from ball rows."""
    ball = tracking_df[tracking_df["team"] == "ball"]
    if ball.empty:
        ball = tracking_df.drop_duplicates(["period", "frame_idx"])
    index = {}
    for p, grp in ball.groupby("period"):
        grp = grp.sort_values("game_clock")
        index[int(p)] = (
            grp["game_clock"].to_numpy(dtype=float),
            grp.reset_index(drop=True),
        )
    return index


def validate_sync(
    events_df: pd.DataFrame,
    tracking_df: pd.DataFrame,
    pitch_meta,
    window_seconds: float = 1.5,
) -> pd.DataFrame:
    """Distance between each on-ball event and the tracked ball nearby in time.

    For every event with coordinates in a real period (1-4), the event position
    is converted to metres and put in the acting team's attacking-positive frame
    (Opta events are already recorded acting-team-attacks-right, so we rotate the
    tracked ball into that frame using the period's ``homeAttPositive``), then
    compared to the ball's tracked ``(x, y)`` at its **closest approach within
    ±window_seconds** of the event's clock. The window matters: Opta timestamps
    are whole seconds, and a ball in flight covers 10-15m in half a second — a
    single nearest-frame comparison measures timestamp quantisation, not clock
    alignment. Within-window closest approach answers the actual question: was
    the ball at the event's spot when the offsets say it should be?

    Returns one row per matched event with ``event_id``, ``game_clock``,
    ``frame_idx``, ``ball_x``/``ball_y`` (metres, normalised), ``event_x``/
    ``event_y`` (metres) and ``distance`` (metres). A summary dict
    ``{median, p90, n}`` is attached as ``df.attrs['summary']``.

    Cannot be meaningfully run against the truncated peek (frames don't span the
    events) — the ball-distance assertion lives behind an integration marker.
    """
    from .coords import opta_to_metres

    L, W = pitch_meta.pitch_length, pitch_meta.pitch_width
    home_id = str(pitch_meta.home_team_id)

    ev = events_df[events_df["period_id"].isin(_PERIOD_OFFSETS)].copy()
    ev = ev[ev["x"].notna() & ev["y"].notna()]
    ev = ev[ev["type_id"] != 34]  # drop team/formation markers
    ev["game_clock"] = event_game_clock(ev)

    index = _frame_index(tracking_df)

    rows = []
    for period, grp in ev.groupby("period_id"):
        if period not in index:
            continue
        clocks, frames = index[period]
        fx = frames["x"].to_numpy(dtype=float)
        fy = frames["y"].to_numpy(dtype=float)
        fidx = frames["frame_idx"].to_numpy()
        att_pos = pitch_meta.home_att_positive(period)
        ex, ey = opta_to_metres(grp["x"].to_numpy(), grp["y"].to_numpy(), L, W)
        for i, (_, e) in enumerate(grp.reset_index(drop=True).iterrows()):
            lo = int(np.searchsorted(clocks, e["game_clock"] - window_seconds))
            hi = int(np.searchsorted(clocks, e["game_clock"] + window_seconds))
            if hi <= lo:
                continue
            bx, by = fx[lo:hi], fy[lo:hi]
            team_is_home = str(e["team_id"]) == home_id
            team_attacks_positive = att_pos if team_is_home else not att_pos
            if not team_attacks_positive:
                bx, by = -bx, -by
            dists = np.hypot(ex[i] - bx, ey[i] - by)
            best = int(np.nanargmin(dists)) if np.isfinite(dists).any() else -1
            if best < 0:
                continue
            rows.append(
                {
                    "event_id": e["event_id"],
                    "type_id": e["type_id"],
                    "period_id": period,
                    "game_clock": e["game_clock"],
                    "frame_idx": fidx[lo + best],
                    "event_x": ex[i],
                    "event_y": ey[i],
                    "ball_x": float(bx[best]),
                    "ball_y": float(by[best]),
                    "distance": float(dists[best]),
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        out.attrs["summary"] = {"median": np.nan, "p90": np.nan, "n": 0}
    else:
        out.attrs["summary"] = {
            "median": float(out["distance"].median()),
            "p90": float(out["distance"].quantile(0.90)),
            "n": int(len(out)),
        }
    return out

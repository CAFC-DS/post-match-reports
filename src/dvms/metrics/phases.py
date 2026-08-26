"""Frame-level phase classification from the tracking feed.

The tracking frames carry the possession signal directly (``lastTouch`` =
'home'/'away' on every frame) plus a ``live`` flag for the ball being in
play. That is a materially better basis for phase splits than reconstructing
possession from event data: it covers every instant, not just on-ball events.

Phases, for a given side, on live frames only:

* ``in_possession``    — lastTouch is this side (beyond the transition window)
* ``out_of_possession``— lastTouch is the other side (beyond the window)
* ``transition_to_attack`` — first ``TRANSITION_SECONDS`` after winning it
* ``transition_to_defend`` — first ``TRANSITION_SECONDS`` after losing it
* ``build_up``         — refinement of ``in_possession``: the ball is in the
  side's own half (the settled construction phase). Emitted as a separate
  boolean column, not a fifth phase, so the four phases stay exhaustive.

Dead-ball frames (``live == False``) are dropped before classification —
players walking to positions at a goal kick would otherwise pollute every
average. These definitions are deliberately centralised here; every report
caption that mentions a phase quotes them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRANSITION_SECONDS = 7.0

PHASES = ("in_possession", "out_of_possession",
          "transition_to_attack", "transition_to_defend")


def _ball_frames(tracking: pd.DataFrame) -> pd.DataFrame:
    """One row per (period, frame): clock, live, last_touch, ball x."""
    ball = tracking[tracking["team"] == "ball"]
    cols = ["period", "frame_idx", "game_clock", "live", "last_touch", "x"]
    if ball.empty:
        # No ball rows (defensive fallback): dedupe player rows, no ball x.
        out = tracking.drop_duplicates(["period", "frame_idx"])[
            ["period", "frame_idx", "game_clock", "live", "last_touch"]].copy()
        out["x"] = np.nan
        return out.sort_values(["period", "frame_idx"]).reset_index(drop=True)
    return ball[cols].sort_values(["period", "frame_idx"]).reset_index(drop=True)


def classify_phases(tracking: pd.DataFrame, pitch_meta, side: str) -> pd.DataFrame:
    """Phase per live frame for ``side`` ('home'/'away').

    Returns one row per live frame: ``period``, ``frame_idx``, ``game_clock``,
    ``phase`` (one of :data:`PHASES`), ``build_up`` (bool) and ``ball_x_att``
    (ball x with this side's attack normalised to +x).
    """
    if side not in ("home", "away"):
        raise ValueError(f"side must be 'home' or 'away', got {side!r}")

    frames = _ball_frames(tracking)
    frames = frames[frames["live"] == True].copy()  # noqa: E712
    if frames.empty:
        return pd.DataFrame(columns=["period", "frame_idx", "game_clock",
                                     "phase", "build_up", "ball_x_att"])

    has_ball = (frames["last_touch"] == side).to_numpy()

    # Seconds since the last possession flip, computed per period so a flip
    # never leaks across half-time.
    phase = np.empty(len(frames), dtype=object)
    since_flip = np.full(len(frames), np.inf)
    clocks = frames["game_clock"].to_numpy(dtype=float)
    periods = frames["period"].to_numpy()
    flips = np.zeros(len(frames), dtype=bool)
    flips[1:] = (has_ball[1:] != has_ball[:-1]) | (periods[1:] != periods[:-1])
    last_flip_clock = np.nan
    for i in range(len(frames)):
        if flips[i] or i == 0:
            last_flip_clock = clocks[i]
        since_flip[i] = clocks[i] - last_flip_clock

    in_window = since_flip < TRANSITION_SECONDS
    phase[has_ball & in_window] = "transition_to_attack"
    phase[has_ball & ~in_window] = "in_possession"
    phase[~has_ball & in_window] = "transition_to_defend"
    phase[~has_ball & ~in_window] = "out_of_possession"

    # Ball x in this side's attacking-positive frame, per period.
    ball_x_att = frames["x"].to_numpy(dtype=float).copy()
    for p in np.unique(periods):
        hap = pitch_meta.home_att_positive(int(p))
        if hap is None:
            continue
        attacks_positive = hap if side == "home" else not hap
        if not attacks_positive:
            mask = periods == p
            ball_x_att[mask] = -ball_x_att[mask]

    out = frames[["period", "frame_idx", "game_clock"]].copy()
    out["phase"] = phase
    out["ball_x_att"] = ball_x_att
    out["build_up"] = (phase == "in_possession") & (ball_x_att < 0)
    return out.reset_index(drop=True)

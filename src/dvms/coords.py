"""Coordinate conversion and attack-direction normalisation.

Two coordinate systems meet in this data:

* **Opta 0-100** (event feed) — ``x`` along the pitch length, ``y`` along the
  width, both 0-100, independent of real dimensions.
* **Second Spectrum metres** (tracking) — pitch-centred, ``(0, 0)`` at the
  centre spot, in real metres from the metadata (``pitchLength`` × ``pitchWidth``).

``opta_to_metres`` bridges the first onto the second so an event position can be
compared to the ball's tracked position.

**y convention (stated explicitly, because it is load-bearing for corner-side
and direction logic).** Opta ``y = 0`` is the right-hand touchline when standing
behind a team's own goal looking up-pitch toward the goal it attacks; ``y = 100``
is the left-hand touchline. We map ``y = 0 -> -W/2`` and ``y = 100 -> +W/2``:
facing ``+x`` (the attacked goal), the attacker's left hand points toward
``+y``, which is Second Spectrum's own frame. This sign was **verified
empirically** against a full match: at every Opta corner event the tracked
ball sits on the matching pitch corner only with this orientation (an earlier
draft used the opposite sign and put every corner on the wrong flank, a ~65m
error at the extremes). For distance-to-goal and shot-angle (xG) the y sign is
immaterial — those are symmetric about the pitch centre line.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


def opta_to_metres(x, y, pitch_length: float, pitch_width: float):
    """Convert Opta 0-100 ``x``/``y`` to pitch-centred metres.

    ``x``: 0 -> ``-L/2`` (own goal line), 100 -> ``+L/2`` (attacked goal line).
    ``y``: 0 -> ``-W/2`` (right touchline), 100 -> ``+W/2`` (left touchline).

    Works on scalars or array-likes (returns numpy arrays for the latter).
    """
    x_m = (np.asarray(x, dtype=float) / 100.0 - 0.5) * pitch_length
    y_m = (np.asarray(y, dtype=float) / 100.0 - 0.5) * pitch_width
    if np.ndim(x) == 0 and np.ndim(y) == 0:
        return float(x_m), float(y_m)
    return x_m, y_m


def metres_to_opta(x_m, y_m, pitch_length: float, pitch_width: float) -> Tuple:
    """Inverse of :func:`opta_to_metres` (exact round-trip)."""
    x = (np.asarray(x_m, dtype=float) / pitch_length + 0.5) * 100.0
    y = (np.asarray(y_m, dtype=float) / pitch_width + 0.5) * 100.0
    if np.ndim(x_m) == 0 and np.ndim(y_m) == 0:
        return float(x), float(y)
    return x, y


def normalize_attack_direction(
    df: pd.DataFrame,
    period: int,
    home_att_positive: bool,
    team_is_home: bool,
    x_col: str = "x",
    y_col: str = "y",
) -> pd.DataFrame:
    """Flip a period's rows so the analysed team always attacks ``+x``.

    Reversing attack direction is a **180° rotation** about the pitch centre —
    it negates *both* ``x`` and ``y``, not ``x`` alone (a plain x-flip would
    mirror the pitch left-to-right and put every right-wing action on the left).

    The analysed team attacks positive x in a period when it is the home team
    and ``home_att_positive`` is set, or the away team and it is not; otherwise
    that period's rows are rotated. Only rows whose ``period`` equals ``period``
    are touched. Returns a copy; vectorised.
    """
    out = df.copy()
    team_attacks_positive = home_att_positive if team_is_home else not home_att_positive
    if team_attacks_positive:
        return out
    mask = out["period"] == period
    out.loc[mask, x_col] = -out.loc[mask, x_col]
    out.loc[mask, y_col] = -out.loc[mask, y_col]
    return out

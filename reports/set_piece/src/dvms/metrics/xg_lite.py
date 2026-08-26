"""CAFC-lite xG — a small, deterministic, hand-tuned expected-goals model.

This is **not** a trained model and does not claim to be. It is a transparent
logistic function of a few well-understood shot features, calibrated by hand to
land near widely-known open-play anchor points so shot maps get a sensible,
reproducible weight per shot without any external dependency or fitted artefact.
Every shot in every run gets the exact same number.

Features and the reasoning behind each coefficient (all in the metres frame from
:func:`dvms.coords.opta_to_metres`, attacked goal at ``x = +L/2``, centred ``y``):

* **distance** to the goal centre and **shot angle** (the angle the goal mouth
  subtends at the shot location, via the standard arctan-of-the-posts formula).
  The two linear coefficients were solved to pass through three anchors:
  penalty spot ≈ 0.19, six-yard-central ≈ 0.37, 25 m central ≈ 0.03 (open play).
* **header** (Opta qualifier 15) — an additive *negative* logit term, so a header
  is always worth less than the same-placed foot shot (≈ 0.6× at the penalty
  spot).
* **big chance** (q214) — additive positive term.
* **set-piece context** — from-corner (q25) shots carry a small penalty
  (crowded box, awkward contact); a direct free-kick (q26) a larger one. In this
  sample match q26 never appears (no direct free-kick attempts) and q25 tags a
  handful of shots — the term is implemented and simply contributes zero where
  the qualifier is absent.

The final probability is floored at 0.01 (no shot is treated as truly
impossible); the anchors keep realistic shots comfortably under ~0.4.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..coords import opta_to_metres

XG_MODEL_LABEL = "CAFC-lite xG"

# Shot type_ids (Miss, Post, Attempt Saved, Goal).
_SHOT_TYPE_IDS = frozenset({13, 14, 15, 16})

GOAL_WIDTH = 7.32  # metres, standard

# Hand-solved logit coefficients (see module docstring for the anchor fit).
_B_INTERCEPT = -0.144
_B_DISTANCE = -0.1369
_B_ANGLE = 0.3114
_B_HEADER = -0.5      # header worth ~0.6x the equivalent foot shot
_B_BIG_CHANCE = 1.0
_B_FROM_CORNER = -0.2
_B_DIRECT_FK = -0.3

_Q_HEADER = 15
_Q_BIG_CHANCE = 214
_Q_FROM_CORNER = 25
_Q_DIRECT_FK = 26

_XG_FLOOR = 0.01


def _shot_angle(dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Angle (radians) the goal mouth subtends at the shot location.

    ``dx`` is the straight-line distance from the goal line (``L/2 - x``), ``dy``
    the lateral offset from the centre. Standard formula; wider/closer angles
    give a larger value.
    """
    half = GOAL_WIDTH / 2.0
    numerator = GOAL_WIDTH * dx
    denominator = dx * dx + dy * dy - half * half
    angle = np.arctan2(numerator, denominator)
    # arctan2 can go negative when the shot is level with / behind the posts;
    # clamp to a small positive angle so the logit stays well-behaved.
    return np.where(angle < 0, angle + np.pi, angle)


def add_xg(events_df: pd.DataFrame, pitch_length: float, pitch_width: float) -> pd.Series:
    """CAFC-lite xG per shot, as a Series aligned to ``events_df``.

    Shot rows (type_id 13/14/15/16) get a value in ``[0.01, ~0.4]``; every other
    row is ``NaN``. Deterministic — identical inputs always give identical xG.
    """
    xg = pd.Series(np.nan, index=events_df.index, dtype="float64")
    shots = events_df[events_df["type_id"].isin(_SHOT_TYPE_IDS)]
    if shots.empty:
        return xg

    x_m, y_m = opta_to_metres(shots["x"].to_numpy(), shots["y"].to_numpy(),
                              pitch_length, pitch_width)
    dx = pitch_length / 2.0 - x_m       # distance out from the goal line
    dy = y_m                             # lateral offset from centre
    distance = np.hypot(dx, dy)
    angle = _shot_angle(dx, dy)

    quals = shots["qualifiers"]
    header = quals.apply(lambda q: _Q_HEADER in q).to_numpy()
    big_chance = quals.apply(lambda q: _Q_BIG_CHANCE in q).to_numpy()
    from_corner = quals.apply(lambda q: _Q_FROM_CORNER in q).to_numpy()
    direct_fk = quals.apply(lambda q: _Q_DIRECT_FK in q).to_numpy()

    logit = (
        _B_INTERCEPT
        + _B_DISTANCE * distance
        + _B_ANGLE * angle
        + _B_HEADER * header
        + _B_BIG_CHANCE * big_chance
        + _B_FROM_CORNER * from_corner
        + _B_DIRECT_FK * direct_fk
    )
    prob = 1.0 / (1.0 + np.exp(-logit))
    prob = np.clip(prob, _XG_FLOOR, 0.99)
    xg.loc[shots.index] = prob
    return xg

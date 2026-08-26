"""True average positions per player per phase, from tracking.

This is the map event data could never draw honestly: every player's mean
tracked position over every live frame of a phase — not just the moments
they touched the ball. Positions come out in the side's attacking-positive
frame (attack toward +x), pitch-centred metres.
"""

from __future__ import annotations

import pandas as pd

from .lines import _attack_positive_x


def average_positions(tracking: pd.DataFrame, phases: pd.DataFrame,
                      pitch_meta, side: str) -> pd.DataFrame:
    """Mean position per player per phase (plus a ``build_up`` pseudo-phase).

    Returns: ``opta_id``, ``phase``, ``x`` / ``y`` (metres, attacking +x),
    ``n_frames`` and ``minutes`` (the real time the average is built from —
    a reader should trust a 25-minute average more than a 40-second one).
    """
    team = tracking[tracking["team"] == side].copy()
    if team.empty:
        return pd.DataFrame(columns=["opta_id", "phase", "x", "y",
                                     "n_frames", "minutes"])
    team["x_att"] = _attack_positive_x(team, pitch_meta, side)
    team["y_att"] = team["y"].astype(float)
    # The 180° rotation that flips x also flips y (see coords module).
    for p in team["period"].unique():
        hap = pitch_meta.home_att_positive(int(p))
        if hap is None:
            continue
        attacks_positive = hap if side == "home" else not hap
        if not attacks_positive:
            mask = team["period"] == p
            team.loc[mask, "y_att"] = -team.loc[mask, "y_att"]

    merged = team.merge(
        phases[["period", "frame_idx", "phase", "build_up"]],
        on=["period", "frame_idx"], how="inner",
    )

    # Seconds per kept frame, inferred from the median frame gap so the same
    # code serves any downsample rate.
    clocks = phases.sort_values(["period", "game_clock"])["game_clock"]
    dt = float(clocks.diff().median()) if len(clocks) > 1 else 0.2

    def _agg(df: pd.DataFrame, label: str) -> pd.DataFrame:
        g = df.groupby("opta_id").agg(
            x=("x_att", "mean"), y=("y_att", "mean"), n_frames=("x_att", "size"),
        ).reset_index()
        g["phase"] = label
        g["minutes"] = g["n_frames"] * dt / 60.0
        return g

    parts = [_agg(grp, phase) for phase, grp in merged.groupby("phase")]
    bu = merged[merged["build_up"]]
    if not bu.empty:
        parts.append(_agg(bu, "build_up"))
    out = pd.concat(parts, ignore_index=True)
    return out[["opta_id", "phase", "x", "y", "n_frames", "minutes"]]

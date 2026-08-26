"""Line heights, block shape and compactness from tracking frames.

Units (defence / midfield / attack) are assigned from the F7 team sheet's
``Position`` per player — the same source the handover recommends — rather
than clustering x-coordinates per frame, which flickers whenever a midfielder
drops between the centre-backs. A wing-back listed as a Defender stays part
of the back line; that is a feature (it is how the team is set up), and the
team-sheet basis is stated in every caption that quotes a line height.

All heights are **metres from the team's own goal line** on the 0-to-pitch-
length axis, computed in the team's attacking-positive frame: a defensive
line at 34m is a back line a third of the way up the pitch. The median (not
mean) of the unit is used so one defender stepping out doesn't move the line.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# F7 Position -> unit. Substitutes inherit their SubPosition when they appear
# in tracking, resolved by unit_map().
_POSITION_UNIT = {
    "Goalkeeper": "goalkeeper",
    "Defender": "defence",
    "Midfielder": "midfield",
    "Striker": "attack",
    "Forward": "attack",
}


def unit_map(lineups: pd.DataFrame) -> dict[str, str]:
    """``opta player id -> unit`` from the F7 lineup (subs via SubPosition)."""
    out: dict[str, str] = {}
    for _, r in lineups.iterrows():
        pos = r["sub_position"] or r["position"]
        unit = _POSITION_UNIT.get(pos)
        if unit and pd.notna(r["player_id"]):
            out[str(r["player_id"])] = unit
    return out


def _attack_positive_x(df: pd.DataFrame, pitch_meta, side: str) -> pd.Series:
    """Player x flipped per period so ``side`` attacks +x."""
    x = df["x"].astype(float).copy()
    for p in df["period"].unique():
        hap = pitch_meta.home_att_positive(int(p))
        if hap is None:
            continue
        attacks_positive = hap if side == "home" else not hap
        if not attacks_positive:
            mask = df["period"] == p
            x[mask] = -x[mask]
    return x


def team_shape_timeseries(tracking: pd.DataFrame, pitch_meta, side: str,
                          units: dict[str, str]) -> pd.DataFrame:
    """Per-frame shape numbers for one side.

    One row per (period, frame): ``def_line_m`` / ``mid_line_m`` /
    ``att_line_m`` (median unit height, metres from own goal), ``depth_m``
    (deepest to highest outfielder), ``width_m``, ``def_mid_gap_m`` and
    ``compactness_area_m2`` (convex hull of the outfield players).
    Join to :func:`phases.classify_phases` on (period, frame_idx) to split
    any of these by game phase.
    """
    team = tracking[tracking["team"] == side].copy()
    team["unit"] = team["opta_id"].map(units)
    team = team[team["unit"].notna() & (team["unit"] != "goalkeeper")]
    if team.empty:
        return pd.DataFrame()

    half_len = pitch_meta.pitch_length / 2.0
    team["x_att"] = _attack_positive_x(team, pitch_meta, side)
    team["height_m"] = team["x_att"] + half_len

    rows = []
    for (period, frame_idx), grp in team.groupby(["period", "frame_idx"], sort=True):
        heights = {}
        for unit in ("defence", "midfield", "attack"):
            vals = grp.loc[grp["unit"] == unit, "height_m"]
            heights[unit] = float(vals.median()) if len(vals) else np.nan
        xs = grp["height_m"].to_numpy(dtype=float)
        ys = grp["y"].to_numpy(dtype=float)
        rows.append({
            "period": period,
            "frame_idx": frame_idx,
            "game_clock": float(grp["game_clock"].iloc[0]),
            "def_line_m": heights["defence"],
            "mid_line_m": heights["midfield"],
            "att_line_m": heights["attack"],
            "depth_m": float(xs.max() - xs.min()),
            "width_m": float(ys.max() - ys.min()),
            "def_mid_gap_m": heights["midfield"] - heights["defence"]
                              if not np.isnan(heights["midfield"]) and not np.isnan(heights["defence"])
                              else np.nan,
            "compactness_area_m2": _hull_area(xs, ys),
        })
    return pd.DataFrame(rows)


def _hull_area(xs: np.ndarray, ys: np.ndarray) -> float:
    """Convex-hull area via the monotone chain + shoelace (no scipy)."""
    pts = np.unique(np.column_stack([xs, ys]), axis=0)
    if len(pts) < 3:
        return 0.0
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def half(points):
        chain = []
        for p in points:
            while len(chain) >= 2 and np.cross(chain[-1] - chain[-2], p - chain[-2]) <= 0:
                chain.pop()
            chain.append(p)
        return chain

    hull = half(pts)[:-1] + half(pts[::-1])[:-1]
    hull = np.array(hull)
    x, y = hull[:, 0], hull[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def summarize_by_phase(shape: pd.DataFrame, phases: pd.DataFrame) -> pd.DataFrame:
    """Median shape numbers per phase (plus build-up as its own row)."""
    merged = shape.merge(phases[["period", "frame_idx", "phase", "build_up"]],
                         on=["period", "frame_idx"], how="inner")
    metric_cols = ["def_line_m", "mid_line_m", "att_line_m", "depth_m",
                   "width_m", "def_mid_gap_m", "compactness_area_m2"]
    out = merged.groupby("phase")[metric_cols].median().reset_index()
    bu = merged[merged["build_up"]]
    if not bu.empty:
        row = bu[metric_cols].median()
        row["phase"] = "build_up"
        out = pd.concat([out, row.to_frame().T], ignore_index=True)
    n = merged.groupby("phase").size()
    out["n_frames"] = out["phase"].map(n).fillna(len(bu)).astype(int)
    return out

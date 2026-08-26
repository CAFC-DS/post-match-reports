"""Physical output: provider-computed summaries plus tracking-derived phase splits.

Two tiers, honestly separated:

* The **provider numbers** (Second Spectrum's own physical summary CSV) —
  distances, HSR, sprints, top speed, and the TIP/OTIP/BOP possession splits.
  These are the authoritative figures; :func:`physical_table` just joins
  names/positions on and orders them for a report table.

* The **derived per-phase splits** (:func:`hsr_by_phase`) — high-speed metres
  per game phase, integrated from tracked player speeds (km/h) over the
  downsampled frames joined to the phase classification. Down-sampling makes
  these slight *underestimates* of the provider totals (speed spikes between
  kept frames are missed); they are for comparing phases against each other,
  not for auditing the provider's totals, and captions say so.
"""

from __future__ import annotations

import pandas as pd

# Tracked speeds are metres/second (verified: match maxima ~8.8 m/s align
# with the physical CSV's ~31 km/h top speeds; km/h values would top out ~120).
HSR_THRESHOLD_MS = 20.0 / 3.6


def physical_table(summary: pd.DataFrame, lineups: pd.DataFrame) -> pd.DataFrame:
    """Provider physical summary joined with the team sheet, ordered by distance."""
    lu = lineups[["player_id", "team_id", "last_name", "position", "shirt_number"]]
    out = summary.merge(lu, left_on="opta_player_id", right_on="player_id", how="left")
    return out.sort_values("distance", ascending=False).reset_index(drop=True)


def hsr_by_phase(tracking: pd.DataFrame, phases: pd.DataFrame, side: str) -> pd.DataFrame:
    """High-speed running metres per player per phase, from tracked speeds.

    Distance per kept frame = speed (m/s) × frame gap, summed where the
    speed clears :data:`HSR_THRESHOLD_MS` (20 km/h). Returns ``opta_id``,
    ``phase``, ``hsr_m``, ``total_m``.
    """
    team = tracking[(tracking["team"] == side) & tracking["speed"].notna()].copy()
    if team.empty:
        return pd.DataFrame(columns=["opta_id", "phase", "hsr_m", "total_m"])

    clocks = phases.sort_values(["period", "game_clock"])["game_clock"]
    dt = float(clocks.diff().median()) if len(clocks) > 1 else 0.2

    merged = team.merge(phases[["period", "frame_idx", "phase"]],
                        on=["period", "frame_idx"], how="inner")
    merged["dist_m"] = merged["speed"] * dt
    merged["hsr_m"] = merged["dist_m"].where(merged["speed"] >= HSR_THRESHOLD_MS, 0.0)

    out = merged.groupby(["opta_id", "phase"]).agg(
        hsr_m=("hsr_m", "sum"), total_m=("dist_m", "sum"),
    ).reset_index()
    return out

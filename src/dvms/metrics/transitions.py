"""Transition-episode quality: what happens inside phases.py's
transition_to_attack / transition_to_defend windows.

phases.py already tags every live frame as being inside a transition window
(the ``TRANSITION_SECONDS`` after a possession flip). This module doesn't
reclassify anything — it groups those already-tagged frames into contiguous
episodes and summarises what happened in each: how far a player moved, how
far the ball reached, and whether a shot followed soon after.

An episode's ``duration_s`` is bounded by ``phases.TRANSITION_SECONDS`` by
construction of the classifier's own window, not a free variable measuring
how fast the ball was actually regained.

Deliberately NOT attempted here (documented, not silently approximated):
pressing intensity / a true "regain speed" — there's no acceleration field
and no defender-closing-distance model in the tracked data, only position and
speed — and any formation-aware read of the transition shape, since F7 gives
one static formation per match, not per-minute.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..sync import event_game_clock

SHOT_JOIN_BUFFER_SECONDS = 2.0

EPISODE_COLUMNS = [
    "episode_id", "period", "start_frame_idx", "end_frame_idx",
    "start_clock", "end_clock", "duration_s",
    "start_ball_x_att", "end_ball_x_att",
]

QUALITY_COLUMNS = [
    "episode_id", "duration_s", "distance_covered_m",
    "reached_final_third", "ended_in_shot", "regain_to_shot_s",
]


def transition_episodes(phases_df: pd.DataFrame, phase: str) -> pd.DataFrame:
    """One row per contiguous run of ``phase`` in ``phases_df``.

    A run never spans a period change even if the phase label is unbroken
    across it — half-time is always a new episode, matching phases.py's own
    rule that a possession flip (and hence a fresh window) is forced there.
    """
    if phases_df.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS)

    df = phases_df.sort_values(["period", "game_clock"]).reset_index(drop=True)
    is_phase = (df["phase"] == phase).to_numpy()
    periods = df["period"].to_numpy()

    episode_id = np.full(len(df), -1, dtype=int)
    current = -1
    in_episode = False
    for i in range(len(df)):
        if is_phase[i]:
            new_episode = not in_episode or (i > 0 and periods[i] != periods[i - 1])
            if new_episode:
                current += 1
            episode_id[i] = current
            in_episode = True
        else:
            in_episode = False

    df = df.assign(_episode_id=episode_id)
    rows = []
    for eid, grp in df[df["_episode_id"] >= 0].groupby("_episode_id"):
        rows.append({
            "episode_id": int(eid),
            "period": int(grp["period"].iloc[0]),
            "start_frame_idx": grp["frame_idx"].iloc[0],
            "end_frame_idx": grp["frame_idx"].iloc[-1],
            "start_clock": float(grp["game_clock"].iloc[0]),
            "end_clock": float(grp["game_clock"].iloc[-1]),
            "duration_s": float(grp["game_clock"].iloc[-1] - grp["game_clock"].iloc[0]),
            "start_ball_x_att": float(grp["ball_x_att"].iloc[0]),
            "end_ball_x_att": float(grp["ball_x_att"].iloc[-1]),
        })
    return pd.DataFrame(rows, columns=EPISODE_COLUMNS)


def transition_quality(events: pd.DataFrame, tracking: pd.DataFrame,
                       phases_df: pd.DataFrame, pitch_meta, side: str,
                       phase: str = "transition_to_attack") -> pd.DataFrame:
    """Per-episode quality numbers for ``side``'s transitions.

    ``distance_covered_m`` is the mean per-player distance run during the
    episode (speed × the same inferred ``dt`` used by
    :func:`physical.hsr_by_phase`). ``reached_final_third`` checks whether
    ``ball_x_att`` (already attacking-positive-normalised by phases.py)
    crossed the attacking-third boundary at any point in the episode.
    ``ended_in_shot`` / ``regain_to_shot_s`` join ``side``'s F24 shots whose
    clock falls within the episode window plus a
    :data:`SHOT_JOIN_BUFFER_SECONDS` grace period, since a shot moments after
    the classified window still credibly resulted from the transition.
    """
    episodes = transition_episodes(phases_df, phase)
    if episodes.empty:
        return pd.DataFrame(columns=QUALITY_COLUMNS)

    team = tracking[(tracking["team"] == side) & tracking["speed"].notna()].copy()
    clocks = phases_df.sort_values(["period", "game_clock"])["game_clock"]
    dt = float(clocks.diff().median()) if len(clocks) > 1 else 0.2

    final_third_x = pitch_meta.pitch_length / 6.0

    team_id = pitch_meta.home_team_id if side == "home" else pitch_meta.away_team_id
    shots = events[events.get("is_shot", pd.Series(dtype=bool)).fillna(False)
                  & (events["team_id"].astype(str) == str(team_id))
                  & events["period_id"].isin([1, 2, 3, 4])].copy()
    if not shots.empty:
        shots["game_clock"] = event_game_clock(shots)

    rows = []
    for _, ep in episodes.iterrows():
        period = ep["period"]
        frame_mask = ((team["period"] == period)
                      & (team["frame_idx"] >= ep["start_frame_idx"])
                      & (team["frame_idx"] <= ep["end_frame_idx"]))
        grp = team.loc[frame_mask]
        if grp.empty:
            distance = np.nan
        else:
            per_player = grp.groupby("opta_id")["speed"].apply(lambda s: (s * dt).sum())
            distance = float(per_player.mean())

        reached_final_third = bool(
            max(ep["start_ball_x_att"], ep["end_ball_x_att"]) >= final_third_x
        )

        ended_in_shot = False
        regain_to_shot_s = np.nan
        if not shots.empty:
            window = shots[(shots["period_id"] == period)
                          & (shots["game_clock"] >= ep["start_clock"])
                          & (shots["game_clock"] <= ep["end_clock"] + SHOT_JOIN_BUFFER_SECONDS)]
            if not window.empty:
                ended_in_shot = True
                regain_to_shot_s = float(window["game_clock"].min() - ep["start_clock"])

        rows.append({
            "episode_id": ep["episode_id"],
            "duration_s": ep["duration_s"],
            "distance_covered_m": distance,
            "reached_final_third": reached_final_third,
            "ended_in_shot": ended_in_shot,
            "regain_to_shot_s": regain_to_shot_s,
        })
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def transition_summary(quality_df: pd.DataFrame) -> dict:
    """Match-level rollup of a side's transition episodes."""
    if quality_df.empty:
        return {
            "n_episodes": 0,
            "median_duration_s": np.nan,
            "pct_reaching_final_third": np.nan,
            "pct_ending_in_shot": np.nan,
            "median_distance_m": np.nan,
        }
    return {
        "n_episodes": int(len(quality_df)),
        "median_duration_s": float(quality_df["duration_s"].median()),
        "pct_reaching_final_third": float(quality_df["reached_final_third"].mean() * 100),
        "pct_ending_in_shot": float(quality_df["ended_in_shot"].mean() * 100),
        "median_distance_m": float(quality_df["distance_covered_m"].median()),
    }

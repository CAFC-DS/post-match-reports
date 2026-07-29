"""Line-breaking passes: event passes classified against the tracked defence.

A completed pass "breaks" an opposition line when it starts behind that
line's tracked height and ends beyond it, at the moment the pass was played
— the tracking frame nearest the event supplies where the opposition's
defensive/midfield/attacking units actually stood, so a line break is judged
against the real block, not a fixed pitch zone.

Unit heights use the same F7-team-sheet unit assignment as
:mod:`dvms.metrics.lines` (median x of the unit's players on the frame).

Break style, GeniusIQ's taxonomy re-derived from what the data supports:

* ``around`` — the ball crosses the line outside the unit's occupied width
  (beyond its widest player ±1m): the line was bypassed, not split.
* ``over``  — crossed inside the unit's width but flagged a lofted delivery
  (Opta q1 long ball, or a chipped q155/q156 where present).
* ``through`` — crossed inside the unit's width along the ground: the pass
  that splits two defenders. The default when neither of the above applies.

Only passes into or beyond a line are counted; the receiving side of the
classification (in behind / to feet) is left to callers with the end
coordinates provided.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..coords import opta_to_metres
from ..sync import event_game_clock, nearest_frame_index
from .lines import unit_map as build_unit_map

Q_LONG_BALL = 1
Q_CHIPPED = 155

LINES = ("defence", "midfield", "attack")


def _team_unit_heights(frame_players: pd.DataFrame, units: dict[str, str],
                       flip: bool):
    """(unit -> median x, unit -> (y_min, y_max)) for one frame's players.

    ``flip`` rotates the defending team's coordinates into the passing team's
    attacking-positive frame (180° rotation: both axes negated).
    """
    xs = frame_players["x"].to_numpy(dtype=float)
    ys = frame_players["y"].to_numpy(dtype=float)
    if flip:
        xs, ys = -xs, -ys
    unit_series = frame_players["opta_id"].map(units)
    heights, spans = {}, {}
    for unit in LINES:
        mask = (unit_series == unit).to_numpy()
        if mask.sum() >= 2:
            heights[unit] = float(np.median(xs[mask]))
            spans[unit] = (float(ys[mask].min()) - 1.0, float(ys[mask].max()) + 1.0)
    return heights, spans


def line_breaking_passes(events: pd.DataFrame, tracking: pd.DataFrame,
                         pitch_meta, lineups: pd.DataFrame,
                         team_id: str, opponent_team_id: str,
                         opponent_is_home: bool) -> pd.DataFrame:
    """Completed passes by ``team_id`` that break an opposition line.

    One row per (pass, line broken): ``event_id``, ``player_id``,
    ``receiver_id`` (next same-team event's player), ``line``
    ('defence'/'midfield'/'attack' — the opponent unit crossed), ``style``
    ('around'/'over'/'through'), start/end in metres (passing team attacking
    +x), the line's height at the moment of the pass, plus minute/second.
    A pass splitting both midfield and defence appears twice, once per line —
    callers counting "line-breaking passes" should drop duplicates on
    ``event_id`` or filter to one line.
    """
    L, W = pitch_meta.pitch_length, pitch_meta.pitch_width
    opp_side = "home" if opponent_is_home else "away"
    units = build_unit_map(lineups[lineups["team_id"].astype(str) == str(opponent_team_id)])

    passes = events[(events["is_pass"]) & (events["outcome"] == 1)
                    & (events["team_id"].astype(str) == str(team_id))
                    & events["end_x"].notna()
                    & events["period_id"].isin([1, 2, 3, 4])].copy()
    if passes.empty:
        return pd.DataFrame()

    passes["game_clock"] = event_game_clock(passes)

    # Receiver = the next same-team event's player (Opta's on-ball ordering).
    ev_sorted = events[events["period_id"].isin([1, 2, 3, 4])].sort_values(
        ["period_id", "minute", "second", "event_id"]).reset_index(drop=True)
    pos_of = {eid: i for i, eid in enumerate(ev_sorted["event_id"])}
    receivers = {}
    for eid, tid in zip(passes["event_id"], passes["team_id"]):
        i = pos_of.get(eid)
        receiver = None
        if i is not None:
            for j in range(i + 1, min(i + 6, len(ev_sorted))):
                nxt = ev_sorted.iloc[j]
                if str(nxt["team_id"]) == str(tid) and pd.notna(nxt["player_id"]):
                    receiver = nxt["player_id"]
                    break
        receivers[eid] = receiver

    opp = tracking[tracking["team"] == opp_side]
    frame_groups = {k: g for k, g in opp.groupby(["period", "frame_idx"])}
    ball = tracking[tracking["team"] == "ball"]
    frame_index = {}
    frame_ids = {}
    for p, grp in ball.groupby("period"):
        grp = grp.sort_values("game_clock")
        frame_index[int(p)] = grp["game_clock"].to_numpy(dtype=float)
        frame_ids[int(p)] = grp["frame_idx"].to_numpy()

    rows = []
    for _, e in passes.iterrows():
        period = int(e["period_id"])
        if period not in frame_index:
            continue
        pos = nearest_frame_index(float(e["game_clock"]), period, frame_index)
        if pos < 0:
            continue
        frame_idx = frame_ids[period][pos]
        players = frame_groups.get((period, frame_idx))
        if players is None or players.empty:
            continue

        # The passing team attacks +x in the Opta event frame by construction;
        # rotate the tracked defenders into that frame when the *opponent*
        # attacks +x this period (meaning the passer attacks -x in metres).
        hap = pitch_meta.home_att_positive(period)
        if hap is None:
            continue
        passer_is_home = not opponent_is_home
        passer_attacks_positive = hap if passer_is_home else not hap
        flip = not passer_attacks_positive

        heights, spans = _team_unit_heights(players, units, flip)
        if not heights:
            continue

        sx, sy = opta_to_metres(e["x"], e["y"], L, W)
        ex, ey = opta_to_metres(e["end_x"], e["end_y"], L, W)

        for line, line_x in heights.items():
            if not (sx < line_x < ex):
                continue
            # y where the ball crossed the line (linear interpolation).
            t = (line_x - sx) / (ex - sx) if ex != sx else 0.0
            cross_y = sy + t * (ey - sy)
            y_lo, y_hi = spans[line]
            if not (y_lo <= cross_y <= y_hi):
                style = "around"
            elif Q_LONG_BALL in e["qualifiers"] or Q_CHIPPED in e["qualifiers"]:
                style = "over"
            else:
                style = "through"
            rows.append({
                "event_id": e["event_id"],
                "player_id": e["player_id"],
                "receiver_id": receivers.get(e["event_id"]),
                "line": line,
                "style": style,
                "start_x": sx, "start_y": sy,
                "end_x": ex, "end_y": ey,
                "line_height_x": line_x,
                "minute": e["minute"], "second": e["second"],
                "period_id": period,
            })
    return pd.DataFrame(rows)


def combination_matrix(breaks: pd.DataFrame) -> pd.DataFrame:
    """Passer × receiver counts of line-breaking passes (unique passes)."""
    if breaks.empty:
        return pd.DataFrame()
    uniq = breaks.drop_duplicates("event_id")
    return (uniq.groupby(["player_id", "receiver_id"]).size()
            .reset_index(name="passes")
            .sort_values("passes", ascending=False)
            .reset_index(drop=True))

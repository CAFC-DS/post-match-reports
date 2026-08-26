"""Pass network with tracking-true node positions.

Edges come from the event feed (completed passes, receiver = next same-team
on-ball event); node positions come from tracking — each player's mean
tracked position while their team was in possession — so the network's
geometry reflects where players actually operated, not just where they
happened to touch the ball.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class TrackedPassNetwork:
    nodes: pd.DataFrame   # opta_id, x, y, passes, minutes
    edges: pd.DataFrame   # passer_id, receiver_id, passes, ax, ay, bx, by


def tracked_pass_network(events: pd.DataFrame, avg_positions: pd.DataFrame,
                         team_id: str, min_edge_passes: int = 3) -> TrackedPassNetwork:
    """Build the network for ``team_id``.

    ``avg_positions`` is the output of
    :func:`dvms.metrics.avg_positions.average_positions` for the same side —
    the ``in_possession`` phase rows position the nodes.
    """
    pos = avg_positions[avg_positions["phase"] == "in_possession"]
    pos = pos.set_index("opta_id")[["x", "y", "minutes"]]

    ev = events[events["period_id"].isin([1, 2, 3, 4])].sort_values(
        ["period_id", "minute", "second", "event_id"]).reset_index(drop=True)
    passes = ev[(ev["is_pass"]) & (ev["outcome"] == 1)
                & (ev["team_id"].astype(str) == str(team_id))]

    pairs = []
    idx = {eid: i for i, eid in enumerate(ev["event_id"])}
    for eid, pid, tid in zip(passes["event_id"], passes["player_id"], passes["team_id"]):
        i = idx[eid]
        for j in range(i + 1, min(i + 6, len(ev))):
            nxt = ev.iloc[j]
            if str(nxt["team_id"]) == str(tid) and pd.notna(nxt["player_id"]):
                if nxt["player_id"] != pid:
                    pairs.append((pid, nxt["player_id"]))
                break

    counts = pd.Series(1, index=pd.MultiIndex.from_tuples(
        pairs, names=["passer_id", "receiver_id"])).groupby(level=[0, 1]).sum() \
        if pairs else pd.Series(dtype=int)

    node_passes = passes.groupby("player_id").size()
    nodes = pos.join(node_passes.rename("passes"), how="inner").reset_index()
    nodes["passes"] = nodes["passes"].fillna(0).astype(int)
    nodes = nodes.rename(columns={"index": "opta_id"})

    # Undirected edges above the floor, with both endpoints positioned.
    und: dict[tuple, int] = {}
    for (a, b), n in counts.items():
        key = tuple(sorted((str(a), str(b))))
        und[key] = und.get(key, 0) + int(n)
    edge_rows = []
    locate = pos[["x", "y"]]
    for (a, b), n in und.items():
        if n < min_edge_passes or a not in locate.index or b not in locate.index:
            continue
        edge_rows.append({
            "passer_id": a, "receiver_id": b, "passes": n,
            "ax": locate.loc[a, "x"], "ay": locate.loc[a, "y"],
            "bx": locate.loc[b, "x"], "by": locate.loc[b, "y"],
        })
    return TrackedPassNetwork(nodes=nodes, edges=pd.DataFrame(edge_rows))

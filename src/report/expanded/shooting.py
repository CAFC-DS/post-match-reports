"""Shot placement for the analyst report: where each shot ended up in the goal.

Impect gives the target point of a shot on the goal line as ``targetPoint.y``
(metres from the centre, +3.7 is the left post from the attacker's side) and
``targetPoint.z`` (height in metres; the crossbar is 2.44). Blocked shots have
no target point and are left off the map. The chart is drawn from behind the
shooter, so the attacker's left is the left of the picture.
"""
from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from src.report import metrics, palette, pitch

GOAL_HALF_WIDTH = 3.66
GOAL_HEIGHT = 2.44
X_RANGE = 6.0            # metres either side of the goal centre that the chart shows
SHOT_TYPES = {
    "CLOSE_RANGE_SHOT": "Close range", "MID_RANGE_SHOT": "Mid range", "LONG_RANGE_SHOT": "Long range",
    "HEADER": "Header", "PENALTY_KICK": "Penalty", "DIRECT_FREE_KICK": "Free kick",
    "ONE_VS_ONE_AGAINST_GK": "One v one", "OPEN_GOAL_SHOT": "Open goal", "CORNER": "Corner",
}
_ON_TARGET = ("Goal", "On target")
_STYLE = {"Goal": dict(filled=True, ring=True), "On target": dict(filled=True, ring=False),
          "Off target": dict(filled=False, ring=False)}


def placed_shots(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """The team's non-blocked shots that have a target point on the goal frame."""
    shots = metrics.shot_events(events)
    shots = shots[shots["squadName"] == team]
    if "targetY" not in shots:
        return shots.iloc[0:0]
    shots = shots[shots["targetY"].notna() & shots["targetZ"].notna() & (shots["category"] != "Blocked")].copy()
    shots["category"] = shots["category"].replace({"Other": "Off target"})
    return shots


def goal_zones(on_target: pd.DataFrame) -> list[list[dict[str, int]]]:
    """On-target shots by goal zone: two rows (high, low) of three (left, centre, right) as seen from behind
    the shooter, each with its shot count and how many of them scored."""
    third = GOAL_HALF_WIDTH * 2 / 3
    zones = [[{"n": 0, "goals": 0} for _ in range(3)] for _ in range(2)]
    for r in on_target.itertuples():
        col = 0 if r.targetY > third / 2 else (2 if r.targetY < -third / 2 else 1)       # +y is the attacker's left
        row = 0 if r.targetZ >= GOAL_HEIGHT / 2 else 1
        zones[row][col]["n"] += 1
        zones[row][col]["goals"] += int(r.category == "Goal")
    return zones


def placement_summary(events: pd.DataFrame, team: str, top: int = 10) -> dict[str, Any]:
    """Counts, post-shot xG and the table of shots that were on target or hit the woodwork."""
    shots = placed_shots(events, team)
    wood = shots["woodwork"].notna() if "woodwork" in shots else pd.Series(False, index=shots.index)
    on = shots["category"].isin(_ON_TARGET)
    xgot = float(shots.loc[on, "POSTSHOT_XG"].sum()) if len(shots) else 0.0
    table = shots[on | wood].copy()
    table["xgot"] = table["POSTSHOT_XG"].where(table["category"].isin(_ON_TARGET), 0.0)
    table = table.sort_values(["xgot", "SHOT_XG"], ascending=False).head(top)
    rows = []
    for r in table.itertuples():
        rows.append({
            "minute": f"{int(metrics.minute_num(str(r.gameTime)))}'",
            "player": str(r.playerName).split()[-1],
            "type": SHOT_TYPES.get(str(r.action), str(r.action).replace("_", " ").capitalize()),
            "xg": float(r.SHOT_XG), "xgot": float(r.xgot),
            "result": "Goal" if r.category == "Goal" else ("Post" if pd.notna(getattr(r, "woodwork", None))
                                                           else "Saved"),
        })
    return {"zones": goal_zones(shots[on]), "placed": int(len(shots)), "on_target": int(on.sum()),
            "goals": int((shots["category"] == "Goal").sum()), "woodwork": int(wood.sum()),
            "xgot": xgot, "rows": rows}


def shot_placement_chart(shots: pd.DataFrame, colour: str) -> str:
    """Goal face from behind the shooter: marker area = xG, filled = on target,
    ringed = goal, hollow = off target. Shots wide of the frame are pinned to its edge."""
    z_top = 3.6
    fig, ax = plt.subplots(figsize=(6.6, 2.45), facecolor=palette.PAPER_2)
    fig.subplots_adjust(0.005, 0.005, 0.995, 0.995)
    ax.set_facecolor(palette.PAPER_2)
    ax.set_xlim(-X_RANGE, X_RANGE); ax.set_ylim(-0.3, z_top); ax.set_aspect("equal"); ax.axis("off")
    ax.add_patch(Rectangle((-GOAL_HALF_WIDTH, 0), 2 * GOAL_HALF_WIDTH, GOAL_HEIGHT, facecolor="#e6dfcd",
                           edgecolor="none", zorder=0))
    for frac in (1 / 3, 2 / 3):          # thirds across, halves up: the nine goal zones
        ax.plot([-GOAL_HALF_WIDTH + 2 * GOAL_HALF_WIDTH * frac] * 2, [0, GOAL_HEIGHT], color=palette.HAIR, lw=.7,
                ls=(0, (3, 3)), zorder=1)
    ax.plot([-GOAL_HALF_WIDTH, GOAL_HALF_WIDTH], [GOAL_HEIGHT / 2] * 2, color=palette.HAIR, lw=.7, ls=(0, (3, 3)), zorder=1)
    ax.plot([-X_RANGE, X_RANGE], [0, 0], color=palette.INK, lw=1.1, zorder=2)
    ax.plot([-GOAL_HALF_WIDTH, -GOAL_HALF_WIDTH, GOAL_HALF_WIDTH, GOAL_HALF_WIDTH], [0, GOAL_HEIGHT, GOAL_HEIGHT, 0],
            color=palette.INK, lw=2.6, solid_capstyle="projecting", zorder=2)
    if len(shots):
        # +y is the attacker's left; seen from behind the shooter that is the left of the picture
        px = np.clip(-shots["targetY"].astype(float).to_numpy(), -X_RANGE + .3, X_RANGE - .3)
        pz = np.clip(shots["targetZ"].astype(float).to_numpy(), 0.0, z_top - .3)
        size = 22 + 900 * shots["SHOT_XG"].astype(float).to_numpy()
        cats = shots["category"].to_numpy()
        for cat in ("Off target", "On target", "Goal"):
            m = cats == cat
            if not m.any():
                continue
            st = _STYLE[cat]
            ax.scatter(px[m], pz[m], s=size[m], facecolor=colour if st["filled"] else "none",
                       edgecolors=palette.INK if st["ring"] else colour, linewidths=1.8 if st["ring"] else 1.2,
                       alpha=.92, zorder=5 if cat == "Goal" else 3)
        halo = [pe.withStroke(linewidth=2.4, foreground=palette.PAPER_2)]
        for xi, zi, name, cat in zip(px, pz, shots["playerName"], cats):
            if cat == "Goal":
                ax.annotate(str(name).split()[-1], (xi, zi), xytext=(0, -12), textcoords="offset points", ha="center",
                            va="top", fontsize=7.6, fontweight="bold", color=palette.INK, path_effects=halo, zorder=6)
    return pitch._fig_to_uri(fig)


def shooting_context(events: pd.DataFrame, subject: str, opponent: str, colours: dict[str, str]) -> dict[str, Any]:
    teams = (subject, opponent)
    summaries = {t: placement_summary(events, t) for t in teams}
    return {
        "placement_img": {t: shot_placement_chart(placed_shots(events, t), colours[t]) for t in teams},
        "placement_ctx": {t: {**summaries[t], "xgot": f"{summaries[t]['xgot']:.2f}"} for t in teams},
    }

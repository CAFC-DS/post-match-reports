"""In-possession panels for the analyst report: progression zones, where
players received the ball, threat creation zones and who got the ball into
the final third and box.

Metric functions are pure pandas and take the Impect event frame the report
already loads; the chart functions draw on the shared pitch helpers and
return base64 PNG data URIs. Every map is drawn in the acting team's
attacking frame (left to right), so two teams can be compared on the same
scale.
"""
from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from src.report import metrics, palette, pitch

COLS, ROWS = 6, 3
_SLOTS = 9          # rows in the entry-givers bar panels
_HALF_LEN, _HALF_WID = 52.5, 34.0

# Reception categories as Impect tags them on RECEPTION events. Build-up
# receptions (AVAILABILITY_IN_THE_BACK) and headers are left out, as in the
# U21 report: they say little about how a team got in behind.
RECEPTION_CATEGORIES: dict[str, str] = {
    "AVAILABILITY_BTL": "Between the lines",
    "AVAILABILITY_OUT_WIDE": "Out wide",
    "HOLD_UP_PLAY": "Hold-up play",
    "AVAILABILITY_FDR": "In behind",
    "AVAILABILITY_IN_THE_BOX": "In the box",
}
# Local colours for the categories (the palette has no five-way categorical
# set); chosen to stay apart from Charlton red / opposition grey.
RECEPTION_COLOURS: dict[str, str] = {
    "Between the lines": "#6d3f83",
    "Out wide": "#c0892d",
    "Hold-up play": "#5c7a4a",
    "In behind": "#3f6f8f",
    "In the box": "#1a1a18",
}


RECEPTION_SHORT: dict[str, str] = {
    "Between the lines": "Between lines", "Out wide": "Out wide", "Hold-up play": "Hold-up",
    "In behind": "In behind", "In the box": "In box",
}


def _surname(name: Any) -> str:
    return str(name).split()[-1]


def _bin_index(x: pd.Series, y: pd.Series, cols: int, rows: int) -> tuple[np.ndarray, np.ndarray]:
    """Column / row of each (adjusted) coordinate; out-of-range values clip to the edge."""
    ix = np.floor((x.to_numpy(float) + _HALF_LEN) / (2 * _HALF_LEN) * cols).astype(int).clip(0, cols - 1)
    iy = np.floor((y.to_numpy(float) + _HALF_WID) / (2 * _HALF_WID) * rows).astype(int).clip(0, rows - 1)
    return ix, iy


def _grid(events: pd.DataFrame, values: pd.Series, cols: int, rows: int) -> np.ndarray:
    grid = np.zeros((rows, cols))
    ix, iy = _bin_index(events["endAdjCoordinatesX"], events["endAdjCoordinatesY"], cols, rows)
    np.add.at(grid, (iy, ix), values.to_numpy(float))
    return grid


def _moves(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """The team's passes and carries that have an end location."""
    t = events[(events["squadName"] == team) & events["actionType"].isin(["PASS", "DRIBBLE"])]
    return t[t["endAdjCoordinatesX"].notna() & t["endAdjCoordinatesY"].notna()]


# --------------------------------------------------------------------------- #
# Progression zones
# --------------------------------------------------------------------------- #
def progression_zones(events: pd.DataFrame, team: str, cols: int = COLS, rows: int = ROWS) -> dict[str, Any]:
    """Opponents bypassed by the team's successful passes and carries, binned
    by where the ball was progressed *to*. ``grid[row][col]``: column 0 is the
    team's own goal line, row 0 the bottom touchline."""
    t = _moves(events, team)
    t = t[(t["result"] == "SUCCESS") & (t["BYPASSED_OPPONENTS"] > 0)]
    grid = _grid(t, t["BYPASSED_OPPONENTS"], cols, rows)
    return {"grid": grid, "total": float(grid.sum()), "actions": int(len(t))}


# --------------------------------------------------------------------------- #
# Threat creation zones
# --------------------------------------------------------------------------- #
def threat_zone_grid(events: pd.DataFrame, team: str, cols: int = COLS, rows: int = ROWS) -> dict[str, Any]:
    """Positive open-play threat (PXT_ATTACK of passes and carries, goals
    excluded, shots are not passes or carries) by the zone the action ended in."""
    t = _moves(events, team)
    t = t[t["action"] != "GOAL"]
    values = t["PXT_ATTACK"].fillna(0.0).clip(lower=0.0)
    grid = _grid(t, values, cols, rows)
    return {"grid": grid, "total": float(grid.sum()), "actions": int(len(t))}


# --------------------------------------------------------------------------- #
# Where players received the ball
# --------------------------------------------------------------------------- #
def reception_summary(events: pd.DataFrame, team: str, top: int = 7) -> dict[str, Any]:
    """Receptions in the categories above, plus a per-player table.

    ``players`` is sorted by opponents bypassed on receiving, then by number
    of receptions; ``points`` are the receptions to draw (start location in
    the team's attacking frame)."""
    t = events[(events["squadName"] == team) & (events["actionType"] == "RECEPTION")].copy()
    t["category"] = t["action"].map(RECEPTION_CATEGORIES)
    t = t[t["category"].notna() & t["startAdjCoordinatesX"].notna()]
    t["bypassed"] = t["BYPASSED_OPPONENTS_RECEIVING"].fillna(0.0) if "BYPASSED_OPPONENTS_RECEIVING" in t else 0.0
    counts = {c: int((t["category"] == c).sum()) for c in RECEPTION_CATEGORIES.values()}
    per_player = (t.pivot_table(index="playerName", columns="category", values="eventId", aggfunc="size", fill_value=0)
                  .reindex(columns=list(RECEPTION_COLOURS), fill_value=0))
    per_player["bypassed"] = t.groupby("playerName")["bypassed"].sum()
    per_player["total"] = per_player[list(RECEPTION_COLOURS)].sum(axis=1)
    per_player = per_player.sort_values(["bypassed", "total"], ascending=False).head(top)
    players = [{"name": _surname(name), "counts": [int(row[c]) for c in RECEPTION_COLOURS],
                "bypassed": int(round(row["bypassed"]))} for name, row in per_player.iterrows()]
    return {"counts": counts, "total": int(len(t)), "bypassed": int(round(float(t["bypassed"].sum()))),
            "players": players, "points": t[["startAdjCoordinatesX", "startAdjCoordinatesY", "category", "bypassed"]]}


# --------------------------------------------------------------------------- #
# Who got the ball into the final third / box
# --------------------------------------------------------------------------- #
def entry_givers(events: pd.DataFrame, team: str) -> dict[str, Any]:
    """Completed final-third and box entries by the passer or carrier who
    made them. Everyone with at least one appears."""
    entries = metrics.zone_entries(events, team)
    done = entries[entries["success"]] if len(entries) else entries
    out: dict[str, pd.Series] = {}
    for key, position in (("final_third", "FINAL_THIRD"), ("box", "OPPONENT_BOX")):
        part = done[done["endPitchPosition"] == position] if len(done) else done
        out[key] = (part.groupby("playerName").size().sort_values(ascending=False)
                    if len(part) else pd.Series(dtype=int))
        out[key].index = [_surname(n) for n in out[key].index]
    return {"final_third": out["final_third"], "box": out["box"],
            "n_final_third": int(out["final_third"].sum()), "n_box": int(out["box"].sum())}


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _shade(colour: str, fraction: float) -> tuple[float, float, float, float]:
    from matplotlib.colors import to_rgba
    return to_rgba(colour, 0.08 + 0.72 * float(np.clip(fraction, 0, 1)))


def zone_grid_chart(grid: np.ndarray, colour: str, vmax: float, decimals: int = 0) -> str:
    """Pitch split into ``grid`` cells, each shaded by value (same ``vmax`` for
    both teams) with the value printed in the cell; zero cells stay blank."""
    rows, cols = grid.shape
    _, fig, ax = pitch._horizontal_pitch((6.6, 4.4))
    cell_w, cell_h = 105.0 / cols, 68.0 / rows
    vmax = vmax or 1.0
    for r in range(rows):
        for c in range(cols):
            v = float(grid[r, c])
            ax.add_patch(Rectangle((c * cell_w, r * cell_h), cell_w, cell_h, facecolor=_shade(colour, v / vmax),
                                   edgecolor=palette.PAPER, linewidth=1.0, zorder=0.6))
            if round(v, decimals) > 0:          # cells that would print as 0 stay blank
                dark = v / vmax > .55
                ax.text((c + .5) * cell_w, (r + .5) * cell_h, f"{v:.{decimals}f}", ha="center", va="center",
                        fontsize=13, fontweight="bold", zorder=3, color="white" if dark else palette.INK,
                        path_effects=[pe.withStroke(linewidth=3, foreground=_shade(colour, v / vmax)[:3] if dark
                                                    else palette.PAPER)])
    return pitch._fig_to_uri(fig)


def reception_map(points: pd.DataFrame) -> str:
    """Receptions as dots coloured by category, larger when the receiver
    bypassed opponents."""
    _, fig, ax = pitch._horizontal_pitch((6.6, 4.4))
    for category, colour in RECEPTION_COLOURS.items():
        part = points[points["category"] == category]
        if part.empty:
            continue
        x, y = pitch._to_pitch(part["startAdjCoordinatesX"], part["startAdjCoordinatesY"])
        ax.scatter(x, y, s=38 + part["bypassed"].to_numpy(float) * 34, c=colour, alpha=.78,
                   edgecolors=palette.PAPER, linewidths=.8, zorder=3)
    return pitch._fig_to_uri(fig)


def entry_givers_chart(givers: dict[str, Any], colour: str) -> str:
    """Two bar panels (into the final third, into the box) of entries per player."""
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.3), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.13, right=0.97, top=0.88, bottom=0.06, wspace=0.55)
    vmax = max([1] + [int(s.max()) for s in (givers["final_third"], givers["box"]) if len(s)])
    for ax, key, title in zip(axes, ("final_third", "box"), ("INTO THE FINAL THIRD", "INTO THE BOX")):
        s = givers[key].sort_values(ascending=False).head(_SLOTS)
        ax.set_facecolor(palette.PAPER)
        ypos = np.arange(len(s))[::-1] + (_SLOTS - len(s))        # top-aligned, same bar height in both panels
        ax.barh(ypos, s.to_numpy(), color=colour, alpha=.9, height=.68, zorder=2)
        for y, v in zip(ypos, s.to_numpy()):
            ax.text(v + vmax * .03, y, str(int(v)), va="center", ha="left", fontsize=10.5, fontweight="bold",
                    color=palette.INK)
        ax.set_yticks(ypos)
        ax.set_yticklabels(list(s.index), fontsize=10.5, fontweight="bold", color=palette.INK)
        ax.set_ylim(-.6, _SLOTS - .4)
        ax.set_xlim(0, vmax * 1.3)
        ax.set_xticks([])
        ax.spines[:].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_title(f"{title} · {int(givers[key].sum())}", fontsize=9.5, fontweight="bold",
                     color=palette.MUTED, loc="left")
    return pitch._fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Template context
# --------------------------------------------------------------------------- #
def inpossession_context(events: pd.DataFrame, subject: str, opponent: str) -> dict[str, Any]:
    """Everything the in-possession pages need, keyed by team where per-team.

    Progression and threat grids share one colour scale across both teams so
    they can be compared directly."""
    teams = (subject, opponent)
    colour = {subject: palette.CHARLTON_RED, opponent: palette.OPPONENT_GREY}

    prog = {t: progression_zones(events, t) for t in teams}
    prog_max = max(float(p["grid"].max()) for p in prog.values()) or 1.0
    threat = {t: threat_zone_grid(events, t) for t in teams}
    threat_max = max(float(p["grid"].max()) for p in threat.values()) or 1.0

    receptions, givers = {}, {}
    for t in teams:
        summary = reception_summary(events, t)
        receptions[t] = {
            "img": reception_map(summary["points"]),
            "total": summary["total"], "bypassed": summary["bypassed"],
            "categories": [{"label": c, "short": RECEPTION_SHORT[c], "colour": RECEPTION_COLOURS[c],
                            "n": summary["counts"][c]} for c in RECEPTION_COLOURS],
            "players": summary["players"],
        }
        g = entry_givers(events, t)
        givers[t] = {"img": entry_givers_chart(g, colour[t]), "n_final_third": g["n_final_third"], "n_box": g["n_box"]}

    return {
        "progression_img": {t: zone_grid_chart(prog[t]["grid"], colour[t], prog_max) for t in teams},
        "progression_kpis": {t: {"total": int(round(prog[t]["total"])), "actions": prog[t]["actions"]} for t in teams},
        "threat_zone_img": {t: zone_grid_chart(threat[t]["grid"], colour[t], threat_max, decimals=2) for t in teams},
        "threat_zone_kpis": {t: {"total": f"{threat[t]['total']:.2f}", "actions": threat[t]["actions"]} for t in teams},
        "reception_ctx": receptions,
        "entry_givers_ctx": givers,
    }

"""In-possession panels for the analyst report: progression, where players
received the ball, threat creation, player threat and who got the ball into
the final third and box.

Metric functions are pure pandas and take the Impect event frame the report
already loads; the chart functions return base64 PNG data URIs.

Packing zones
-------------
Impect's packing-zone code (``CBC``, ``DMC``, ``AMR``, ``WL``, ``IBC`` ...) is
the *role* of the player the ball reached, not a patch of pitch: the same code
sits at a different place for different teams (across five matches the median
x of a ``DMC`` end zone ran from -4 m for Charlton to +19 m for West Ham). An
``OPP_`` code is an end zone that belongs to the opposition: it never occurs as
a start zone and 80% of the actions ending there were lost (the rest neutral,
none successful), so they carry no progression and are left out of the role
maps. The role maps therefore draw zones as a schematic line-up, never as a
geographic grid. The decode is empirical (Impect publishes no glossary).
"""
from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.patches import Rectangle

from src.report import metrics, palette, pitch

# Coarse role groups of Impect's packing zones (left/centre/right merged where
# the split carries little). Same decode as expanded/metrics/in_possession.py,
# copied because that module is not importable.
PACKING_ZONE_GROUPS: dict[str, str] = {
    "GKC": "GK", "GKL": "GK", "GKR": "GK",
    "CBL": "CB", "CBR": "CB", "CBC": "CB",
    "FBL": "FBL", "FBR": "FBR",
    "DML": "DM", "DMC": "DM", "DMR": "DM",
    "CML": "CM", "CMC": "CM", "CMR": "CM",
    "AML": "AM", "AMR": "AM", "AMC": "AM",
    "WL": "WL", "WR": "WR",
    "IBWL": "IBWL", "IBWR": "IBWR", "IBL": "IB", "IBC": "IB", "IBR": "IB",
}
# Schematic layout, own goal on the left. (group, x0, x1, y0, y1, label) on a
# 105 x 68 canvas; the attacker's left is the top edge.
_ROLE_CELLS = [
    ("GK", 0, 9, 0, 68, "GK"),
    ("FBL", 9, 27, 45.33, 68, "Full-back"), ("CB", 9, 27, 22.67, 45.33, "Centre-back"),
    ("FBR", 9, 27, 0, 22.67, "Full-back"),
    ("DM", 27, 44, 0, 68, "Def. mid"),
    ("CM", 44, 61, 0, 68, "Central mid"),
    ("WL", 61, 82, 45.33, 68, "Wing"), ("AM", 61, 82, 22.67, 45.33, "Att. mid"), ("WR", 61, 82, 0, 22.67, "Wing"),
    ("IBWL", 82, 105, 45.33, 68, "Box, wide"), ("IB", 82, 105, 22.67, 45.33, "In the box"),
    ("IBWR", 82, 105, 0, 22.67, "Box, wide"),
]

# Impect reception tags kept for the category strip. Build-up receptions
# (AVAILABILITY_IN_THE_BACK) and headers are left out, as in the U21 report.
RECEPTION_CATEGORIES: dict[str, str] = {
    "AVAILABILITY_BTL": "Between the lines",
    "AVAILABILITY_OUT_WIDE": "Out wide",
    "HOLD_UP_PLAY": "Hold-up play",
    "AVAILABILITY_FDR": "In behind",
    "AVAILABILITY_IN_THE_BOX": "In the box",
}
_SLOTS = 9          # rows in the entry-givers bar panels
_THREAT_SLOTS = 8   # rows in the player threat bar panels


def _surname(name: Any) -> str:
    return str(name).split()[-1]


def _role_values(frame: pd.DataFrame, zone_col: str, values: pd.Series) -> dict[str, float]:
    """Sum ``values`` by role group of ``zone_col``; ``OPP_`` and untagged zones are dropped."""
    zone = frame[zone_col].astype("object")
    group = zone.map(PACKING_ZONE_GROUPS)           # OPP_* and missing codes map to NaN
    sums = values.groupby(group).sum()
    return {str(k): float(v) for k, v in sums.items() if pd.notna(k)}


def _moves(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """The team's passes and carries that have an end location."""
    t = events[(events["squadName"] == team) & events["actionType"].isin(["PASS", "DRIBBLE"])]
    return t[t["endAdjCoordinatesX"].notna() & t["endAdjCoordinatesY"].notna()]


# --------------------------------------------------------------------------- #
# Progression by packing zone
# --------------------------------------------------------------------------- #
def progression_zones(events: pd.DataFrame, team: str) -> dict[str, Any]:
    """Opponents (and, separately, defenders) bypassed by the team's successful
    passes and carries, by the role zone the ball was progressed *to*: the zone
    is the role of the player the ball reached, not where the bypassed
    opponents stood."""
    t = _moves(events, team)
    t = t[(t["result"] == "SUCCESS") & (t["BYPASSED_OPPONENTS"] > 0)]
    values = _role_values(t, "endPackingZone", t["BYPASSED_OPPONENTS"].astype(float))
    defenders = _role_values(t, "endPackingZone", t["BYPASSED_DEFENDERS"].fillna(0.0).astype(float))
    return {"values": values, "defenders": defenders, "total": float(sum(values.values())),
            "defenders_total": float(sum(defenders.values())), "actions": int(len(t))}


# --------------------------------------------------------------------------- #
# Threat creation by packing zone
# --------------------------------------------------------------------------- #
def _positive_threat(frame: pd.DataFrame) -> pd.Series:
    return frame["PXT_ATTACK"].fillna(0.0).clip(lower=0.0)


def threat_zone_values(events: pd.DataFrame, team: str) -> dict[str, Any]:
    """Positive open-play threat (passes and carries, goals excluded) by the role
    zone the action ended in."""
    t = _moves(events, team)
    t = t[t["action"] != "GOAL"]
    values = _role_values(t, "endPackingZone", _positive_threat(t))
    return {"values": values, "total": float(sum(values.values())), "actions": int(len(t))}


# --------------------------------------------------------------------------- #
# Where players received the ball
# --------------------------------------------------------------------------- #
def reception_summary(events: pd.DataFrame, team: str, top: int = 5) -> dict[str, Any]:
    """Receptions in the Impect categories above, by the receiver's role zone.

    ``bypassed`` is opponents taken out of the game by the receiver on
    receiving; ``xt`` is the positive threat credited to the reception event.
    ``players`` is sorted by opponents bypassed, then by receptions."""
    t = events[(events["squadName"] == team) & (events["actionType"] == "RECEPTION")].copy()
    t["category"] = t["action"].map(RECEPTION_CATEGORIES)
    t = t[t["category"].notna()]
    t["bypassed"] = t["BYPASSED_OPPONENTS_RECEIVING"].fillna(0.0) if "BYPASSED_OPPONENTS_RECEIVING" in t else 0.0
    t["xt"] = _positive_threat(t)
    by_role = _role_values(t, "startPackingZone", t["bypassed"])
    n_by_role = _role_values(t, "startPackingZone", pd.Series(1.0, index=t.index))
    per_player = t.groupby("playerName").agg(receptions=("eventId", "size"), bypassed=("bypassed", "sum"),
                                             xt=("xt", "sum"))
    per_player = per_player.sort_values(["bypassed", "receptions"], ascending=False).head(top)
    return {
        "counts": {c: int((t["category"] == c).sum()) for c in RECEPTION_CATEGORIES.values()},
        "total": int(len(t)), "bypassed": int(round(float(t["bypassed"].sum()))),
        "values": by_role, "receptions_by_role": n_by_role,
        "players": [{"name": _surname(n), "receptions": int(r.receptions), "bypassed": int(round(r.bypassed)),
                     "xt": float(r.xt)} for n, r in per_player.iterrows()],
    }


# --------------------------------------------------------------------------- #
# Player threat: passing, carrying, receiving
# --------------------------------------------------------------------------- #
def player_threat_panels(events: pd.DataFrame, team: str, top: int = _THREAT_SLOTS) -> dict[str, Any]:
    """Positive threat by player, split by what they did: pass, carry or receive.

    All three use ``PXT_ATTACK`` (goals excluded). Impect credits a completed
    move's threat to the passer or carrier *and* to the receiver, so the panels
    are separate rankings, not shares of one total. Passing plus carrying is
    the measure the report has always used for 'threat created'."""
    t = events[(events["squadName"] == team) & (events["action"] != "GOAL")]
    out: dict[str, Any] = {}
    for key, action_type in (("passing", "PASS"), ("carrying", "DRIBBLE"), ("receiving", "RECEPTION")):
        part = t[t["actionType"] == action_type]
        by_player = _positive_threat(part).groupby(part["playerName"]).sum()
        by_player = by_player[by_player > 0].sort_values(ascending=False)
        out[key] = pd.Series(by_player.head(top).to_numpy(), index=[_surname(n) for n in by_player.head(top).index])
        out[f"{key}_total"] = float(by_player.sum())
    out["created_total"] = out["passing_total"] + out["carrying_total"]
    return out


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
    return to_rgba(colour, 0.08 + 0.72 * float(np.clip(fraction, 0, 1)))


def packing_zone_chart(values: dict[str, float], colour: str, vmax: float, decimals: int = 0,
                       sub: dict[str, str] | None = None, label_prefix: str = "", small: bool = False) -> str:
    """Role-line map: the twelve packing-zone groups as a schematic line-up, own
    goal on the left. Each cell is shaded by its value against ``vmax`` (shared
    by both teams) and prints the value; zero cells stay blank. ``sub`` adds a
    small second line per cell and ``label_prefix`` (e.g. ``"TO "``) says the
    zone is the role the ball *reached*. ``small`` draws the map at the size of a
    half-page panel, with type set for that size rather than scaled down."""
    size, label_font, value_font, sub_font, sub_gap = ((3.3, 2.2), 5.6, 10.0, 5.6, 7.6) if small else \
                                                      ((6.6, 4.4), 9.2, 19.0, 9.0, 7.2)
    fig, ax = plt.subplots(figsize=size, facecolor=palette.PAPER_2)
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_facecolor(palette.PAPER_2)
    ax.set_xlim(-1, 106); ax.set_ylim(-1, 69); ax.set_aspect("equal"); ax.axis("off")
    vmax = vmax or 1.0
    units_per_pt = 107 / (size[0] * 72)
    for group, x0, x1, y0, y1, label in _ROLE_CELLS:
        v = float(values.get(group, 0.0))
        shown = round(v, decimals) > 0
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=_shade(colour, v / vmax if shown else 0),
                               edgecolor=palette.PAPER, linewidth=1.4, zorder=1))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        dark = shown and v / vmax > .4
        text = (label_prefix + label).upper()
        if len(text) * label_font * 0.62 * units_per_pt > (x1 - x0) - 1.5:      # too wide for the cell: stack the words
            text = text.replace(" ", "\n")
        ax.text(cx, y1 - 2.2, text, ha="center", va="top", fontsize=label_font, linespacing=1.05,
                fontweight="bold", color="white" if dark else palette.MUTED, zorder=3)
        if shown:
            ax.text(cx, cy, f"{v:.{decimals}f}", ha="center", va="center", fontsize=value_font, fontweight="bold",
                    zorder=3, color="white" if v / vmax > .55 else palette.INK)
            if sub and sub.get(group):
                ax.text(cx, cy - sub_gap, sub[group], ha="center", va="center", fontsize=sub_font,
                        color="white" if dark else palette.MUTED, zorder=3)
    ax.add_patch(Rectangle((0, 0), 105, 68, fill=False, edgecolor=palette.INK, linewidth=1.0, zorder=4))
    ax.annotate("", xy=(103, -0.2), xytext=(88, -0.2), arrowprops=dict(arrowstyle="-|>", color=palette.MUTED, lw=.9))
    return pitch._fig_to_uri(fig)


def _bar_panels_chart(panels: list[tuple[str, pd.Series, str]], colour: str, slots: int, figsize: tuple[float, float],
                      decimals: int = 0, label_size: float = 8.6) -> str:
    """Side-by-side horizontal bar panels (title, series, sum text), one style for
    entry givers and the player threat panels: top-aligned, same bar height in
    every panel, labels designed at print size."""
    fig, axes = plt.subplots(1, len(panels), figsize=figsize, facecolor=palette.PAPER)
    axes = np.atleast_1d(axes)
    fig.subplots_adjust(left=0.13 if len(panels) == 2 else 0.12, right=0.99, top=0.9, bottom=0.03,
                        wspace=0.75 if len(panels) == 2 else 0.95)
    vmax = max([1e-9] + [float(s.max()) for _, s, _ in panels if len(s)])
    for ax, (title, series, total) in zip(axes, panels):
        s = series.head(slots)
        ax.set_facecolor(palette.PAPER)
        ypos = np.arange(len(s))[::-1] + (slots - len(s))
        ax.barh(ypos, s.to_numpy(), color=colour, alpha=.9, height=.68, zorder=2)
        for y, v in zip(ypos, s.to_numpy()):
            ax.text(v + vmax * .04, y, f"{v:.{decimals}f}", va="center", ha="left", fontsize=label_size,
                    fontweight="bold", color=palette.INK)
        ax.set_yticks(ypos)
        ax.set_yticklabels(list(s.index), fontsize=label_size, fontweight="bold", color=palette.INK)
        ax.set_ylim(-.6, slots - .4)
        ax.set_xlim(0, vmax * 1.6)
        ax.set_xticks([])
        ax.spines[:].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_title(f"{title} · {total}", fontsize=label_size + .4, fontweight="bold", color=palette.MUTED,
                     loc="left")
    return pitch._fig_to_uri(fig)


def entry_givers_chart(givers: dict[str, Any], colour: str) -> str:
    """Bar panels of completed entries per player: into the final third, into the box."""
    return _bar_panels_chart(
        [("INTO THE FINAL THIRD", givers["final_third"], str(int(givers["final_third"].sum()))),
         ("INTO THE BOX", givers["box"], str(int(givers["box"].sum())))],
        colour, _SLOTS, (7.6, 3.3), label_size=10.5)


def player_threat_chart(panels: dict[str, Any], colour: str) -> str:
    """Three bar panels per team: passing, carrying and receiving threat, drawn at
    the width of a half-page card so the labels print at their set size."""
    return _bar_panels_chart(
        [("PASSING", panels["passing"], f"{panels['passing_total']:.2f}"),
         ("CARRYING", panels["carrying"], f"{panels['carrying_total']:.2f}"),
         ("RECEIVING", panels["receiving"], f"{panels['receiving_total']:.2f}")],
        colour, _THREAT_SLOTS, (5.4, 2.95), decimals=3, label_size=7.6)


# --------------------------------------------------------------------------- #
# Template context
# --------------------------------------------------------------------------- #
def inpossession_context(events: pd.DataFrame, subject: str, opponent: str) -> dict[str, Any]:
    """Everything the in-possession pages need except the threat density maps
    (drawn in ``working`` with the report's heatmap styling). Role maps share one
    colour scale across both teams so they can be compared directly."""
    teams = (subject, opponent)
    colour = {subject: palette.CHARLTON_RED, opponent: palette.OPPONENT_GREY}

    prog = {t: progression_zones(events, t) for t in teams}
    prog_max = max([1.0] + [max(p["values"].values(), default=0.0) for p in prog.values()])
    threat = {t: threat_zone_values(events, t) for t in teams}
    threat_max = max([1e-9] + [max(p["values"].values(), default=0.0) for p in threat.values()])
    receptions = {t: reception_summary(events, t) for t in teams}
    rec_max = max([1.0] + [max(r["values"].values(), default=0.0) for r in receptions.values()])

    reception_ctx, givers_ctx, player_threat_ctx = {}, {}, {}
    for t in teams:
        r = receptions[t]
        sub = {g: f"{int(n)} received" for g, n in r["receptions_by_role"].items()}
        reception_ctx[t] = {
            "img": packing_zone_chart(r["values"], colour[t], rec_max, sub=sub),
            "total": r["total"], "bypassed": r["bypassed"],
            "categories": [{"label": c, "n": r["counts"][c]} for c in RECEPTION_CATEGORIES.values()],
            "players": r["players"],
        }
        g = entry_givers(events, t)
        givers_ctx[t] = {"img": entry_givers_chart(g, colour[t]), "n_final_third": g["n_final_third"],
                         "n_box": g["n_box"]}
        panels = player_threat_panels(events, t)
        player_threat_ctx[t] = {
            "img": player_threat_chart(panels, colour[t]),
            "passing": f"{panels['passing_total']:.2f}", "carrying": f"{panels['carrying_total']:.2f}",
            "receiving": f"{panels['receiving_total']:.2f}", "created": f"{panels['created_total']:.2f}",
        }

    return {
        "progression_img": {
            t: packing_zone_chart(prog[t]["values"], colour[t], prog_max, label_prefix="To ",
                                  sub={g: f"{int(round(prog[t]['defenders'].get(g, 0.0)))} def."
                                       for g, v in prog[t]["values"].items() if round(v) > 0})
            for t in teams},
        "progression_kpis": {t: {"total": int(round(prog[t]["total"])), "actions": prog[t]["actions"],
                                 "defenders": int(round(prog[t]["defenders_total"]))} for t in teams},
        "threat_zone_img": {t: packing_zone_chart(threat[t]["values"], colour[t], threat_max, decimals=2,
                                                  label_prefix="To ", small=True) for t in teams},
        "threat_zone_kpis": {t: {"total": f"{threat[t]['total']:.2f}", "actions": threat[t]["actions"]}
                             for t in teams},
        "reception_ctx": reception_ctx,
        "entry_givers_ctx": givers_ctx,
        "player_threat_ctx": player_threat_ctx,
    }

"""Out-of-possession panels for the analyst report: duel maps, pressing.

Both teams on every panel, on the same scales, drawn in each team's own attacking
frame (a vertical pitch, own goal at the bottom).
"""
from __future__ import annotations

from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, to_rgba
from mplsoccer import VerticalPitch
from scipy.ndimage import gaussian_filter

from src.report import palette, pitch
from src.report.expanded import inpossession

DUEL_TYPES = (("AERIAL", "Aerial"), ("GROUND", "Ground"))
_PRESS_SLOTS = 8


def _surname(name: Any) -> str:
    return str(name).split()[-1]


def orient_duels(duels: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Duel rows with ``x``/``y`` in each player's *own team's* attacking frame.

    A duel's coordinates are the acting event's, so they are in the acting team's
    frame; the opponent's row of the same duel (the loser, usually) must be flipped."""
    out = duels.copy()
    acting = events.drop_duplicates("eventId").set_index("eventId")["squadName"]
    flip = out["eventId"].map(acting).ne(out["squadName"]) & out["eventId"].map(acting).notna()
    sign = np.where(flip, -1.0, 1.0)
    out["x"] = pd.to_numeric(out["startAdjCoordinatesX"], errors="coerce") * sign
    out["y"] = pd.to_numeric(out["startAdjCoordinatesY"], errors="coerce") * sign
    return out


def duel_totals(duels: pd.DataFrame, team: str) -> dict[str, dict[str, int]]:
    """Won / total / percentage for each duel type and overall."""
    t = duels[duels["squadName"] == team]
    out = {}
    for key, part in (("all", t), *((k, t[t["duel_type"] == k]) for k, _ in DUEL_TYPES)):
        won, total = int((part["outcome"] == "WON").sum()), int(len(part))
        out[key] = {"won": won, "total": total, "pct": round(won / total * 100) if total else 0}
    return out


def duel_map_chart(duels: pd.DataFrame, team: str, duel_type: str, colour: str) -> str:
    """Won (dot) and lost (cross) duels over a soft density of where the team contested them."""
    t = duels[(duels["squadName"] == team) & (duels["duel_type"] == duel_type)].dropna(subset=["x", "y"])
    pitch_obj, fig, ax = pitch._vertical_pitch((3.1, 4.6))
    if len(t):
        px, py = pitch._to_pitch(t["x"], t["y"])
        stat = pitch_obj.bin_statistic(px, py, statistic="count", bins=(14, 20))
        stat["statistic"] = gaussian_filter(stat["statistic"], 1.4)
        ramp = LinearSegmentedColormap.from_list("duel", [to_rgba(palette.PAPER_2, 0), to_rgba(colour, .5)])
        pitch_obj.heatmap(stat, ax=ax, cmap=ramp, edgecolors="none", zorder=1)
        for outcome, marker, face in (("LOST", "X", palette.FAIL_REDGREY), ("WON", "o", palette.SUCCESS_GREEN)):
            part = t[t["outcome"] == outcome]
            if part.empty:
                continue
            x, y = pitch._to_pitch(part["x"], part["y"])
            pitch_obj.scatter(x, y, ax=ax, s=34, color=face, marker=marker, edgecolors=palette.PAPER_2,
                              linewidth=.7, alpha=.92, zorder=3)
    return pitch._fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Pressing
# --------------------------------------------------------------------------- #
def pressing_summary(pressure: pd.DataFrame, events: pd.DataFrame, team: str) -> dict[str, Any]:
    """Pressures by player and the forced turnovers among them (the pressed action failed)."""
    p = pressure[pressure["squadName"] == team].copy()
    lost = events.drop_duplicates("eventId").set_index("eventId")["result"].eq("FAIL")
    p["forced"] = p["eventId"].map(lost).fillna(False).astype(bool)
    x = -pd.to_numeric(p["startAdjCoordinatesX"], errors="coerce")        # carrier's frame, so negate
    by_player = p.groupby("playerName").agg(pressures=("eventId", "size"), forced=("forced", "sum"))

    def best(column: str) -> pd.Series:
        part = by_player[by_player[column] > 0][column].sort_values(ascending=False).head(_PRESS_SLOTS)
        return pd.Series(part.to_numpy(), index=[_surname(n) for n in part.index])

    n = int(len(p))
    return {"n": n, "forced": int(p["forced"].sum()), "forced_pct": round(float(p["forced"].mean() * 100)) if n else 0,
            "opp_half": int((x > 0).sum()), "opp_third": int((x > 17.5).sum()),
            "top_pressures": best("pressures"), "top_forced": best("forced")}


def pressure_heatmap(pressure: pd.DataFrame, team: str, vmax: float) -> tuple[str, float]:
    """Pressure density in the team's own frame. Returns the image and the peak
    (so both teams can be drawn on one scale)."""
    from matplotlib.colors import PowerNorm

    from src.report.expanded.working import _THERMAL_CMAP, _heatmap_pitch_kwargs

    p = pressure[pressure["squadName"] == team]
    x = -pd.to_numeric(p["startAdjCoordinatesX"], errors="coerce")
    y = -pd.to_numeric(p["startAdjCoordinatesY"], errors="coerce")
    pitch_obj = VerticalPitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_heatmap_pitch_kwargs())
    fig, ax = pitch_obj.draw(figsize=(3.2, 4.9))
    fig.set_facecolor(palette.PAPER_2)
    px, py = pitch._to_pitch(x, y)
    stat = pitch_obj.bin_statistic(px, py, statistic="count", bins=(20, 30))
    stat["statistic"] = gaussian_filter(stat["statistic"], 1.6)
    pitch_obj.heatmap(stat, ax=ax, cmap=_THERMAL_CMAP, edgecolors="none", alpha=.92,
                      norm=PowerNorm(.6, vmin=0, vmax=vmax or float(stat["statistic"].max()) or 1.0), zorder=1)
    return pitch._fig_to_uri(fig), float(stat["statistic"].max())


def pressing_chart(summary: dict[str, Any], colour: str) -> str:
    return inpossession._bar_panels_chart(
        [("PRESSURES", summary["top_pressures"], str(summary["n"])),
         ("FORCED TURNOVERS", summary["top_forced"], str(summary["forced"]))],
        colour, _PRESS_SLOTS, (7.6, 3.5), label_size=10.2)


# --------------------------------------------------------------------------- #
# Ball regains by third
# --------------------------------------------------------------------------- #
THIRDS = (("Defensive third", "#8a8678"), ("Middle third", "#c0892d"), ("Attacking third", "#5c7a4a"))
_THIRD_EDGES = (-17.5, 17.5)


def third_of(x: pd.Series) -> pd.Series:
    """0 / 1 / 2 for the defensive / middle / attacking third of a team-frame x coordinate."""
    return pd.cut(pd.to_numeric(x, errors="coerce"), [-np.inf, *_THIRD_EDGES, np.inf], labels=False)


def regains(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """The team's ball wins with the third they happened in and whether the team shot within 15s of
    winning the ball without the opponent touching it in between (the report's shot-after-regain rule)."""
    t = events[events["squadName"] == team].sort_values("gameTimeInSec")
    flag = lambda name: pd.to_numeric(t.get(name, 0), errors="coerce").fillna(0)
    won = t[flag("BALL_WIN_NUMBER") == 1].copy()
    won["third"] = third_of(won["startAdjCoordinatesX"])
    won = won[won["third"].notna()]
    shot_times = t.loc[flag("SHOT_AT_GOAL_NUMBER") == 1, "gameTimeInSec"].to_numpy()
    ordered = events.sort_values("gameTimeInSec")

    def led_to_shot(rt: float) -> bool:
        window = shot_times[(shot_times >= rt) & (shot_times <= rt + 15)]
        if not len(window):
            return False
        between = ordered[(ordered["gameTimeInSec"] > rt) & (ordered["gameTimeInSec"] < window[0])]
        return not (between["squadName"] != team).any()

    won["led_to_shot"] = won["gameTimeInSec"].map(led_to_shot) if len(won) else pd.Series(dtype=bool)
    return won


def losses_by_third(events: pd.DataFrame, team: str) -> list[int]:
    t = events[events["squadName"] == team]
    lost = t[pd.to_numeric(t.get("BALL_LOSS_NUMBER", 0), errors="coerce").fillna(0) == 1]
    thirds = third_of(lost["startAdjCoordinatesX"]).dropna().astype(int)
    return [int((thirds == i).sum()) for i in range(3)]


def regain_summary(events: pd.DataFrame, team: str, top: int = 8) -> dict[str, Any]:
    won = regains(events, team)
    counts = [int((won["third"] == i).sum()) for i in range(3)]
    n = int(len(won))
    by_player = pd.crosstab(won["playerName"], won["third"]).reindex(columns=[0, 1, 2], fill_value=0) if n else \
        pd.DataFrame(columns=[0, 1, 2])
    by_player["total"] = by_player.sum(axis=1) if n else []
    ranked = by_player.sort_values("total", ascending=False).head(top)
    losses = losses_by_third(events, team)
    return {"n": n, "counts": counts, "pcts": [round(c / n * 100) if n else 0 for c in counts],
            "shots": int(won["led_to_shot"].sum()) if n else 0,
            "shot_pct": round(float(won["led_to_shot"].mean() * 100)) if n else 0,
            "losses": losses, "losses_n": int(sum(losses)),
            "players": [(_surname(name), [int(r[i]) for i in range(3)]) for name, r in ranked.iterrows()],
            "frame": won}


def regain_map_chart(summary: dict[str, Any]) -> str:
    """Own goal at the bottom; the thirds are shaded and each regain is a dot in its third's
    colour, ringed where the team shot within 15s."""
    pitch_obj, fig, ax = pitch._vertical_pitch((3.5, 5.2))
    for i, (_, colour) in enumerate(THIRDS):
        y0 = (0, 105 / 3, 2 * 105 / 3)[i]
        ax.axhspan(y0, y0 + 105 / 3, facecolor=to_rgba(colour, .12), edgecolor="none", zorder=0)
    won = summary["frame"]
    if len(won):
        x, y = pitch._to_pitch(won["startAdjCoordinatesX"], won["startAdjCoordinatesY"])
        colours = [THIRDS[int(i)][1] for i in won["third"]]
        pitch_obj.scatter(x, y, ax=ax, s=34, c=colours, edgecolors=palette.PAPER_2, linewidth=.6, alpha=.92, zorder=3)
        led = won["led_to_shot"].to_numpy(dtype=bool)
        if led.any():
            pitch_obj.scatter(x[led], y[led], ax=ax, s=110, facecolors="none", edgecolors=palette.INK, linewidth=1.5,
                              zorder=4)
    return pitch._fig_to_uri(fig)


def regain_players_chart(summary: dict[str, Any]) -> str:
    """Who won the ball back: stacked bars per player, one segment per third."""
    players = summary["players"]
    slots = 8
    fig, ax = plt.subplots(figsize=(7.6, 3.5), facecolor=palette.PAPER)
    fig.subplots_adjust(left=.12, right=.97, top=.86, bottom=.04)
    ax.set_facecolor(palette.PAPER)
    vmax = max([1] + [sum(v) for _, v in players])
    for row, (name, parts) in enumerate(players):
        y = slots - 1 - row
        left = 0
        for part, (_, colour) in zip(parts, THIRDS):
            if part:
                ax.barh(y, part, left=left, color=colour, height=.68, zorder=2)
                if part >= vmax * .07:
                    ax.text(left + part / 2, y, str(part), ha="center", va="center", fontsize=9.4, fontweight="bold",
                            color="white")
                left += part
        ax.text(left + vmax * .03, y, str(left), va="center", fontsize=10.5, fontweight="bold", color=palette.INK)
    ax.set_yticks([slots - 1 - r for r in range(len(players))])
    ax.set_yticklabels([n for n, _ in players], fontsize=10.5, fontweight="bold", color=palette.INK)
    ax.set_ylim(-.6, slots - .4); ax.set_xlim(0, vmax * 1.12); ax.set_xticks([])
    ax.spines[:].set_visible(False); ax.tick_params(axis="y", length=0)
    from matplotlib.patches import Patch
    fig.legend(handles=[Patch(color=c, label=n) for n, c in THIRDS], loc="upper center", ncol=3, frameon=False,
               fontsize=10)
    return pitch._fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Template context
# --------------------------------------------------------------------------- #
def outofpossession_context(events: pd.DataFrame, duels: pd.DataFrame, pressure: pd.DataFrame, subject: str,
                            opponent: str) -> dict[str, Any]:
    teams = (subject, opponent)
    colour = {subject: palette.CHARLTON_RED, opponent: palette.OPPONENT_GREY}
    oriented = orient_duels(duels, events)

    # one colour scale for both teams' pressure maps: peak of the smoothed counts over either team
    peak = max(pressure_heatmap(pressure, t, 0.0)[1] for t in teams)
    summaries = {t: pressing_summary(pressure, events, t) for t in teams}
    regain = {t: regain_summary(events, t) for t in teams}
    return {
        "regain_img": {t: regain_map_chart(regain[t]) for t in teams},
        "regain_players_img": {t: regain_players_chart(regain[t]) for t in teams},
        "regain_ctx": {t: {k: v for k, v in regain[t].items() if k not in ("frame", "players")} for t in teams},
        "duel_totals": {t: duel_totals(oriented, t) for t in teams},
        "duel_map_img": {t: {k: duel_map_chart(oriented, t, k, colour[t]) for k, _ in DUEL_TYPES} for t in teams},
        "pressure_heat_img": {t: pressure_heatmap(pressure, t, peak)[0] for t in teams},
        "pressing_img": {t: pressing_chart(summaries[t], colour[t]) for t in teams},
        "pressing_kpis": {t: {"n": s["n"], "forced": s["forced"], "forced_pct": s["forced_pct"],
                              "opp_half": s["opp_half"], "opp_third": s["opp_third"],
                              "per_min": round(s["n"] / 90, 1)} for t, s in summaries.items()},
    }

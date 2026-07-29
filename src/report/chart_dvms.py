"""Tracking-native charts for the DVMS board report.

Only what the IMPECT chart module can't draw lives here; everything else
(chance-source bars) is reused from ``chart.py``.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.report import palette  # noqa: E402
from src.report.chart import _fig_to_uri  # noqa: E402


def territory_chart(wave: pd.DataFrame, goals: list[dict],
                    charlton_team: str, opponent_team: str,
                    figsize=(16.0, 3.5)) -> str:
    """Field tilt from tracking: rolling mean ball position, in metres.

    The momentum chart's replacement, and unlike a threat-model wave the
    y-axis needs no apology: +20m literally means the ball spent the window
    averaging 20 metres inside the opposition half. Linear axis (territory is
    bounded, there are no goal-sized spikes to tame), Charlton shaded above
    the line, opponent below, goals marked on the timeline.
    """
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(palette.PAPER)
    ax.set_facecolor(palette.PAPER)

    x = wave["minute"].to_numpy()
    y = wave["territory_m"].to_numpy()
    peak = max(float(np.abs(y).max()), 5.0)

    ax.fill_between(x, y, 0, where=y >= 0, interpolate=True,
                    color=palette.CHARLTON_RED, alpha=0.90, linewidth=0, zorder=3)
    ax.fill_between(x, y, 0, where=y <= 0, interpolate=True,
                    color=palette.OPPONENT_GREY, alpha=0.85, linewidth=0, zorder=3)
    ax.plot(x, y, color=palette.INK, linewidth=0.7, alpha=0.35, zorder=4)
    ax.axhline(0, color=palette.INK, linewidth=1.0, zorder=5)
    ax.axvline(45, color=palette.HAIR, linewidth=1.0, linestyle=(0, (3, 3)), zorder=1)

    halo = [pe.withStroke(linewidth=2.6, foreground=palette.PAPER)]
    lane = peak * 1.45
    for g in goals:
        is_cha = g["team"] == charlton_team
        color = palette.CHARLTON_RED if is_cha else palette.OPPONENT_GREY
        gy = lane if is_cha else -lane
        curve_y = float(np.interp(g["minute"], x, y))
        ax.plot([g["minute"], g["minute"]], [curve_y, gy], color=color,
                linewidth=0.8, linestyle=(0, (1, 1.6)), alpha=0.5, zorder=4)
        ax.scatter([g["minute"]], [gy], s=95, facecolor=color,
                   edgecolors=palette.INK, linewidth=1.7, zorder=6)
        ax.annotate(g["label"], (g["minute"], gy), xytext=(7, 0),
                    textcoords="offset points", ha="left", va="center",
                    fontsize=9.2, fontweight="bold", color=palette.INK,
                    zorder=7, path_effects=halo)

    ax.set_ylim(-peak * 1.9, peak * 1.9)
    ax.set_xlim(0, max(float(x.max()), 90))
    ax.set_xticks([0, 15, 30, 45, 60, 75, 90])
    ax.set_xticklabels(["0'", "15'", "30'", "HT", "60'", "75'", "90'"])
    ax.tick_params(axis="x", labelsize=10.5, colors=palette.MUTED, length=0, pad=6)

    ticks = [t for t in (-20, -10, 0, 10, 20) if abs(t) <= peak * 1.1]
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"+{t}m" if t > 0 else (f"{t}m" if t else "0")
                        for t in ticks])
    ax.set_ylabel("Ball territory\n(tracked)", fontsize=9.4, color=palette.MUTED,
                  linespacing=1.5)
    ax.tick_params(axis="y", labelsize=9, colors=palette.MUTED)
    ax.grid(axis="y", color=palette.HAIR, linewidth=0.5, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(palette.HAIR)

    for txt, col, y_at, va in (
        (charlton_team, palette.CHARLTON_RED, peak * 1.82, "top"),
        (opponent_team, palette.OPPONENT_GREY, -peak * 1.82, "bottom"),
    ):
        ax.annotate(txt.upper(), (1.0, y_at), fontsize=8.6, fontweight="bold",
                    color=col, va=va, ha="left", zorder=5)
    return _fig_to_uri(fig)

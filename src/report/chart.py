"""Non-pitch charts: the momentum wave and the expected-threat bars. Same
matplotlib/Agg -> base64 PNG convention as pitch.py.
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from src.report import palette  # noqa: E402


def _fig_to_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=240, bbox_inches="tight", pad_inches=0.04,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def momentum_chart(
    wave: pd.DataFrame,
    events: list,
    charlton_team: str,
    opponent_team: str,
    figsize=(16.0, 3.5),
) -> str:
    """Rolling net packing expected threat: Charlton above the line in red, the
    opponent below it in grey, with goals, cards and substitutions on the
    timeline.

    The y-axis is real and it is labelled, because the underlying series is a
    plain rolling *sum* of ``PXT_ATTACK`` and so is still in pxT units — the
    height of the curve is the net packing xT a side created in the surrounding
    five minutes, which is a sentence you can say to a board. That honesty is
    exactly why the metric is a rolling sum and not something cleverer: a
    transformed, kernel-smoothed wave looks better and has no units, and a y-axis
    that looks authoritative while meaning nothing is the worst of both.
    """
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(palette.PAPER)
    ax.set_facecolor(palette.PAPER)

    x, y = wave["minute"].to_numpy(), wave["momentum"].to_numpy()
    peak = max(float(abs(y).max()), 1e-6)

    ax.fill_between(x, y, 0, where=y >= 0, interpolate=True, color=palette.CHARLTON_RED,
                    alpha=0.90, linewidth=0, zorder=3)
    ax.fill_between(x, y, 0, where=y <= 0, interpolate=True, color=palette.OPPONENT_GREY,
                    alpha=0.85, linewidth=0, zorder=3)
    ax.plot(x, y, color=palette.INK, linewidth=0.7, alpha=0.35, zorder=4)
    ax.axhline(0, color=palette.INK, linewidth=1.0, zorder=5)
    ax.axvline(45, color=palette.HAIR, linewidth=1.0, linestyle=(0, (3, 3)), zorder=1)

    # Event markers ride in a lane above the wave for Charlton and below it for
    # the opponent, so which side an icon belongs to needs no legend. No stems
    # down to the axis: they turned the chart into a row of lollipops and fought
    # with the wave, which is the thing you are meant to be looking at. A fine
    # dotted lead line ties each marker back to the wave's own value at that
    # minute — the lane height is fixed so markers never collide with a tall
    # peak, which otherwise leaves nothing but the shared x-position saying
    # "this happened here"; the connector makes that link visible without
    # moving the marker off its lane.
    lane = peak * 1.75
    halo = [pe.withStroke(linewidth=2.6, foreground=palette.PAPER)]
    for e in events:
        is_cha = e.team == charlton_team
        color = palette.CHARLTON_RED if is_cha else palette.OPPONENT_GREY
        ey = lane if is_cha else -lane

        curve_y = float(np.interp(e.minute, x, y))
        ax.plot([e.minute, e.minute], [curve_y, ey], color=color, linewidth=0.8,
                linestyle=(0, (1, 1.6)), alpha=0.5, zorder=4)

        if e.kind == "goal":
            ax.scatter([e.minute], [ey], s=95, facecolor=color, edgecolors=palette.INK,
                       linewidth=1.7, zorder=6)
            ax.annotate(e.label, (e.minute, ey), xytext=(7, 0), textcoords="offset points",
                        ha="left", va="center", fontsize=9.2, fontweight="bold", color=palette.INK,
                        zorder=7, path_effects=halo)
        elif e.kind == "sub":
            ax.scatter([e.minute], [ey], s=40, marker="^", facecolor=palette.PAPER,
                       edgecolors=color, linewidth=1.1, zorder=5)
        else:  # yellow / red card
            card = palette.AMBER if e.kind == "yellow" else palette.CHARLTON_RED
            ax.add_patch(Rectangle((e.minute - 0.55, ey - peak * 0.11), 1.1, peak * 0.22,
                                   facecolor=card, edgecolor=palette.INK, linewidth=0.7, zorder=6))

    ax.set_ylim(-peak * 2.4, peak * 2.4)   # generous: the sqrt scale compresses the top
    ax.set_xlim(0, max(float(x.max()), 90))
    ax.set_xticks([0, 15, 30, 45, 60, 75, 90])
    ax.set_xticklabels(["0'", "15'", "30'", "HT", "60'", "75'", "90'"])
    ax.tick_params(axis="x", labelsize=10.5, colors=palette.MUTED, length=0, pad=6)

    # A symmetric square-root *scale*, not a transformed *series*. The distinction
    # is the whole ballgame. pxT is dominated by shots — a goal is worth roughly
    # ten times an ordinary five-minute window — so on a linear axis the quiet
    # spells are crushed flat against zero. Rescaling the axis stretches those
    # spells open while leaving every underlying number exactly as it was: the
    # ticks are still real pxT, and no team can overtake another because a
    # monotonic axis cannot reorder anything.
    #
    # The alternatives were tried and are worse. Capping the big events inverts
    # the match (it deletes the very shot value that made Swansea dominant), and
    # dropping shots from the series inverts it harder still: Charlton did more
    # build-up work, Swansea turned theirs into shots, so a shots-free momentum
    # chart reports Charlton +0.740 to Swansea +0.239 and is simply false.
    ax.set_yscale("function", functions=(
        lambda v: np.sign(v) * np.sqrt(np.abs(v)),
        lambda v: np.sign(v) * v ** 2,
    ))
    # Sparse ticks on purpose: a square-root axis crowds its labels near zero, and
    # this is a chart you read the shape of, with the numbers there for scale.
    candidates = np.array([0.05, 0.2, 0.8])
    mags = [m for m in candidates if m <= peak * 1.05]
    ticks = [-m for m in reversed(mags)] + [0.0] + mags
    ax.set_yticks(ticks)
    ax.set_yticklabels([f"{abs(t):g}" if t else "0" for t in ticks])
    ax.set_ylabel("Net packing\nexpected threat", fontsize=9.4, color=palette.MUTED,
                  linespacing=1.5)
    ax.tick_params(axis="y", labelsize=9, colors=palette.MUTED)
    ax.grid(axis="y", color=palette.HAIR, linewidth=0.5, alpha=0.6, zorder=0)
    ax.set_axisbelow(True)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(palette.HAIR)

    for txt, col, y_at, va in (
        (charlton_team, palette.CHARLTON_RED, peak * 2.3, "top"),
        (opponent_team, palette.OPPONENT_GREY, -peak * 2.3, "bottom"),
    ):
        ax.annotate(txt.upper(), (1.0, y_at), fontsize=8.6, fontweight="bold", color=col,
                    va=va, ha="left", zorder=5)
    return _fig_to_uri(fig)


def chance_source_bars(df: pd.DataFrame, charlton_team: str, opponent_team: str,
                       figsize=(4.4, 3.5)) -> str:
    """Non-penalty xG by the phase of play that created it, one red bar and one
    grey bar per phase.

    Grouped rather than stacked, despite "stacked" being the natural way to say
    it. A stacked bar needs a colour per phase, and every colour on this page
    already means something — red *is* Charlton and grey *is* the opponent, on
    every table, map and chart. Introducing a second, competing colour language
    for four phases in one small panel would cost more than the stacking gains,
    and grouped bars answer the same question ("where did the chances come
    from?") while also answering "and how does that compare to theirs?", which
    stacking makes harder, not easier.
    """
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(palette.PAPER)
    ax.set_facecolor(palette.PAPER)

    phases = list(df.index)[::-1]          # first phase at the top
    y = np.arange(len(phases))
    cha = df.loc[phases, charlton_team].to_numpy()
    opp = df.loc[phases, opponent_team].to_numpy()

    ax.barh(y + 0.19, cha, height=0.34, color=palette.CHARLTON_RED, zorder=3)
    ax.barh(y - 0.19, opp, height=0.34, color=palette.OPPONENT_GREY, zorder=3)

    top = max(float(max(cha.max(), opp.max())), 0.05)
    for yi, v in zip(y + 0.19, cha):
        ax.text(v + top * 0.03, yi, f"{v:.2f}", va="center", fontsize=8.6,
                fontweight="bold", color=palette.CHARLTON_RED)
    for yi, v in zip(y - 0.19, opp):
        ax.text(v + top * 0.03, yi, f"{v:.2f}", va="center", fontsize=8.6,
                fontweight="bold", color=palette.OPPONENT_GREY)

    ax.set_yticks(y)
    ax.set_yticklabels(phases, fontsize=9.4)
    ax.tick_params(axis="y", length=0, colors=palette.INK)
    ax.set_xlim(0, top * 1.30)
    ax.set_xticks([])
    ax.set_xlabel("Non-penalty xG", fontsize=9, color=palette.MUTED)
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(palette.HAIR)
    ax.set_axisbelow(True)
    return _fig_to_uri(fig)

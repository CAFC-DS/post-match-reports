"""Delivery-map graphics for the set-piece report.

Two vertical pitches per team, drawn in the active :class:`~set_piece_report.
theme.Theme` so the artwork sits on the same paper as the page (cream in light
mode, charcoal in dark mode):

* :func:`corner_overview`    – attacking-box view, one arrow per corner coloured
  by IMPECT corner type (near post / central / far post / short), the landing
  spot ringed when the attacking team won the first contact.
* :func:`corner_zone_overview` – a 6-cell target-zone grid shaded / labelled by
  how many deliveries landed in each zone.
* :func:`free_kick_overview` – full pitch, indirect free-kick deliveries as
  arrows over a soft threat heatmap of where they land.

Figures are returned as base64-encoded PNG ``data:`` URIs ready to drop into the
HTML/PDF template.
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from mplsoccer import VerticalPitch  # noqa: E402

from set_piece_report.theme import LIGHT, Theme  # noqa: E402

# IMPECT adjusted coords: X in [-52.5, 52.5] (attacking goal at +52.5),
# Y in [-34, 34]. Shift into a 105 x 68 "custom" pitch.
_HALF_LEN, _HALF_WID = 52.5, 34.0
_PITCH_LEN, _PITCH_WID = 105.0, 68.0


def _to_pitch(x, y):
    px = pd.to_numeric(pd.Series(x), errors="coerce") + _HALF_LEN
    py = pd.to_numeric(pd.Series(y), errors="coerce") + _HALF_WID
    return px, py


def _fig_to_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(
        buf, format="png", dpi=240, bbox_inches="tight",
        pad_inches=0.05, facecolor=fig.get_facecolor(),
    )
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _pitch(theme: Theme, half: bool, pad_bottom: float, figsize) -> tuple:
    pitch = VerticalPitch(
        pitch_type="custom",
        pitch_length=_PITCH_LEN,
        pitch_width=_PITCH_WID,
        half=half,
        pad_top=1,
        pad_bottom=pad_bottom,
        pad_left=1,
        pad_right=1,
        pitch_color=theme.pitch_surface,
        line_color=theme.pitch_line,
        linewidth=1.0,
        line_zorder=1,
        goal_type="line",
        goal_alpha=0.9,
        corner_arcs=True,
    )
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(theme.pitch_surface)
    return pitch, fig, ax


def _danger_cmap(theme: Theme) -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list("sp_heat", list(theme.heat_stops))


def _goal_star(pitch, ax, theme, x, y, s):
    pitch.scatter(x, y, ax=ax, s=s, marker="*", color=theme.goal,
                  edgecolors=theme.goal_edge, linewidth=0.9, zorder=6)


def _markers_ring(pitch, ax, theme, ex, ey, fills, outcome, goals,
                  *, circle=64, star=190):
    """Delivery end markers: fill = category (landing zone / type / length),
    **ring colour = outcome** (won-or-retained → green, lost → red, uncontested →
    grey), and a star when it led to a goal."""
    ring = {"won": theme.edge_won, "lost": theme.edge_lost}
    ex = list(ex); ey = list(ey); fills = list(fills)
    outcome = list(outcome); goals = list(goals)
    for i in range(len(ex)):
        if goals[i]:
            _goal_star(pitch, ax, theme, ex[i], ey[i], star)
        else:
            pitch.scatter(ex[i], ey[i], ax=ax, s=circle, marker="o", color=fills[i],
                          edgecolors=ring.get(outcome[i], theme.edge_none),
                          linewidth=1.9, zorder=5)


def _attack_arrow(theme, ax, lo=0.06, hi=0.94):
    """A direction arrow drawn *outside* the pitch (to its left), spanning the
    pitch length and pointing at the attacked goal, labelled 'attacking'."""
    ax.annotate(
        "", xy=(-0.055, hi), xytext=(-0.055, lo), xycoords="axes fraction",
        annotation_clip=False,
        arrowprops=dict(arrowstyle="-|>", color=theme.red, lw=1.6,
                        shrinkA=0, shrinkB=0, mutation_scale=9),
    )
    ax.text(-0.11, (lo + hi) / 2, "attacking", rotation=90, transform=ax.transAxes,
            fontsize=5, color=theme.muted, va="center", ha="center",
            fontweight="bold", clip_on=False)


# --------------------------------------------------------------------------- #
# Corner overview
# --------------------------------------------------------------------------- #
def corner_overview(deliveries: pd.DataFrame, theme: Theme = LIGHT) -> str:
    """Attacking corner delivery map: soft danger zones under the arrows."""
    # Crop to roughly the final 32m so the box fills the frame (landscape).
    pitch, fig, ax = _pitch(theme, half=True, pad_bottom=-20.5, figsize=(5.2, 3.2))

    if deliveries is not None and not deliveries.empty:
        d = deliveries.reset_index(drop=True)
        sx, sy = _to_pitch(d["startAdjCoordinatesX"], d["startAdjCoordinatesY"])
        ex, ey = _to_pitch(d["endAdjCoordinatesX"], d["endAdjCoordinatesY"])
        valid = ex.notna() & ey.notna()
        if valid.sum() >= 4:
            try:
                pitch.kdeplot(
                    ex[valid], ey[valid], ax=ax, fill=True, levels=30,
                    thresh=0.15, cmap=_danger_cmap(theme), alpha=0.30, zorder=1,
                )
            except Exception:
                pass
        fills = [theme.corner_colors.get(t, theme.red) for t in d["corner_type"]]
        for i in range(len(d)):
            pitch.lines(
                sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax,
                color=fills[i], lw=2.4, comet=True, alpha=0.9, zorder=3,
                capstyle="round",
            )
        _markers_ring(pitch, ax, theme, ex, ey, fills, d["first_touch"], d["led_to_goal"])
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN - 16, "No attacking corners",
            ha="center", va="center", color=theme.muted, fontsize=9,
        )
    _attack_arrow(theme, ax)
    return _fig_to_uri(fig)


# Zone grid over the penalty area (length = depth from goal, width thirds).
_ZONE_X = np.array([88.5, 99.5, 105.0])                 # deep box, then 6-yard
_ZONE_Y = np.array([13.85, 27.28, 40.72, 54.15])        # left / central / right


def corner_zone_overview(deliveries: pd.DataFrame, theme: Theme = LIGHT) -> str:
    """Attacking corner *target zones*: a 6-cell box grid shaded and labelled by
    how many deliveries landed in each zone."""
    pitch, fig, ax = _pitch(theme, half=True, pad_bottom=-20.5, figsize=(5.2, 3.2))

    ex = ey = None
    if deliveries is not None and not deliveries.empty:
        ex, ey = _to_pitch(deliveries["endAdjCoordinatesX"], deliveries["endAdjCoordinatesY"])
        valid = ex.notna() & ey.notna()
        ex, ey = ex[valid], ey[valid]

    if ex is not None and len(ex):
        stat = pitch.bin_statistic(ex, ey, statistic="count", bins=(_ZONE_X, _ZONE_Y))
        grid = np.array(stat["statistic"], dtype=float)
        shaded = grid.copy()
        shaded[shaded == 0] = np.nan          # empty zones stay pitch-coloured
        stat["statistic"] = shaded
        pitch.heatmap(stat, ax=ax, cmap=_danger_cmap(theme), alpha=0.62,
                      edgecolors=theme.pitch_surface, lw=1.2, zorder=1)
        labels = stat.copy()
        labels["statistic"] = grid            # keep zeros; exclude_zeros hides them
        pitch.label_heatmap(labels, ax=ax, str_format="{:.0f}", color=theme.ink,
                            fontsize=11, fontweight="bold", zorder=3,
                            ha="center", va="center", exclude_zeros=True)
    else:
        ax.text(_PITCH_WID / 2, _PITCH_LEN - 16, "No attacking corners",
                ha="center", va="center", color=theme.muted, fontsize=9)
    _attack_arrow(theme, ax)
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Free-kick overview  (indirect deliveries + direct free-kick attempts)
# --------------------------------------------------------------------------- #
def free_kick_overview(deliveries: pd.DataFrame, theme: Theme = LIGHT) -> str:
    """Free-kick map: indirect deliveries over a threat heatmap, with direct
    free-kicks (shots) drawn in their own colour."""
    pitch, fig, ax = _pitch(theme, half=False, pad_bottom=1, figsize=(3.9, 5.4))

    if deliveries is not None and not deliveries.empty:
        d = deliveries.reset_index(drop=True)
        ex, ey = _to_pitch(d["endAdjCoordinatesX"], d["endAdjCoordinatesY"])
        sx, sy = _to_pitch(d["startAdjCoordinatesX"], d["startAdjCoordinatesY"])
        indirect = (d["fk_group"] != "DIRECT")
        valid_end = ex.notna() & ey.notna() & indirect
        if valid_end.sum() >= 5:
            try:
                pitch.kdeplot(
                    ex[valid_end], ey[valid_end], ax=ax, fill=True, levels=40,
                    thresh=0.12, cmap=_danger_cmap(theme), alpha=0.32, zorder=1,
                )
            except Exception:
                pass
        fills = [theme.fk_colors.get(g, theme.muted) for g in d["fk_group"]]
        for i in range(len(d)):
            recycle = d["fk_group"].iloc[i] == "SHORT"
            direct = d["fk_group"].iloc[i] == "SHOT"
            pitch.lines(
                sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax,
                color=fills[i], lw=2.2 if direct else 1.8, comet=True,
                alpha=0.5 if recycle else 0.9, zorder=3, capstyle="round",
                linestyle="--" if direct else "-",
            )
        _markers_ring(pitch, ax, theme, ex, ey, fills, d["first_touch"], d["led_to_goal"],
                      circle=50, star=165)
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN / 2, "No free-kicks",
            ha="center", va="center", color=theme.muted, fontsize=9,
        )
    _attack_arrow(theme, ax)
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Throw-in overview
# --------------------------------------------------------------------------- #
def throw_in_overview(deliveries: pd.DataFrame, theme: Theme = LIGHT) -> str:
    """Valid throw-ins, distinguishing box throws from all other throws."""
    pitch, fig, ax = _pitch(theme, half=False, pad_bottom=1, figsize=(3.9, 5.4))

    if deliveries is not None and not deliveries.empty:
        d = deliveries.reset_index(drop=True)
        ex, ey = _to_pitch(d["endAdjCoordinatesX"], d["endAdjCoordinatesY"])
        sx, sy = _to_pitch(d["startAdjCoordinatesX"], d["startAdjCoordinatesY"])
        fills = [theme.throw_colors.get(g, theme.muted) for g in d["throw_group"]]
        for i in range(len(d)):
            other = d["throw_group"].iloc[i] == "OTHER_THROW"
            pitch.lines(
                sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax,
                color=fills[i], lw=1.6, comet=True,
                alpha=0.55 if other else 0.9, zorder=3, capstyle="round",
            )
        _markers_ring(pitch, ax, theme, ex, ey, fills, d["first_touch"], d["led_to_goal"],
                      circle=54, star=165)
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN / 2, "No throw-ins",
            ha="center", va="center", color=theme.muted, fontsize=9,
        )
    _attack_arrow(theme, ax)
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Legend swatches (colours come from the active theme so they match the artwork)
# --------------------------------------------------------------------------- #
def corner_legend_items(theme: Theme = LIGHT) -> list[tuple[str, str]]:
    from set_piece_report.config import CORNER_TYPE_LABELS, CORNER_TYPE_ORDER

    return [(CORNER_TYPE_LABELS[t], theme.corner_colors[t]) for t in CORNER_TYPE_ORDER]


def fk_legend_items(theme: Theme = LIGHT) -> list[tuple[str, str]]:
    labels = {
        "CROSS": "Cross",
        "HIGH_BALL": "High ball",
        "SHORT": "Short",
        "SHOT": "Shot",
    }
    return [(labels[k], theme.fk_colors[k]) for k in labels]


def throw_legend_items(theme: Theme = LIGHT) -> list[tuple[str, str]]:
    return [("Into box", theme.throw_colors["BOX_THROW"]),
            ("Other", theme.throw_colors["OTHER_THROW"])]

"""Delivery-map graphics for the set-piece report.

Two vertical pitches per team, drawn in the cream / editorial palette:

* :func:`corner_overview`   – attacking-box view, one arrow per corner coloured
  by IMPECT corner type (near post / central / far post / short), the landing
  spot ringed when the attacking team won the first contact.
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

from set_piece_report.config import (
    CORNER_TYPE_COLORS,
    FK_TYPE_COLORS,
    INK,
    MUTED,
    PITCH_LINE,
    PITCH_SURFACE,
    RED,
)

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


def _pitch(half: bool, pad_bottom: float, figsize) -> tuple:
    pitch = VerticalPitch(
        pitch_type="custom",
        pitch_length=_PITCH_LEN,
        pitch_width=_PITCH_WID,
        half=half,
        pad_top=1,
        pad_bottom=pad_bottom,
        pad_left=1,
        pad_right=1,
        pitch_color=PITCH_SURFACE,
        line_color=PITCH_LINE,
        linewidth=1.0,
        line_zorder=1,
        goal_type="line",
        goal_alpha=0.9,
        corner_arcs=True,
    )
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(PITCH_SURFACE)
    return pitch, fig, ax


# --------------------------------------------------------------------------- #
# Corner overview
# --------------------------------------------------------------------------- #
def _danger_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list(
        "sp_heat", [PITCH_SURFACE, "#EAD6A6", "#DCA23F", "#C0522B"]
    )


def corner_overview(deliveries: pd.DataFrame) -> str:
    """Attacking corner delivery map: soft danger zones under the arrows."""
    # Crop to roughly the final 32m so the box fills the frame (landscape).
    pitch, fig, ax = _pitch(half=True, pad_bottom=-20.5, figsize=(5.2, 3.2))

    if deliveries is not None and not deliveries.empty:
        sx, sy = _to_pitch(deliveries["startAdjCoordinatesX"], deliveries["startAdjCoordinatesY"])
        ex, ey = _to_pitch(deliveries["endAdjCoordinatesX"], deliveries["endAdjCoordinatesY"])
        # danger-zone shading = where deliveries land (needs a few points to be stable)
        valid = ex.notna() & ey.notna()
        if valid.sum() >= 4:
            try:
                pitch.kdeplot(
                    ex[valid], ey[valid], ax=ax, fill=True, levels=30,
                    thresh=0.15, cmap=_danger_cmap(), alpha=0.30, zorder=1,
                )
            except Exception:
                pass
        for i, (_, row) in enumerate(deliveries.reset_index(drop=True).iterrows()):
            colour = CORNER_TYPE_COLORS.get(row["corner_type"], RED)
            pitch.lines(
                sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax,
                color=colour, lw=2.4, comet=True, alpha=0.9, zorder=3,
                capstyle="round",
            )
            won = row["first_touch"] == "won"
            pitch.scatter(
                ex.iloc[i], ey.iloc[i], ax=ax, s=64 if won else 42, color=colour,
                edgecolors="#FFFFFF" if won else PITCH_SURFACE,
                linewidth=1.4 if won else 0.7, zorder=4,
            )
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN - 16, "No attacking corners",
            ha="center", va="center", color=MUTED, fontsize=9,
        )
    return _fig_to_uri(fig)


# Zone grid over the penalty area (length = depth from goal, width thirds).
_ZONE_X = np.array([88.5, 99.5, 105.0])                 # deep box, then 6-yard
_ZONE_Y = np.array([13.85, 27.28, 40.72, 54.15])        # left / central / right


def corner_zone_overview(deliveries: pd.DataFrame) -> str:
    """Attacking corner *target zones*: a 6-cell box grid shaded and labelled by
    how many deliveries landed in each zone."""
    pitch, fig, ax = _pitch(half=True, pad_bottom=-20.5, figsize=(5.2, 3.2))

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
        pitch.heatmap(stat, ax=ax, cmap=_danger_cmap(), alpha=0.62,
                      edgecolors=PITCH_SURFACE, lw=1.2, zorder=1)
        labels = stat.copy()
        labels["statistic"] = grid            # keep zeros; exclude_zeros hides them
        pitch.label_heatmap(labels, ax=ax, str_format="{:.0f}", color=INK,
                            fontsize=11, fontweight="bold", zorder=3,
                            ha="center", va="center", exclude_zeros=True)
    else:
        ax.text(_PITCH_WID / 2, _PITCH_LEN - 16, "No attacking corners",
                ha="center", va="center", color=MUTED, fontsize=9)
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Free-kick overview
# --------------------------------------------------------------------------- #
def free_kick_overview(deliveries: pd.DataFrame) -> str:
    """Indirect free-kick delivery map over a soft landing-zone heatmap."""
    pitch, fig, ax = _pitch(half=False, pad_bottom=1, figsize=(4.2, 5.6))

    if deliveries is not None and not deliveries.empty:
        ex, ey = _to_pitch(deliveries["endAdjCoordinatesX"], deliveries["endAdjCoordinatesY"])
        sx, sy = _to_pitch(deliveries["startAdjCoordinatesX"], deliveries["startAdjCoordinatesY"])
        valid_end = ex.notna() & ey.notna()
        if valid_end.sum() >= 5:
            try:
                pitch.kdeplot(
                    ex[valid_end], ey[valid_end], ax=ax, fill=True, levels=40,
                    thresh=0.12, cmap=_danger_cmap(), alpha=0.32, zorder=1,
                )
            except Exception:
                pass
        for i, (_, row) in enumerate(deliveries.reset_index(drop=True).iterrows()):
            colour = FK_TYPE_COLORS.get(row["fk_group"], MUTED)
            recycle = row["fk_group"] == "INTO_POSSESSION"
            pitch.lines(
                sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax,
                color=colour, lw=1.8, comet=True,
                alpha=0.45 if recycle else 0.85, zorder=3, capstyle="round",
            )
            won = row["first_touch"] == "won"
            pitch.scatter(
                ex.iloc[i], ey.iloc[i], ax=ax, s=44 if won else 24, color=colour,
                edgecolors="#FFFFFF" if won else PITCH_SURFACE,
                linewidth=1.2 if won else 0.6,
                alpha=0.5 if recycle else 1.0, zorder=4,
            )
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN / 2, "No indirect free-kicks",
            ha="center", va="center", color=MUTED, fontsize=9,
        )
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Set-piece shot map
# --------------------------------------------------------------------------- #
_SHOT_NONGOAL = "#7F8DA3"


def _shot_sizes(xg: pd.Series) -> pd.Series:
    clean = pd.to_numeric(xg, errors="coerce").fillna(0.03).clip(lower=0.01, upper=0.6)
    return 34 + (clean / 0.6) * 300


def set_piece_shot_map(shots: pd.DataFrame) -> str:
    """Half-pitch of shots created from set-pieces; dot size = xG, goals in red."""
    pitch, fig, ax = _pitch(half=True, pad_bottom=-16, figsize=(5.0, 3.4))

    if shots is not None and not shots.empty:
        sx, sy = _to_pitch(shots["startAdjCoordinatesX"], shots["startAdjCoordinatesY"])
        sizes = _shot_sizes(shots["SHOT_XG"]).reset_index(drop=True)
        goal = shots["is_goal"].reset_index(drop=True)
        sx = sx.reset_index(drop=True)
        sy = sy.reset_index(drop=True)
        if (~goal).any():
            pitch.scatter(
                sx[~goal], sy[~goal], ax=ax, s=sizes[~goal], color=_SHOT_NONGOAL,
                edgecolors=PITCH_SURFACE, linewidth=0.7, alpha=0.8, zorder=3,
            )
        if goal.any():
            # goals always read clearly, even from a low-xG finish
            goal_sizes = sizes[goal].clip(lower=110)
            pitch.scatter(
                sx[goal], sy[goal], ax=ax, s=goal_sizes, color=RED, marker="o",
                edgecolors="#FFFFFF", linewidth=1.6, zorder=5,
            )
    else:
        ax.text(
            _PITCH_WID / 2, _PITCH_LEN - 12, "No set-piece shots",
            ha="center", va="center", color=MUTED, fontsize=9,
        )
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Legend swatches (kept here so colours have one source of truth)
# --------------------------------------------------------------------------- #
def shot_legend_items() -> list[tuple[str, str]]:
    return [("Shot (size = xG)", _SHOT_NONGOAL), ("Goal", RED)]


def corner_legend_items() -> list[tuple[str, str]]:
    from set_piece_report.config import CORNER_TYPE_LABELS, CORNER_TYPE_ORDER

    return [(CORNER_TYPE_LABELS[t], CORNER_TYPE_COLORS[t]) for t in CORNER_TYPE_ORDER]


def fk_legend_items() -> list[tuple[str, str]]:
    labels = {
        "CROSS": "Cross / box",
        "HIGH_BALL": "High ball",
        "INTO_POSSESSION": "Into possession",
        "OTHER": "Other",
    }
    return [(labels[k], FK_TYPE_COLORS[k]) for k in labels]

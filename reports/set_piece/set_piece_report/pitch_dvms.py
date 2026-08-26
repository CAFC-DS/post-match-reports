"""Corner freeze-frame graphic — the tracking-data panel with no IMPECT
counterpart: all 22 players and the ball at the instant the corner was struck.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import pandas as pd  # noqa: E402
from mplsoccer import VerticalPitch  # noqa: E402

from set_piece_report.pitch import _fig_to_uri  # noqa: E402
from set_piece_report.theme import LIGHT, Theme  # noqa: E402


def corner_freeze_frame(frame: pd.DataFrame, meta, attacking_side: str,
                        attacking_color: str, numbers: dict[str, int] | None = None,
                        theme: Theme = LIGHT, figsize=(4.6, 4.2)) -> str:
    """Half-pitch snapshot at delivery: attackers filled, defenders hollow.

    ``frame`` is the tracking rows of one frame (players + ball), raw
    pitch-centred metres. The half shown is wherever the ball is — the corner
    is by definition in the attacked half, so orient so that half is up.
    """
    pitch = VerticalPitch(
        pitch_type="custom", pitch_length=meta.pitch_length,
        pitch_width=meta.pitch_width, half=True,
        pitch_color=theme.pitch_surface, line_color=theme.pitch_line,
        linewidth=1.0, goal_type="line", pad_bottom=2,
    )
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(theme.pitch_surface)
    if frame is None or frame.empty:
        return _fig_to_uri(fig)

    ball = frame[frame["team"] == "ball"]
    # Flip so the ball's half is the shown (upper) half.
    flip = not ball.empty and float(ball.iloc[0]["x"]) < 0
    sign = -1.0 if flip else 1.0

    half_l, half_w = meta.pitch_length / 2.0, meta.pitch_width / 2.0

    def to_draw(rows: pd.DataFrame):
        return (sign * rows["x"].astype(float) + half_l,
                sign * rows["y"].astype(float) + half_w)

    halo = [pe.withStroke(linewidth=2.0, foreground=theme.pitch_surface)]
    for side in ("home", "away"):
        rows = frame[frame["team"] == side]
        if rows.empty:
            continue
        x, y = to_draw(rows)
        attacking = side == attacking_side
        pitch.scatter(
            x, y, ax=ax, s=150,
            color=attacking_color if attacking else theme.pitch_surface,
            edgecolors=theme.ink, linewidth=1.2, zorder=4 if attacking else 3,
        )
        for xi, yi, num in zip(x, y, rows["number"]):
            if num == num and num is not None:
                ax.annotate(
                    f"{int(num)}", (yi, xi), ha="center", va="center", zorder=6,
                    fontsize=5.6, fontweight="bold",
                    color=("#ffffff" if attacking else theme.ink),
                    path_effects=halo if not attacking else None,
                )

    if not ball.empty:
        bx, by = to_draw(ball)
        pitch.scatter(bx, by, ax=ax, s=48, color=theme.ink,
                      edgecolors=theme.pitch_surface, linewidth=1.2, zorder=7)
    return _fig_to_uri(fig)

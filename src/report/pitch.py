"""Pitch graphics: passing networks, shot maps and final-third / box entry
maps. Matplotlib (Agg backend) via mplsoccer, returned as base64 PNG data URIs,
matching the convention already used in set-piece-report.

Coordinate system: IMPECT adjusted coordinates, X in [-52.5, 52.5] (attacking
goal at +52.5), Y in [-34, 34] — a 105 x 68 pitch centred on the halfway line.
mplsoccer's ``pitch_type="custom"`` pitch is 0..105 / 0..68, so every x/y pair
is shifted by the half-length / half-width before plotting.

Every map on the page attacks in the same direction (left to right on the
landscape pitches, upwards on the shot maps) for both teams, so the two halves
of a pair can be compared without mentally flipping one of them.
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
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from mplsoccer import Pitch, VerticalPitch  # noqa: E402

from src.report import palette  # noqa: E402
from src.report.metrics import PassingNetwork  # noqa: E402

_HALF_LEN, _HALF_WID = 52.5, 34.0
_PITCH_LEN, _PITCH_WID = 105.0, 68.0

_LABEL_FONT = "DejaVu Sans"


def _to_pitch(x, y):
    return pd.Series(x) + _HALF_LEN, pd.Series(y) + _HALF_WID


def _fig_to_uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=240, bbox_inches="tight", pad_inches=0.02,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _pitch_kwargs() -> dict:
    return dict(
        pitch_type="custom",
        pitch_length=_PITCH_LEN,
        pitch_width=_PITCH_WID,
        pitch_color=palette.PAPER_2,
        line_color=palette.HAIR,
        linewidth=1.0,
        line_zorder=1,
        goal_type="line",
    )


def _horizontal_pitch(figsize):
    pitch = Pitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_pitch_kwargs())
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(palette.PAPER_2)
    return pitch, fig, ax


def _vertical_pitch(figsize):
    pitch = VerticalPitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_pitch_kwargs())
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(palette.PAPER_2)
    return pitch, fig, ax


def _half_pitch(figsize):
    # A little pad_bottom, not a lot: enough that a shot struck from distance has
    # pitch beneath it, but not so much that the shots bunch into the top third
    # of the panel with a band of empty grass under them.
    pitch = VerticalPitch(half=True, pad_top=1, pad_bottom=2, pad_left=1, pad_right=1,
                          **_pitch_kwargs())
    fig, ax = pitch.draw(figsize=figsize)
    fig.set_facecolor(palette.PAPER_2)
    return pitch, fig, ax


# Candidate label offsets, in pitch units, tried in order: directly below the
# node, directly above, then progressively further out — and, since a full-
# match network can pack in a substitute or two right next to the starter they
# replaced (see metrics.passing_network), sideways as a last resort, once
# stacking straight up and down has run out of room. A surname at 8.4pt on
# this pitch occupies roughly 8 x 2.5 units, which is what _LABEL_BOX tests.
_LABEL_SLOTS = [
    (0.0, -3.6), (0.0, 4.0), (0.0, -7.4), (0.0, 7.8), (0.0, -11.2), (0.0, 11.6),
    (6.4, -3.0), (-6.4, -3.0), (6.4, 3.4), (-6.4, 3.4),
    (7.6, -7.0), (-7.6, -7.0), (7.6, 7.2), (-7.6, 7.2),
]
_LABEL_BOX = (9.2, 3.4)  # half-width, half-height of a label, in pitch units


def _label_offsets(xs, ys) -> list[tuple[float, float]]:
    """Pick a non-overlapping offset for each node's surname.

    Two players whose average positions nearly coincide — a double pivot, the
    middle two of a back three — otherwise print their surnames straight through
    each other. Place the busiest nodes first (callers pass them sorted, so they
    get first pick of the closest slot) and give each one the first candidate
    slot that collides with no label already placed and no other node.
    """
    xs, ys = list(xs), list(ys)
    placed: list[tuple[float, float]] = []
    out: list[tuple[float, float]] = []
    for i in range(len(xs)):
        for dx, dy in _LABEL_SLOTS:
            lx, ly = xs[i] + dx, ys[i] + dy
            hits_label = any(
                abs(px - lx) < _LABEL_BOX[0] and abs(py - ly) < _LABEL_BOX[1] for px, py in placed
            )
            hits_node = any(
                j != i and abs(xs[j] - lx) < 3.2 and abs(ys[j] - ly) < 3.0 for j in range(len(xs))
            )
            if not hits_label and not hits_node:
                out.append((dx, dy))
                placed.append((lx, ly))
                break
        else:
            out.append(_LABEL_SLOTS[0])
            placed.append((xs[i] + _LABEL_SLOTS[0][0], ys[i] + _LABEL_SLOTS[0][1]))
    return out


# --------------------------------------------------------------------------- #
# Passing network
# --------------------------------------------------------------------------- #
# Diverging purple -> grey -> green, for node fill only (edges stay team-
# coloured — see passing_network_map). See palette.py for why this pair and
# not red/green.
_THREAT_CMAP = LinearSegmentedColormap.from_list(
    "threat",
    [palette.THREAT_LOW, palette.THREAT_LOW_LIGHT, palette.THREAT_MID,
     palette.THREAT_HIGH_LIGHT, palette.THREAT_HIGH],
)


def _threat_colors(threat: pd.Series, max_abs_threat: float) -> np.ndarray:
    """Map signed per-player pxT to the diverging colormap, linearly.

    Normalised by ``max_abs_threat`` — the largest magnitude across *both*
    teams' networks (see render.build_context), the same shared-scale principle
    as ``max_edge_passes`` — so a green node means the same thing on either
    map.

    Deliberately linear, not the momentum chart's square-root curve. That axis
    can afford to reshape the *spacing* because a reader can still read the
    real number off its tick labels; a colour swatch has no ticks to correct
    it, so what it looks like has to *be* the data. An earlier version applied
    the same square root here and it inflated a goalkeeper whose net pass
    threat was 3% of the match's most threatening passer to nearly a third of
    the way to a saturated colour — a false sense of standing out. Most
    players correctly sitting close to the neutral midpoint is the honest
    picture, not a flaw to compress away.
    """
    if not max_abs_threat:
        return _THREAT_CMAP(np.full(len(threat), 0.5))
    t = np.clip(threat.to_numpy() / max_abs_threat, -1.0, 1.0)
    return _THREAT_CMAP((t + 1.0) / 2.0)


def passing_network_map(net: PassingNetwork, color: str, max_edge_passes: int,
                         max_abs_threat: float) -> str:
    """Nodes at each player's average successful-pass position over the full
    match, sized by passes played and coloured by the net packing threat those
    passes carried; undirected edges between pairs who combined, width
    proportional to how often.

    Circles are starters, triangles are substitutes — a reader can discount a
    triangle's position accordingly (however long they were on, not a full
    match), the same convention the momentum chart already uses for a sub
    coming on. See ``metrics.passing_network`` for why this covers the whole
    match rather than stopping at the first change.

    ``max_edge_passes`` is the heaviest link across *both* teams, and both maps
    are drawn against it, so a thick line means the same thing on both. Scaling
    each team to its own maximum would be the flattering choice and a dishonest
    one: on a fixture where one side barely strings passes together, its network
    *should* look thin next to the other. ``max_abs_threat`` is the same idea
    applied to node colour.

    Edges keep the team colour rather than joining the diverging scale: they
    are already carrying passes-between-pair as width, and a network is read
    by "whose map is this" (team colour, plus the caption above each half)
    before "which players stood out" (node colour) — one line encoding two
    unrelated things would ask the same ink to answer both questions at once.

    Labels sit directly under their own node with a paper-coloured halo. There
    are deliberately no leader lines: on a network map the only lines allowed to
    mean anything are passes.
    """
    pitch, fig, ax = _horizontal_pitch(figsize=(7.4, 5.0))

    if not net.edges.empty:
        ax_, ay_ = _to_pitch(net.edges["ax"], net.edges["ay"])
        bx_, by_ = _to_pitch(net.edges["bx"], net.edges["by"])
        for i in range(len(net.edges)):
            n = int(net.edges["passes"].iloc[i])
            frac = n / max_edge_passes if max_edge_passes else 0.0
            ax.plot(
                [ax_.iloc[i], bx_.iloc[i]], [ay_.iloc[i], by_.iloc[i]],
                color=color,
                # floor of 0.9pt keeps a genuinely weak link visible rather than
                # invisible; the ceiling is what carries the comparison
                linewidth=0.9 + 5.6 * frac,
                alpha=0.28 + 0.5 * frac,
                solid_capstyle="round", zorder=2,
            )

    nx, ny = _to_pitch(net.nodes["x"], net.nodes["y"])
    passes = net.nodes["passes"].to_numpy()
    top = passes.max() if len(passes) else 1
    sizes = 150 + 480 * (passes / top)
    node_colors = _threat_colors(net.nodes["threat"], max_abs_threat)

    is_starter = net.nodes["is_starter"].to_numpy()
    for mask, marker in ((is_starter, "o"), (~is_starter, "^")):
        if not mask.any():
            continue
        pitch.scatter(nx[mask], ny[mask], s=sizes[mask], color=node_colors[mask], marker=marker,
                      edgecolors=palette.PAPER_2, linewidth=1.6, alpha=0.95, zorder=3, ax=ax)

    halo = [pe.withStroke(linewidth=2.8, foreground=palette.PAPER_2)]
    offsets = _label_offsets(nx.to_numpy(), ny.to_numpy())
    for xi, yi, name, (dx, dy) in zip(nx, ny, net.nodes["surname"], offsets):
        ha = "center" if dx == 0 else ("left" if dx > 0 else "right")
        ax.annotate(name, (xi + dx, yi + dy), ha=ha, va="top" if dy < 0 else "bottom",
                    zorder=5, fontsize=8.4, fontweight="bold", color=palette.INK,
                    fontfamily=_LABEL_FONT, path_effects=halo)

    first_change = ("no substitutions made" if net.first_sub_minute == float("inf")
                     else f"first change {net.first_sub_minute:.0f}'")
    ax.annotate(
        f"Full match · {net.total_passes} passes between players used · {first_change}",
        (0.5, -0.015), xycoords="axes fraction", ha="center", va="top",
        fontsize=7.6, color=palette.MUTED, fontfamily=_LABEL_FONT,
    )
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Shot map
# --------------------------------------------------------------------------- #
# Circles throughout, area proportional to xG. The outcome is carried by the
# fill and the outline, not by a zoo of different glyphs: a solid disc is a shot
# that hit the target, a hollow one is a shot that did not, a square is one a
# defender got in the way of, and the goal is the only marker that gets a dark
# ring, so the eye finds it first.
_SHOT_STYLE = {
    "Goal":       dict(marker="o", filled=True,  ring=True),
    "On target":  dict(marker="o", filled=True,  ring=False),
    "Off target": dict(marker="o", filled=False, ring=False),
    "Blocked":    dict(marker="s", filled=False, ring=False),
}
_SHOT_DRAW_ORDER = ["Blocked", "Off target", "On target", "Goal"]


def _shot_size(xg: pd.Series) -> pd.Series:
    """Marker area (matplotlib ``s`` is an area in pt^2) linear in xG, so a
    chance twice as good is a circle with twice the ink."""
    return 26 + 1500 * xg


def shot_map(shots: pd.DataFrame, color: str, label_scorers: bool = True) -> str:
    """Half-pitch, attacking goal at the top. ``shots`` needs
    startAdjCoordinatesX/Y, SHOT_XG and 'category' (see metrics.shot_events).
    'Other' is folded into 'Off target' rather than earning its own legend key
    for the handful of events that land in it."""
    pitch, fig, ax = _half_pitch(figsize=(4.4, 4.0))
    if shots.empty:
        return _fig_to_uri(fig)

    s = shots.copy()
    s["category"] = s["category"].replace({"Other": "Off target"})
    px, py = _to_pitch(s["startAdjCoordinatesX"], s["startAdjCoordinatesY"])
    sizes = _shot_size(s["SHOT_XG"])

    for cat in _SHOT_DRAW_ORDER:
        mask = (s["category"] == cat).to_numpy()
        if not mask.any():
            continue
        style = _SHOT_STYLE[cat]
        pitch.scatter(
            px[mask], py[mask], ax=ax, marker=style["marker"], s=sizes[mask],
            facecolor=color if style["filled"] else "none",
            edgecolors=palette.INK if style["ring"] else color,
            linewidth=1.9 if style["ring"] else 1.25,
            alpha=0.95, zorder=5 if cat == "Goal" else 3,
        )

    if label_scorers:
        halo = [pe.withStroke(linewidth=2.6, foreground=palette.PAPER_2)]
        goals = s.loc[s["category"] == "Goal"]
        gx, gy = _to_pitch(goals["startAdjCoordinatesX"], goals["startAdjCoordinatesY"])
        for xi, yi, name in zip(gx, gy, goals["playerName"]):
            ax.annotate(str(name).split()[-1], (xi, yi), xytext=(0, -13),
                        textcoords="offset points", ha="center", va="top", zorder=6,
                        fontsize=7.6, fontweight="bold", color=palette.INK,
                        fontfamily=_LABEL_FONT, path_effects=halo)
    return _fig_to_uri(fig)


# --------------------------------------------------------------------------- #
# Final-third / box entries
# --------------------------------------------------------------------------- #
def entry_map(entries: pd.DataFrame, max_threat: float) -> str:
    """Full landscape pitch, attacking left to right, one arrow per entry.

    Three things are encoded, on three different channels, so none of them has to
    fight the others:

    * **Colour** = how they got in. A pass is olive, a carry is amber. Worth its
      own channel: Swansea carried the ball into the final third 16 times to
      Charlton's 2, which is a real difference in method and is invisible when
      both are drawn as the same arrow.
    * **Thickness** = the packing xT the entry itself added, on a shared scale across
      both maps, so a fat arrow means the same thing on either. Getting in is not
      the same as getting in somewhere that hurt.
    * **Faded and thin** = the entry was lost. Failures are context, not the
      subject; they are drawn first and stay out of the way of the ones that came
      off.

    Both teams' maps come out of this one function with identical geometry and no
    baked-in legend — the legend lives once in the HTML, under the pair.
    """
    pitch, fig, ax = _horizontal_pitch(figsize=(7.4, 4.9))
    if entries.empty:
        return _fig_to_uri(fig)

    sx, sy = _to_pitch(entries["startAdjCoordinatesX"], entries["startAdjCoordinatesY"])
    ex, ey = _to_pitch(entries["endAdjCoordinatesX"], entries["endAdjCoordinatesY"])
    success = entries["success"].to_numpy()
    carry = entries["carry"].to_numpy()
    # Width floor keeps a zero-threat entry visible; the ceiling carries the story.
    widths = 1.1 + 4.6 * (entries["threat"].to_numpy() / max_threat if max_threat else 0.0)

    lost = ~success
    if lost.any():
        pitch.arrows(sx[lost], sy[lost], ex[lost], ey[lost], ax=ax, color=palette.FAIL_REDGREY,
                     width=1.1, headwidth=4.0, headlength=4.2, alpha=0.34, zorder=2)

    # One call per arrow: mplsoccer.arrows wraps quiver, whose ``width`` is a
    # single scalar for the whole batch, so a per-arrow width has to be drawn
    # one at a time. A hundred arrows is nothing.
    for i in np.flatnonzero(success):
        color = palette.AMBER if carry[i] else palette.SUCCESS_GREEN
        pitch.arrows(sx.iloc[i], sy.iloc[i], ex.iloc[i], ey.iloc[i], ax=ax, color=color,
                     width=float(widths[i]), headwidth=4.0, headlength=4.2, alpha=0.9, zorder=3)

    n, ok = len(entries), int(success.sum())
    carries = int((success & carry).sum())
    ax.annotate(
        f"{n} entries · {ok} completed ({ok / n * 100:.0f}%) · {carries} carried in",
        (0.5, -0.015), xycoords="axes fraction", ha="center", va="top",
        fontsize=7.6, color=palette.MUTED, fontfamily=_LABEL_FONT,
    )
    return _fig_to_uri(fig)

def average_position_map(avg_pos: pd.DataFrame, color: str, line_height: float = None,
                          vertical: bool = False) -> str:
    """Players' average positions for the phase, attacking left-to-right
    (horizontal) or bottom-to-top (vertical).

    Labels are placed in *screen* space, not pitch space: mplsoccer's
    ``VerticalPitch`` swaps which pitch axis (length vs. width) maps to
    which screen axis inside ``pitch.scatter``, but a raw ``ax.annotate``
    call knows nothing about that swap. An earlier version of this map
    called ``ax.annotate`` with unswapped pitch coordinates on a vertical
    pitch, which is why surnames floated away from the node they belonged
    to. Converting node positions to screen space once, up front, means the
    label-offset logic below (``_label_offsets``) is orientation-agnostic.
    """
    figsize = (5.0, 7.0) if vertical else (6.6, 4.5)
    pitch, fig, ax = _vertical_pitch(figsize) if vertical else _horizontal_pitch(figsize)

    if avg_pos.empty:
        return _fig_to_uri(fig)

    # Sort players to ensure a consistent order for label offsetting
    avg_pos = avg_pos.sort_values(by=['x', 'y']).reset_index(drop=True)

    nx, ny = _to_pitch(avg_pos["x"], avg_pos["y"])  # pitch space: nx = length, ny = width
    # Screen space: on a vertical pitch, width is the screen-x axis and
    # length is the screen-y axis; on a horizontal pitch they match pitch
    # space exactly.
    sx, sy = (ny, nx) if vertical else (nx, ny)

    # The dashed line shows how far up the pitch (from the team's own goal
    # line) the back line's average position sits, in metres.
    if line_height is not None and line_height > 0:
        line_fn = ax.axhline if vertical else ax.axvline
        line_fn(line_height, color=color, linestyle='--', linewidth=1.6, alpha=0.8, zorder=2)
        label_xy = (_PITCH_WID - 1.5, line_height + 1.2) if vertical else (line_height, _PITCH_WID - 1.5)
        ha, va = ("right", "bottom") if vertical else ("center", "top")
        ax.annotate(
            f"{line_height:.0f}m", label_xy,
            ha=ha, va=va, zorder=4, fontsize=7.4, fontweight="bold",
            color=color, fontfamily=_LABEL_FONT,
            path_effects=[pe.withStroke(linewidth=2.4, foreground=palette.PAPER_2)],
        )

    pitch.scatter(nx, ny, s=300, color=color, marker='o',
                  edgecolors=palette.PAPER_2, linewidth=1.6, alpha=0.95, zorder=3, ax=ax)

    halo = [pe.withStroke(linewidth=2.8, foreground=palette.PAPER_2)]
    offsets = _label_offsets(sx.to_numpy(), sy.to_numpy())
    for xi, yi, name, (dx, dy) in zip(sx, sy, avg_pos["playerName"], offsets):
        ha = "center" if dx == 0 else ("left" if dx > 0 else "right")
        ax.annotate(name.split()[-1], (xi + dx, yi + dy), ha=ha, va="top" if dy < 0 else "bottom",
                    zorder=5, fontsize=8.4, fontweight="bold", color=palette.INK,
                    fontfamily=_LABEL_FONT, path_effects=halo)

    return _fig_to_uri(fig)
"""Report-styled drawing of IMPECT packing zones.

Geometry, zone masks and border lines come from IMPECT's own reference code
(``impect_zones.py``); this module only dresses them in the report's palette and
rotates the pitch so the team in possession attacks to the right (own goal on the
left), as every other horizontal map in the report does.
"""
from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgb

from src.report import palette, pitch
from src.report.expanded import impect_zones as iz

# Plain-English captions for the twelve default zones (IMPECT's codes are kept in ``CODES``).
LABELS = {
    "GK": "GK", "FBL": "Full-back", "CB": "Centre-back", "FBR": "Full-back", "DM": "Def. mid", "CM": "Central mid",
    "WL": "Wing", "AM": "Att. mid", "WR": "Wing", "IBWL": "Box, wide", "IB": "In box", "IBWR": "Box, wide",
}
CODES = tuple(iz.PACKING_ZONES["default"])


def _to_horizontal(x, y):
    """Impect frame (attacking up, left = -x) -> report frame (attacking right, attacker's left = top)."""
    return y, -x


def _zone_image(values: dict[str, float], colour: str, vmax: float, detail: str, decimals: int) -> np.ndarray:
    """RGBA raster of the horizontal pitch with each zone tinted by its value."""
    xs = np.arange(-iz.HEIGHT / 2, iz.HEIGHT / 2) + .5            # horizontal axis = Impect y
    ys = np.arange(iz.WIDTH / 2, -iz.WIDTH / 2, -1) - .5          # vertical axis (top first) = -Impect x
    hx, hy = np.meshgrid(xs, ys)
    x, y = -hy, hx                                                # back to the Impect frame
    r = np.hypot(x, y - iz.HEIGHT / 2)
    base, tint = np.array(to_rgb(palette.PAPER_2)), np.array(to_rgb(colour))
    image = np.tile(base, (*hx.shape, 1))
    for zone, (borders, _) in iz._ZONES[detail].items():
        v = float(values.get(zone, 0.0))
        if round(v, decimals) <= 0:
            continue
        alpha = 0.08 + 0.72 * float(np.clip(v / (vmax or 1.0), 0, 1))
        mask = iz._zone_mask(x, y, r, borders)
        image[mask] = base * (1 - alpha) + tint * alpha
    return image


def zone_chart(values: dict[str, float], colour: str, vmax: float, decimals: int = 0,
               sub: dict[str, str] | None = None, label_prefix: str = "", small: bool = False,
               detail: str = "default", show_labels: bool = True) -> str:
    """Packing-zone map drawn with IMPECT's geometry, own goal on the left. Each zone is tinted by its value
    against ``vmax`` (shared by both teams) and prints the value; zero zones stay blank. ``sub`` adds a small
    second line per zone and ``label_prefix`` says the zone is the role the ball *reached*."""
    size, label_font, value_font, sub_font, sub_gap = ((3.3, 2.5), 5.2, 9.5, 5.2, 30) if small else \
                                                      ((6.6, 5.0), 8.6, 18.0, 8.6, 28)
    fig, ax = plt.subplots(figsize=size, facecolor=palette.PAPER_2)
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_xlim(-iz.HEIGHT / 2 - 3, iz.HEIGHT / 2 + 3)
    ax.set_ylim(-iz.WIDTH / 2 - 3, iz.WIDTH / 2 + 3)
    ax.set_aspect("equal"); ax.axis("off")
    ax.imshow(_zone_image(values, colour, vmax, detail, decimals), zorder=1, interpolation="nearest",
              extent=(-iz.HEIGHT / 2, iz.HEIGHT / 2, -iz.WIDTH / 2, iz.WIDTH / 2))
    iz._draw_zone_lines(ax, detail, transform=_to_horizontal, color=palette.INK, linewidth=.8, zorder=3)
    for zone, (_, (lx, ly)) in iz._ZONES[detail].items():
        px, py = _to_horizontal(lx, ly)
        v = float(values.get(zone, 0.0))
        shown = round(v, decimals) > 0
        dark = shown and v / (vmax or 1.0) > .4
        if show_labels:
            name = (label_prefix + LABELS.get(zone, zone)).upper()
            if " " in name and len(name) > 9:
                name = name.replace(" ", "\n")
            ax.text(px, py + (26 if shown else 0), name, ha="center", va="center", fontsize=label_font,
                    linespacing=1.05, fontweight="bold", color="white" if dark else palette.MUTED, zorder=4)
        if shown:
            ax.text(px, py - 8, f"{v:.{decimals}f}", ha="center", va="center", fontsize=value_font,
                    fontweight="bold", zorder=4, color="white" if v / (vmax or 1.0) > .55 else palette.INK)
            if sub and sub.get(zone):
                ax.text(px, py - 8 - sub_gap, sub[zone], ha="center", va="center", fontsize=sub_font,
                        color="white" if dark else palette.MUTED, zorder=4)
    ax.annotate("", xy=(iz.HEIGHT / 2 - 10, -iz.WIDTH / 2 - 1), xytext=(iz.HEIGHT / 2 - 120, -iz.WIDTH / 2 - 1),
                arrowprops=dict(arrowstyle="-|>", color=palette.MUTED, lw=.9))
    return pitch._fig_to_uri(fig)

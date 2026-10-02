"""IMPECT packing-zone geometry (vendored).

The zone geometry and the masking / line-drawing helpers below are IMPECT's own reference code
(supplied by IMPECT, kept unchanged apart from this header and the removal of the figure-level
``plot_packing_zones`` convenience wrapper, which the report replaces with ``zone_chart`` in
``packing_zones.py``).

The pitch is in IMPECT packing-zone coordinates: origin at the centre spot, x from -255 to 255 and
y from -335 to 335, the team in possession attacking upwards.
"""

import numpy as np
from matplotlib import patches
from matplotlib.axes import Axes

__all__ = ["PACKING_ZONES", "WIDTH", "HEIGHT"]

# pitch geometry
_WIDTH = 510
_HEIGHT = 670
WIDTH, HEIGHT = _WIDTH, _HEIGHT
_CENTER = (0.0, _HEIGHT / 2)  # centre of the zone arcs: the attacked goal
_R_IB, _R_AM, _R_CM, _R_DM = 161, 261, 361, 461  # arc radii
_LANE = 155  # x of the left/right lanes (mirrored)
_HALF_LANE = 55  # x of the left/right half lanes (mirrored)
_GK_LINE = -280  # y of the goalkeeper line


def _arc_y(x: float, radius: float) -> float:
    """Return the y of the lower half of a zone arc at ``x``."""
    return _CENTER[1] - np.sqrt(radius**2 - (x - _CENTER[0]) ** 2)


def _line(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """Return ``(slope, intercept)`` of the line through ``a`` and ``b``."""
    slope = (b[1] - a[1]) / (b[0] - a[0])
    return slope, a[1] - slope * a[0]


# corners of the diagonal lines between the attacking-mid and in-behind zones
_WL_CORNER = (-_LANE, _arc_y(-_LANE, _R_AM))
_IBL_CORNER = (-_HALF_LANE, _arc_y(-_HALF_LANE, _R_IB))
_WR_CORNER = (_LANE, _arc_y(_LANE, _R_AM))
_IBR_CORNER = (_HALF_LANE, _arc_y(_HALF_LANE, _R_IB))
_LEFT_DIAG = _line(_WL_CORNER, _IBL_CORNER)
_RIGHT_DIAG = _line(_WR_CORNER, _IBR_CORNER)

# label rows (y) and columns (x)
_Y_GK = (-_HEIGHT / 2 + _GK_LINE) / 2
_Y_CB = (_HEIGHT / 2 - _R_DM + _GK_LINE) / 2
_Y_DM = _HEIGHT / 2 - (_R_CM + _R_DM) / 2
_Y_CM = _HEIGHT / 2 - (_R_AM + _R_CM) / 2
_Y_AM = _HEIGHT / 2 - (_R_IB + _R_AM) / 2
_Y_IB = _HEIGHT / 2 - _R_IB / 2
_Y_WING = _HEIGHT / 20
_NUDGE = _HEIGHT / 50  # lifts half-space labels clear of the arcs
_X_WIDE = (_LANE + _WIDTH / 2) / 2
_X_HALF = (_LANE + _HALF_LANE) / 2
_IBW = (_WIDTH * 0.3, _HEIGHT * 0.28)

# zone borders and label positions; borders are combined with AND:
# r_min/r_max = distance to the attacked goal, x/y bounds, and the zone lying
# below/above one or more diagonal lines given as (slope, intercept)
_ZONES: dict[str, dict[str, tuple[dict, tuple[float, float]]]] = {
    "default": {
        "GK": ({"y_max": _GK_LINE}, (0, _Y_GK)),
        "FBL": ({"r_min": _R_DM, "x_max": -_LANE, "y_min": _GK_LINE}, (-_X_WIDE, _Y_CB)),
        "CB": ({"r_min": _R_DM, "x_min": -_LANE, "x_max": _LANE, "y_min": _GK_LINE}, (0, _Y_CB)),
        "FBR": ({"r_min": _R_DM, "x_min": _LANE, "y_min": _GK_LINE}, (_X_WIDE, _Y_CB)),
        "DM": ({"r_min": _R_CM, "r_max": _R_DM, "x_min": -_LANE, "x_max": _LANE}, (0, _Y_DM)),
        "CM": ({"r_min": _R_AM, "r_max": _R_CM, "x_min": -_LANE, "x_max": _LANE}, (0, _Y_CM)),
        "WL": ({"r_min": _R_AM, "r_max": _R_DM, "x_max": -_LANE}, (-_X_WIDE, _Y_WING)),
        "AM": ({"r_min": _R_IB, "r_max": _R_AM, "below": (_LEFT_DIAG, _RIGHT_DIAG)}, (0, _Y_AM)),
        "WR": ({"r_min": _R_AM, "r_max": _R_DM, "x_min": _LANE}, (_X_WIDE, _Y_WING)),
        "IBWL": ({"r_min": _R_IB, "r_max": _R_AM, "x_max": -_HALF_LANE, "above": (_LEFT_DIAG,)},
                 (-_IBW[0], _IBW[1])),
        "IB": ({"r_max": _R_IB}, (0, _Y_IB)),
        "IBWR": ({"r_min": _R_IB, "r_max": _R_AM, "x_min": _HALF_LANE, "above": (_RIGHT_DIAG,)}, _IBW),
    },
    "granular": {
        "GKL": ({"x_max": -_HALF_LANE, "y_max": _GK_LINE}, (-_LANE, _Y_GK)),
        "GKC": ({"x_min": -_HALF_LANE, "x_max": _HALF_LANE, "y_max": _GK_LINE}, (0, _Y_GK)),
        "GKR": ({"x_min": _HALF_LANE, "y_max": _GK_LINE}, (_LANE, _Y_GK)),
        "FBL": ({"r_min": _R_DM, "x_max": -_LANE, "y_min": _GK_LINE}, (-_X_WIDE, _Y_CB)),
        "CBL": ({"r_min": _R_DM, "x_min": -_LANE, "x_max": -_HALF_LANE, "y_min": _GK_LINE}, (-_X_HALF, _Y_CB)),
        "CBC": ({"r_min": _R_DM, "x_min": -_HALF_LANE, "x_max": _HALF_LANE, "y_min": _GK_LINE}, (0, _Y_CB)),
        "CBR": ({"r_min": _R_DM, "x_min": _HALF_LANE, "x_max": _LANE, "y_min": _GK_LINE}, (_X_HALF, _Y_CB)),
        "FBR": ({"r_min": _R_DM, "x_min": _LANE, "y_min": _GK_LINE}, (_X_WIDE, _Y_CB)),
        "DML": ({"r_min": _R_CM, "r_max": _R_DM, "x_min": -_LANE, "x_max": -_HALF_LANE},
                (-_X_HALF, _Y_DM + _NUDGE)),
        "DMC": ({"r_min": _R_CM, "r_max": _R_DM, "x_min": -_HALF_LANE, "x_max": _HALF_LANE}, (0, _Y_DM)),
        "DMR": ({"r_min": _R_CM, "r_max": _R_DM, "x_min": _HALF_LANE, "x_max": _LANE},
                (_X_HALF, _Y_DM + _NUDGE)),
        "WL": ({"r_min": _R_AM, "r_max": _R_DM, "x_max": -_LANE}, (-_X_WIDE, _Y_WING)),
        "CML": ({"r_min": _R_AM, "r_max": _R_CM, "x_min": -_LANE, "x_max": -_HALF_LANE},
                (-_X_HALF, _Y_CM + _NUDGE)),
        "CMC": ({"r_min": _R_AM, "r_max": _R_CM, "x_min": -_HALF_LANE, "x_max": _HALF_LANE}, (0, _Y_CM)),
        "CMR": ({"r_min": _R_AM, "r_max": _R_CM, "x_min": _HALF_LANE, "x_max": _LANE},
                (_X_HALF, _Y_CM + _NUDGE)),
        "WR": ({"r_min": _R_AM, "r_max": _R_DM, "x_min": _LANE}, (_X_WIDE, _Y_WING)),
        "AML": ({"r_max": _R_AM, "x_max": -_HALF_LANE, "below": (_LEFT_DIAG,)}, (-_X_HALF + _WIDTH / 40, _Y_AM)),
        "AMC": ({"r_min": _R_IB, "r_max": _R_AM, "x_min": -_HALF_LANE, "x_max": _HALF_LANE}, (0, _Y_AM)),
        "AMR": ({"r_max": _R_AM, "x_min": _HALF_LANE, "below": (_RIGHT_DIAG,)}, (_X_HALF - _WIDTH / 40, _Y_AM)),
        "IBWL": ({"r_min": _R_IB, "r_max": _R_AM, "x_max": -_HALF_LANE, "above": (_LEFT_DIAG,)},
                 (-_IBW[0], _IBW[1])),
        "IBL": ({"r_max": _R_IB, "x_max": -_HALF_LANE}, (-_X_HALF + _WIDTH / 60, _Y_IB + _NUDGE)),
        "IBC": ({"r_max": _R_IB, "x_min": -_HALF_LANE, "x_max": _HALF_LANE}, (0, _Y_IB)),
        "IBR": ({"r_max": _R_IB, "x_min": _HALF_LANE}, (_X_HALF - _WIDTH / 60, _Y_IB + _NUDGE)),
        "IBWR": ({"r_min": _R_IB, "r_max": _R_AM, "x_min": _HALF_LANE, "above": (_RIGHT_DIAG,)}, _IBW),
    },
}

#: Zone names available at each level of detail.
PACKING_ZONES = {level: tuple(zones) for level, zones in _ZONES.items()}


def _zone_mask(x: np.ndarray, y: np.ndarray, r: np.ndarray, borders: dict):
    """Return a boolean mask of the grid cells that lie inside a zone."""
    mask = np.ones_like(x, dtype=bool)
    if "r_min" in borders:
        mask &= r >= borders["r_min"]
    if "r_max" in borders:
        mask &= r <= borders["r_max"]
    if "x_min" in borders:
        mask &= x >= borders["x_min"]
    if "x_max" in borders:
        mask &= x <= borders["x_max"]
    if "y_min" in borders:
        mask &= y >= borders["y_min"]
    if "y_max" in borders:
        mask &= y <= borders["y_max"]
    for slope, intercept in borders.get("below", ()):
        mask &= y <= slope * x + intercept
    for slope, intercept in borders.get("above", ()):
        mask &= y >= slope * x + intercept
    return mask


def _draw_zone_lines(ax: Axes, detail: str, transform=None, **style_overrides) -> None:
    """Draw the zone borders onto ``ax``. ``transform`` maps (x, y) arrays to the axes' own frame."""
    style = {"color": "black", "linewidth": 1, "zorder": 2, **style_overrides}
    tf = transform or (lambda a, b: (a, b))
    half_w, half_h = _WIDTH / 2, _HEIGHT / 2

    def plot(xs, ys, **kw):
        px, py = tf(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
        ax.plot(px, py, **{**style, **kw})

    # arcs around the attacked goal; the centre-mid arc only spans the lanes
    for radius, x_lim in ((_R_IB, half_w), (_R_AM, half_w), (_R_CM, _LANE), (_R_DM, half_w)):
        x = np.linspace(-min(x_lim, radius), min(x_lim, radius), 500)
        plot(x, _arc_y(x, radius))

    plot([-half_w, half_w], [_GK_LINE, _GK_LINE])
    plot([-_LANE, -_LANE], [_GK_LINE, _WL_CORNER[1]])
    plot([_LANE, _LANE], [_GK_LINE, _WR_CORNER[1]])
    plot(*zip(_WL_CORNER, _IBL_CORNER))
    plot(*zip(_WR_CORNER, _IBR_CORNER))

    if detail == "granular":
        for x in (-_HALF_LANE, _HALF_LANE):
            plot([x, x], [-half_h, half_h], linestyle="dotted")

    plot([-half_w, half_w, half_w, -half_w, -half_w], [-half_h, -half_h, half_h, half_h, -half_h])

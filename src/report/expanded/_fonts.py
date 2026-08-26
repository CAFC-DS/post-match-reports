"""The report's actual brand fonts (Plus Jakarta Sans, Spectral), self-contained.

Two consumers, one set of files:

1. matplotlib (chart-drawn text -- player initials, axis labels, KPI numbers
   baked into PNGs) needs the font FILE registered with its font_manager;
   ``register()`` does that.
2. Chrome's headless print-to-pdf needs the font available to the HTML it's
   printing. A <link> to Google Fonts turned out to be unreliable there --
   the fetch doesn't reliably complete (or isn't honoured) inside
   --print-to-pdf's page lifecycle, and the report silently fell back to the
   system sans the whole time. ``embedded_css()`` sidesteps that entirely by
   inlining each TTF as a base64 @font-face data URI, so there is no network
   dependency at generation time at all.

Both read the same files, downloaded once from fonts.gstatic.com and
committed here rather than fetched per render.
"""

from __future__ import annotations

import base64
from pathlib import Path

import matplotlib.font_manager as fm

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

SANS = "Plus Jakarta Sans"
SERIF = "Spectral"

# filename stem -> (family, weight, style)
_FACES = [
    ("PlusJakartaSans-400-normal", SANS, 400, "normal"),
    ("PlusJakartaSans-700-normal", SANS, 700, "normal"),
    ("PlusJakartaSans-700-italic", SANS, 700, "italic"),
    ("PlusJakartaSans-800-normal", SANS, 800, "normal"),
    ("Spectral-400-normal", SERIF, 400, "normal"),
    ("Spectral-400-italic", SERIF, 400, "italic"),
    ("Spectral-600-normal", SERIF, 600, "normal"),
    ("Spectral-600-italic", SERIF, 600, "italic"),
]

_registered = False


def register() -> None:
    """Make the fonts available to matplotlib's font_manager."""
    global _registered
    if _registered:
        return
    for path in _FONTS_DIR.glob("*.ttf"):
        fm.fontManager.addfont(str(path))
    _registered = True


def embedded_css() -> str:
    """@font-face CSS with each font file inlined as a base64 data URI --
    no network fetch required at PDF-generation time."""
    blocks = []
    for stem, family, weight, style in _FACES:
        data = base64.b64encode((_FONTS_DIR / f"{stem}.ttf").read_bytes()).decode("ascii")
        blocks.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};"
            f"src:url(data:font/ttf;base64,{data}) format('truetype')}}"
        )
    return "".join(blocks)

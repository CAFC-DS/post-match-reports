"""Single-match set-piece report.

A one-page, horizontal "Set Play Analysis" report for a single fixture, inspired
by the elite post-match set-piece pages but rendered in the cream / editorial
visual language of ``outputs/season_story``.

The report shows, for both teams:
  * an attacking corner overview (delivery map coloured by swing type),
  * a free-kick overview (delivery map + threat heatmap),
  * a central stack of stat bars (match value vs season per-90 / % change),
  * first-contact tables for attacking & defending corners and free-kicks.

Data flows through the same Snowflake / parquet-cache connection layer used by
``full-season-analysis`` (``src.db.query_runner.QueryRunner``).
"""

from __future__ import annotations

__all__ = ["build_report"]


def build_report(*args, **kwargs):
    """Lazy proxy to :func:`set_piece_report.render.build_report`."""
    from set_piece_report.render import build_report as _build_report

    return _build_report(*args, **kwargs)

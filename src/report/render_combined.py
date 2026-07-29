"""Assemble the combined Impect + DVMS single-page board report (HTML + PDF).

Sources each panel from whichever provider is authoritative for that metric
(see docs/superpowers/specs/2026-07-29-combined-board-post-match-report-design.md).
Template, CSS and panel layout are copied byte-for-byte from
board-post-match-report's post_match_report_v2.html.j2 — only the data
feeding each panel differs.
"""

from __future__ import annotations


class FixtureMismatchError(ValueError):
    """Raised when the given Impect match and DVMS fixture don't look like
    the same real-world game — team names or kickoff date disagree."""


def _normalize(name: str) -> str:
    return name.strip().lower()


def _assert_same_fixture(impect_meta, dvms_fixture) -> None:
    impect_teams = {_normalize(impect_meta.home_team), _normalize(impect_meta.away_team)}
    dvms_teams = {_normalize(dvms_fixture.home_team), _normalize(dvms_fixture.away_team)}
    if impect_teams != dvms_teams:
        raise FixtureMismatchError(
            f"Impect match {impect_meta.home_team} v {impect_meta.away_team} does not match "
            f"DVMS fixture {dvms_fixture.home_team} v {dvms_fixture.away_team}."
        )
    impect_date = impect_meta.kickoff.date()
    dvms_date = dvms_fixture.match_date.date()
    if impect_date != dvms_date:
        raise FixtureMismatchError(
            f"Impect match date {impect_date} does not match DVMS fixture date {dvms_date} "
            f"({impect_meta.home_team} v {impect_meta.away_team})."
        )

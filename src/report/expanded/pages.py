"""Page registry for the expanded analyst report.

The template used to hard-code every footer number and "PAGE x/y" label,
which made adding a page a find-and-replace exercise. The registry is the one
place that knows the page order; the template, the contents page and the
generation checks all read from it.
"""
from __future__ import annotations

from typing import Any

SECTIONS = ("overview", "in_possession", "out_of_possession", "transition")


def _plan(tracked_shapes: bool, has_team_sheet: bool, has_players: bool) -> list[tuple[str, str, bool]]:
    """Ordered ``(key, section, is_divider)`` for the report."""
    plan: list[tuple[str, str, bool]] = [
        ("contents", "front", True),
        ("div_overview", "overview", True),
    ]
    plan.append(("ov_summary", "overview", False))
    if has_team_sheet:
        plan.append(("ov_sheet", "overview", False))
    if has_players:
        plan += [(f"ov_players_{g.lower()}", "overview", False) for g in ("GK", "CB", "FB", "MF", "W", "CF")]
    plan += [
        ("ov_stats", "overview", False),
        ("ov_flow", "overview", False),
        ("ov_phases", "overview", False),
        ("div_ip", "in_possession", True),
        ("net", "in_possession", False),
    ]
    if tracked_shapes:
        plan += [("shapes_0", "in_possession", False), ("shapes_1", "in_possession", False)]
    else:
        plan += [("shapes", "in_possession", False)]
    plan += [
        ("ip_receptions", "in_possession", False),
        ("ip_threat_zones", "in_possession", False),
        ("ip_entries", "in_possession", False),
        ("ip_shots", "in_possession", False),
        ("div_oop", "out_of_possession", True),
        ("oop_pressure", "out_of_possession", False),
        ("oop_duels", "out_of_possession", False),
        ("oop_regains", "out_of_possession", False),
        ("div_trans", "transition", True),
        ("trans_response", "transition", False),
    ]
    return plan


def build_page_plan(tracked_shapes: bool, has_team_sheet: bool = True, has_players: bool = True) -> dict[str, Any]:
    """Number every page and label content pages ``PAGE i/n`` within their section.

    Returns ``{"pages": {key: {...}}, "order": [key, ...], "total": int,
    "sections": {section: {"first": int, "last": int}}}``. Each page entry has
    ``n`` (1-based position in the report), ``section``, ``divider`` and
    ``label`` (``"DIVIDER"`` or ``"PAGE i/n"``).
    """
    plan = _plan(tracked_shapes, has_team_sheet, has_players)
    content_total: dict[str, int] = {}
    for _, section, divider in plan:
        if not divider:
            content_total[section] = content_total.get(section, 0) + 1

    pages: dict[str, dict[str, Any]] = {}
    seen: dict[str, int] = {}
    sections: dict[str, dict[str, int]] = {}
    for n, (key, section, divider) in enumerate(plan, start=1):
        if key == "contents":
            label = ""
        elif divider:
            label = "DIVIDER"
        else:
            seen[section] = seen.get(section, 0) + 1
            label = f"PAGE {seen[section]}/{content_total[section]}"
        pages[key] = {"n": n, "section": section, "divider": divider, "label": label}
        span = sections.setdefault(section, {"first": n, "last": n})
        span["last"] = n
    return {"pages": pages, "order": [k for k, _, _ in plan], "total": len(plan), "sections": sections}


def section_info(subject: str, tracked_shapes: bool, has_team_sheet: bool,
                 has_players: bool = True) -> dict[str, dict[str, Any]]:
    """Title, blurb and sub-items per section: the single source for both the
    divider pages and the contents page."""
    overview = ["Match stats & team performance", "Match flow, timeline & xG race",
                "Game state & 15-minute phases"]
    if has_players:
        overview.insert(0, "Player performance by position vs season & league averages")
    if has_team_sheet:
        overview.insert(0, "Team sheet, lineups & timeline")
    overview.insert(0, "Match summary")
    return {
        "overview": {
            "num": 1, "title": "Overview",
            "blurb": f"Who played, match stats, {subject}'s season-relative performance profile, "
                     "and how the game unfolded." if has_team_sheet else
                     f"Match stats, {subject}'s season-relative performance profile, and how the game unfolded.",
            "items": overview,
        },
        "in_possession": {
            "num": 2, "title": "In Possession",
            "blurb": f"How both teams built play, how {subject} progressed threat, and how chance quality compared.",
            "items": ["Passing networks & progression",
                      "Team-by-team tracked phase shapes" if tracked_shapes else "Combined event-data average locations",
                      "Where players received the ball",
                      "Threat density, role zones & player threat",
                      "Final-third & box entries",
                      "Comparative shot maps, xG sources & shot placement"],
        },
        "out_of_possession": {
            "num": 3, "title": "Out of Possession",
            "blurb": f"Where {subject} engaged, competed and recovered the ball.",
            "items": ["Pressing & duel maps, best pressers", "Player duel performance", "Ball regains by third & second balls"],
        },
        "transition": {
            "num": 4, "title": "Transition",
            "blurb": f"Whether {subject} controlled the immediate response after losing the ball.",
            "items": ["High attacking-half losses", "Counter-press regains", "Losses leading to shots"],
        },
    }


def build_contents(plan: dict[str, Any], subject: str, tracked_shapes: bool,
                   has_team_sheet: bool, has_players: bool = True) -> list[dict[str, Any]]:
    """Contents rows: section info plus the page span from the plan."""
    info = section_info(subject, tracked_shapes, has_team_sheet, has_players)
    rows = []
    for section in SECTIONS:
        span = plan["sections"][section]
        pages = f"page {span['first']}" if span["first"] == span["last"] else f"pages {span['first']}\u2013{span['last']}"
        rows.append({**info[section], "section": section, "pages": pages, "first": span["first"]})
    return rows

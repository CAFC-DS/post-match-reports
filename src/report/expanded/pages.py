"""Page registry for the expanded analyst report.

The template used to hard-code every footer number and "PAGE x/y" label,
which made adding a page a find-and-replace exercise. The registry is the one
place that knows the page order; the template, the contents page and the
generation checks all read from it.
"""
from __future__ import annotations

from typing import Any

SECTIONS = ("overview", "in_possession", "out_of_possession", "transition")


def _plan(tracked_shapes: bool) -> list[tuple[str, str, bool]]:
    """Ordered ``(key, section, is_divider)`` for the report."""
    plan: list[tuple[str, str, bool]] = [
        ("div_overview", "overview", True),
        ("ov_stats", "overview", False),
        ("ov_flow", "overview", False),
        ("div_ip", "in_possession", True),
        ("net_0", "in_possession", False),
        ("net_1", "in_possession", False),
    ]
    if tracked_shapes:
        plan += [("shapes_0", "in_possession", False), ("shapes_1", "in_possession", False)]
    else:
        plan += [("shapes", "in_possession", False)]
    plan += [
        ("ip_threat", "in_possession", False),
        ("ip_shots", "in_possession", False),
        ("div_oop", "out_of_possession", True),
        ("oop_pressure", "out_of_possession", False),
        ("oop_duels", "out_of_possession", False),
        ("oop_regains", "out_of_possession", False),
        ("div_trans", "transition", True),
        ("trans_response", "transition", False),
    ]
    return plan


def build_page_plan(tracked_shapes: bool) -> dict[str, Any]:
    """Number every page and label content pages ``PAGE i/n`` within their section.

    Returns ``{"pages": {key: {...}}, "order": [key, ...], "total": int,
    "sections": {section: {"first": int, "last": int}}}``. Each page entry has
    ``n`` (1-based position in the report), ``section``, ``divider`` and
    ``label`` (``"DIVIDER"`` or ``"PAGE i/n"``).
    """
    plan = _plan(tracked_shapes)
    content_total: dict[str, int] = {}
    for _, section, divider in plan:
        if not divider:
            content_total[section] = content_total.get(section, 0) + 1

    pages: dict[str, dict[str, Any]] = {}
    seen: dict[str, int] = {}
    sections: dict[str, dict[str, int]] = {}
    for n, (key, section, divider) in enumerate(plan, start=1):
        if divider:
            label = "DIVIDER"
        else:
            seen[section] = seen.get(section, 0) + 1
            label = f"PAGE {seen[section]}/{content_total[section]}"
        pages[key] = {"n": n, "section": section, "divider": divider, "label": label}
        span = sections.setdefault(section, {"first": n, "last": n})
        span["last"] = n
    return {"pages": pages, "order": [k for k, _, _ in plan], "total": len(plan), "sections": sections}

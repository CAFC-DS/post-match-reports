"""Set-piece concepts derived from Opta F24 events.

The IMPECT feed the set-piece reports were built on hands over rich pre-labelled
set-piece fields (``setPieceSubPhaseCornerType``, ``setPieceSubPhaseFirstTouchWon``,
delivery end zones, a shared ``setPieceId`` linking a phase's events). Opta's F24
has none of those as fields — the same concepts have to be *derived* from event
qualifiers and sequence. This module is that derivation layer, and the honest
list of where a derivation is weaker than the IMPECT original lives in each
function's docstring, because those caveats get surfaced in report captions.

Qualifier ids used (verified present in the sample feed):

* q6  — corner taken (flag on the delivery pass)
* q5  — free kick taken (flag on the delivery pass)
* q107 — throw-in
* q56 — zone of the delivery ("Left" / "Right" / "Center" / "Back")
* q2  — cross flag
* q26 — direct free kick (on shots; zero occurrences in the sample match —
  a match with no direct attempts, not an absent qualifier)

Geometry constants are Opta's *fixed* 0-100 reference frame (the box is always
at the same 0-100 coordinates regardless of true pitch size): penalty area
``x >= 83``, ``21.1 <= y <= 78.9``; six-yard box ``x >= 94.2``,
``36.8 <= y <= 63.2``; goal mouth centred on ``y = 50``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Opta fixed-frame geometry (0-100 units).
BOX_X = 83.0
BOX_Y_LOW, BOX_Y_HIGH = 21.1, 78.9
SIX_YARD_X = 94.2

Q_CORNER = 6
Q_FK_TAKEN = 5
Q_THROW_IN = 107
Q_ZONE = 56
Q_CROSS = 2
Q_DIRECT_FK = 26

# Event types that can't be a "contact" (stoppages, admin, cards ...).
_NON_CONTACT_TYPES = frozenset({5, 17, 18, 19, 27, 28, 30, 32, 34, 37, 40, 43, 55, 83})

SHOT_TYPE_IDS = frozenset({13, 14, 15, 16})


def _flag(events: pd.DataFrame, qid: int) -> pd.Series:
    return events["qualifiers"].map(lambda q: qid in q)


def _abs_seconds(events: pd.DataFrame) -> pd.Series:
    """Cumulative match seconds (fine for ordering/windows within one period)."""
    return events["minute"] * 60 + events["second"]


def _corner_side(row) -> str:
    """'left' / 'right' from the delivering team's attacking perspective.

    q56 carries it directly on corner passes ("Left"/"Right"); the start-y
    fallback uses Opta's convention (y=0 is the right touchline attacking
    left-to-right), so y < 50 means the right corner.
    """
    zone = row["qualifiers"].get(Q_ZONE)
    if zone in ("Left", "Right"):
        return zone.lower()
    return "right" if row["y"] < 50 else "left"


def _delivery_zone(end_y: float, side: str) -> str:
    """near_post / central / far_post from the delivery's end y and corner side.

    The box width (21.1-78.9) splits into thirds; the third closest to the
    delivering corner is the near post. IMPECT labels these NEAR_POST /
    CENTRAL / FAR_POST from its own tagging — this is a pure-geometry stand-in,
    so a whipped ball that *swerves* through zones is classified by where it
    arrived, which is also how IMPECT's end-zone labels behave.
    """
    third = (BOX_Y_HIGH - BOX_Y_LOW) / 3.0
    if side == "right":
        # right corner is at y ~ 0: near post is the low-y third
        if end_y < BOX_Y_LOW + third:
            return "near_post"
        if end_y < BOX_Y_LOW + 2 * third:
            return "central"
        return "far_post"
    if end_y > BOX_Y_HIGH - third:
        return "near_post"
    if end_y > BOX_Y_HIGH - 2 * third:
        return "central"
    return "far_post"


def corners(events: pd.DataFrame) -> pd.DataFrame:
    """One row per corner delivery (pass with the q6 flag).

    Columns: ``event_id``, ``team_id``, ``player_id``, ``period_id``,
    ``minute``, ``second``, ``side`` ('left'/'right'), ``corner_type``
    ('short' / 'near_post' / 'central' / 'far_post'), ``end_x``/``end_y``,
    ``outcome``, ``is_cross``.

    'Short' means the delivery did not arrive in the penalty area — IMPECT's
    SHORT label is tagged by an analyst, this one is geometric (end point
    outside the box), which also catches a failed cross that never reached the
    box. That over-inclusion is deliberate: for scouting "did they work it
    short or swing it in", where the ball arrived is the actionable fact.
    """
    mask = (events["type_id"] == 1) & _flag(events, Q_CORNER)
    out = events.loc[mask, ["event_id", "team_id", "player_id", "period_id",
                            "minute", "second", "x", "y", "end_x", "end_y",
                            "outcome", "qualifiers"]].copy()
    if out.empty:
        return out.assign(side=None, corner_type=None, is_cross=None)

    out["side"] = out.apply(_corner_side, axis=1)
    in_box = (out["end_x"] >= BOX_X) & out["end_y"].between(BOX_Y_LOW, BOX_Y_HIGH)
    out["corner_type"] = [
        _delivery_zone(ey, s) if ib else "short"
        for ey, s, ib in zip(out["end_y"], out["side"], in_box)
    ]
    out["is_cross"] = _flag(out, Q_CROSS)
    return out.drop(columns=["qualifiers"]).reset_index(drop=True)


def first_contact(events: pd.DataFrame, deliveries: pd.DataFrame,
                  within_seconds: float = 5.0) -> pd.DataFrame:
    """First touch after each delivery: which team and player got there.

    IMPECT hands this over as ``setPieceSubPhaseFirstTouchWon`` +
    ``FirstTouchPlayerName``, tagged by an analyst. The Opta derivation is:
    the next chronological event after the delivery, in the same period,
    within ``within_seconds``, that is a real contact type (stoppages, cards,
    formation markers excluded). The feed is in on-ball order, so the next
    on-ball event *is* the first contact in almost all cases; the known
    weakness is a delivery straight out of play (no contact — returned as
    ``None``) and simultaneous duels, where Opta logs both an Aerial for the
    winner and a Challenge for the loser — taking the first row still returns
    the winner because Opta orders the won duel first.

    Returns ``deliveries`` joined with ``contact_event_id``, ``contact_team_id``,
    ``contact_player_id``, ``contact_type_id``, ``won`` (bool: contact team ==
    delivering team; None when no contact found).
    """
    ev = events[~events["type_id"].isin(_NON_CONTACT_TYPES)].copy()
    ev["_abs"] = _abs_seconds(ev)
    ev = ev.sort_values(["period_id", "_abs", "event_id"]).reset_index(drop=True)

    rows = []
    for _, d in deliveries.iterrows():
        t0 = d["minute"] * 60 + d["second"]
        cand = ev[(ev["period_id"] == d["period_id"])
                  & (ev["_abs"] >= t0)
                  & (ev["_abs"] <= t0 + within_seconds)
                  & (ev["event_id"] != d["event_id"])]
        if cand.empty:
            rows.append({"event_id": d["event_id"], "contact_event_id": None,
                         "contact_team_id": None, "contact_player_id": None,
                         "contact_type_id": None, "won": None})
            continue
        c = cand.iloc[0]
        rows.append({
            "event_id": d["event_id"],
            "contact_event_id": c["event_id"],
            "contact_team_id": c["team_id"],
            "contact_player_id": c["player_id"],
            "contact_type_id": c["type_id"],
            "won": bool(str(c["team_id"]) == str(d["team_id"])),
        })
    return deliveries.merge(pd.DataFrame(rows), on="event_id", how="left")


def free_kicks(events: pd.DataFrame) -> pd.DataFrame:
    """Free-kick deliveries (passes flagged q5) plus direct free-kick shots.

    ``fk_type``: 'into_box_cross' (crossed, arrived in the box), 'into_box'
    (arrived in the box, not flagged a cross — the high/looped ball), 'short'
    (kept possession outside the box), and — from the shots side — 'direct'
    (a shot event carrying q26). IMPECT's finer labels (near/far/back-of-box
    cross types) map onto ``zone`` computed the same way as corner zones,
    using the attacking side implied by start y.
    """
    passes = events.loc[(events["type_id"] == 1) & _flag(events, Q_FK_TAKEN),
                        ["event_id", "team_id", "player_id", "period_id", "minute",
                         "second", "x", "y", "end_x", "end_y", "outcome",
                         "qualifiers"]].copy()
    if not passes.empty:
        in_box = (passes["end_x"] >= BOX_X) & passes["end_y"].between(BOX_Y_LOW, BOX_Y_HIGH)
        is_cross = _flag(passes, Q_CROSS)
        passes["fk_type"] = np.where(in_box & is_cross, "into_box_cross",
                             np.where(in_box, "into_box", "short"))
        side = np.where(passes["y"] < 50, "right", "left")
        passes["zone"] = [
            _delivery_zone(ey, s) if ib else None
            for ey, s, ib in zip(passes["end_y"], side, in_box)
        ]
        passes = passes.drop(columns=["qualifiers"])

    shots = events.loc[events["type_id"].isin(SHOT_TYPE_IDS) & _flag(events, Q_DIRECT_FK),
                       ["event_id", "team_id", "player_id", "period_id", "minute",
                        "second", "x", "y", "outcome"]].copy()
    if not shots.empty:
        shots["end_x"] = np.nan
        shots["end_y"] = np.nan
        shots["fk_type"] = "direct"
        shots["zone"] = None

    out = pd.concat([passes, shots], ignore_index=True)
    return out.reset_index(drop=True)


def throw_ins(events: pd.DataFrame) -> pd.DataFrame:
    """Throw-ins (q107), split long vs short.

    'Long' mirrors the IMPECT-report definition re-expressed in Opta units: the
    throw arrives box-deep (``end_x >= 83``) and centrally enough to threaten
    (``end_y`` within the box width ±2 units) — i.e. a weapon aimed at the box,
    not a routine restart down the line.
    """
    mask = _flag(events, Q_THROW_IN) & (events["type_id"] == 1)
    out = events.loc[mask, ["event_id", "team_id", "player_id", "period_id",
                            "minute", "second", "x", "y", "end_x", "end_y",
                            "outcome"]].copy()
    if out.empty:
        return out.assign(is_long=None)
    out["is_long"] = (out["end_x"] >= BOX_X) & out["end_y"].between(BOX_Y_LOW - 2, BOX_Y_HIGH + 2)
    return out.reset_index(drop=True)


def led_to_goal(events: pd.DataFrame, deliveries: pd.DataFrame,
                within_seconds: float = 10.0) -> pd.Series:
    """Boolean per delivery: did the delivering team score within the window?

    IMPECT links a phase's events by a shared ``setPieceId``; Opta has no such
    key, so the stand-in is a time window — a goal by the delivering team, in
    the same period, within ``within_seconds`` of the delivery. A window admits
    the rare "corner cleared, instantly recycled, scored" sequence that IMPECT
    would call a second phase; at 10 seconds that error is small and errs on
    crediting the set piece, which is the way a set-piece coach counts them.
    """
    goals = events[events["is_goal"]]
    goal_times = list(zip(goals["period_id"], _abs_seconds(goals), goals["team_id"]))

    flags = []
    for _, d in deliveries.iterrows():
        t0 = d["minute"] * 60 + d["second"]
        hit = any(
            p == d["period_id"] and t0 <= t <= t0 + within_seconds and str(team) == str(d["team_id"])
            for p, t, team in goal_times
        )
        flags.append(hit)
    return pd.Series(flags, index=deliveries.index, name="led_to_goal")

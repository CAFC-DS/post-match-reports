"""Parser for the Opta F24 event feed (DVMS ASSET_SUBTYPE=20).

The F24 is the event log: one ``<Event>`` per on-ball action (pass, shot,
tackle, ...), each carrying a variable set of ``<Q>`` qualifiers with the
event-specific detail. This module turns the raw XML text into a typed
``pd.DataFrame`` that downstream metrics build on, keeping the *full* qualifier
set per row because different reports reach for very different qualifiers.

Only the passed XML text is touched here — no file or network I/O — so the same
function serves both the local sample files and the Snowflake ``RAW_PAYLOAD``
text in the later loader stage.

Coordinate note: Opta ``x``/``y`` are on the standard 0-100 pitch scale (0,0 is
one corner, 100,100 the diagonally opposite one), independent of the real pitch
dimensions. Conversion to metres lives in :mod:`dvms.coords`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

# Human-readable names for the type_ids the reports name explicitly. This is a
# deliberately partial map (Opta's full F24 taxonomy is ~80 codes); it covers
# the events surfaced in captions/legends. Anything unmapped keeps its numeric
# id. Values verified against the handover doc and the sample feed.
TYPE_NAMES: Dict[int, str] = {
    1: "Pass",
    2: "Offside Pass",
    3: "Take On",
    4: "Foul",
    5: "Out",
    6: "Corner Awarded",
    7: "Tackle",
    8: "Interception",
    10: "Save",
    12: "Clearance",
    13: "Miss",
    14: "Post",
    15: "Attempt Saved",
    16: "Goal",
    44: "Aerial",
    49: "Ball Recovery",
    61: "Ball Touch",
}

# Shot events (Miss, Post, Attempt Saved, Goal) — the shot map / xG set.
SHOT_TYPE_IDS = frozenset({13, 14, 15, 16})

# Pass end coordinates live on these qualifiers (present on most type_id=1).
Q_PASS_END_X = 140
Q_PASS_END_Y = 141


@dataclass
class F24Match:
    """Parsed F24: game-level metadata plus the typed event table."""

    game_id: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int
    competition: Optional[str]
    kickoff: Optional[pd.Timestamp]
    events: pd.DataFrame


def _qualifiers(event: ET.Element) -> Dict[int, Optional[str]]:
    """Collect an event's qualifiers as ``{qualifier_id: value}``.

    Flag-only qualifiers (a ``<Q>`` with no ``value`` attribute, e.g. the corner
    flag q6 or the header flag q15) map to ``None`` — their presence *is* the
    signal. Callers test ``qid in quals`` for flags, ``quals.get(qid)`` for
    valued ones.
    """
    out: Dict[int, Optional[str]] = {}
    for q in event.findall("Q"):
        qid = q.get("qualifier_id")
        if qid is None:
            continue
        out[int(qid)] = q.get("value")
    return out


def _to_float(value: Optional[str]) -> float:
    if value is None or value == "":
        return np.nan
    try:
        return float(value)
    except ValueError:
        return np.nan


def parse_f24(xml_text: str) -> F24Match:
    """Parse an Opta F24 feed into an :class:`F24Match`.

    The returned ``events`` frame has typed columns:

    ``event_id`` (int, the *unique* Opta ``id`` — note the small per-event
    ``event_id`` attribute is only unique within a period, so it is kept
    separately as ``seq``), ``type_id`` (int), ``period_id`` (int), ``minute``,
    ``second`` (int, cumulative match minute as Opta reports it), ``timestamp``
    (pd.Timestamp), ``player_id`` (nullable string of the numeric id — absent on
    team events like formations), ``team_id`` (string), ``outcome`` (int), ``x``,
    ``y`` (float 0-100), ``qualifiers`` (the per-row dict), plus derived
    ``end_x``/``end_y`` (float, from q140/q141) and the ``is_pass``/``is_shot``/
    ``is_goal`` booleans.

    Rows are returned in chronological order (period, minute, second, unique id).
    """
    root = ET.fromstring(xml_text)
    game = root.find("Game")
    if game is None:
        raise ValueError("F24 XML has no <Game> element")

    rows = []
    for ev in game.findall("Event"):
        quals = _qualifiers(ev)
        type_id = int(ev.get("type_id"))
        player_id = ev.get("player_id")
        ts = ev.get("timestamp")
        rows.append(
            {
                "event_id": int(ev.get("id")),
                "seq": int(ev.get("event_id")) if ev.get("event_id") else np.nan,
                "type_id": type_id,
                "period_id": int(ev.get("period_id")),
                "minute": int(ev.get("min")),
                "second": int(ev.get("sec")),
                "timestamp": pd.Timestamp(ts) if ts else pd.NaT,
                "player_id": player_id if player_id else None,
                "team_id": ev.get("team_id"),
                "outcome": int(ev.get("outcome")) if ev.get("outcome") is not None else np.nan,
                "x": _to_float(ev.get("x")),
                "y": _to_float(ev.get("y")),
                "qualifiers": quals,
                "end_x": _to_float(quals.get(Q_PASS_END_X)) if Q_PASS_END_X in quals else np.nan,
                "end_y": _to_float(quals.get(Q_PASS_END_Y)) if Q_PASS_END_Y in quals else np.nan,
                "is_pass": type_id == 1,
                "is_shot": type_id in SHOT_TYPE_IDS,
                "is_goal": type_id == 16,
            }
        )

    events = pd.DataFrame(rows)
    if not events.empty:
        events["player_id"] = events["player_id"].astype("string")
        events["team_id"] = events["team_id"].astype("string")
        events = events.sort_values(
            ["period_id", "minute", "second", "event_id"]
        ).reset_index(drop=True)

    return F24Match(
        game_id=game.get("id"),
        home_team_id=game.get("home_team_id"),
        away_team_id=game.get("away_team_id"),
        home_team_name=game.get("home_team_name"),
        away_team_name=game.get("away_team_name"),
        home_score=int(game.get("home_score")) if game.get("home_score") is not None else 0,
        away_score=int(game.get("away_score")) if game.get("away_score") is not None else 0,
        competition=game.get("competition_name"),
        kickoff=pd.Timestamp(game.get("game_date")) if game.get("game_date") else None,
        events=events,
    )

"""Parser for the Opta F7 feed (DVMS ASSET_SUBTYPE=21).

The F7 carries the team sheet: formation, score and side per team, the goals
(with scorer/assist), and the lineup with shirt numbers and positions. Player
*names* live in a separate ``<Team>`` block keyed by the padded ``uID``
(``p432735``); the lineup and goals reference players by the same id.

Two ID formats appear across the DVMS feeds for the *same* underlying player:
the F7 uses the padded ``p<n>`` form, the F24 uses the bare numeric ``<n>``.
This parser strips the ``p``/``t`` prefixes so ``player_id``/``team uID`` join
straight onto F24 and the Second Spectrum ``optaId``. The prefixed forms are
kept too where a report needs them.

Only the passed XML text is touched — no file or network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

import pandas as pd


@dataclass
class TeamMeta:
    uid: str          # padded form, e.g. "t5"
    team_id: str      # bare numeric form, e.g. "5"
    name: str
    formation: str    # Opta formation string, e.g. "3421"
    score: int
    side: str         # "Home" / "Away"


@dataclass
class Goal:
    minute: int
    second: Optional[int]
    scorer_id: Optional[str]   # bare numeric
    assist_id: Optional[str]   # bare numeric, None if unassisted
    team_id: Optional[str]     # bare numeric of the scoring team


@dataclass
class F7Match:
    game_id: str
    home: TeamMeta
    away: TeamMeta
    goals: List[Goal]
    lineups: pd.DataFrame
    _names: Dict[str, str] = field(default_factory=dict, repr=False)

    def player_name(self, player_id: str) -> Optional[str]:
        """Full name for a bare-numeric (or ``p``-prefixed) player id."""
        key = str(player_id)
        if key.startswith("p"):
            key = key[1:]
        return self._names.get(key)


def _strip(prefix: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value[len(prefix):] if value.startswith(prefix) else value


def parse_f7(xml_text: str) -> F7Match:
    """Parse an Opta F7 feed into an :class:`F7Match`.

    ``lineups`` is a DataFrame with one row per named player per team:
    ``player_id`` (bare numeric), ``team_id`` (bare numeric), ``side``
    (home/away), ``full_name``, ``last_name``, ``shirt_number`` (int),
    ``position``, ``formation_place`` (int), ``status`` (Start/Sub) and
    ``sub_position`` (the outfield role given to a named substitute, else None).
    """
    root = ET.fromstring(xml_text)
    doc = root.find("SoccerDocument")
    if doc is None:
        raise ValueError("F7 XML has no <SoccerDocument> element")

    game_id = _strip("f", doc.get("uID")) or ""

    # Player-name lookup and per-team side/name come from the <Team> blocks.
    names: Dict[str, str] = {}
    last_names: Dict[str, str] = {}
    team_names: Dict[str, str] = {}
    for team in doc.findall("Team"):
        tid = _strip("t", team.get("uID"))
        name_el = team.find("Name")
        if tid is not None and name_el is not None and name_el.text:
            team_names[tid] = name_el.text
        for player in team.findall("Player"):
            pid = _strip("p", player.get("uID"))
            pn = player.find("PersonName")
            if pid is None or pn is None:
                continue
            first = pn.findtext("First", default="").strip()
            known = pn.findtext("Known", default="").strip()
            last = pn.findtext("Last", default="").strip()
            display_last = known or last
            full = " ".join(part for part in (first, display_last) if part) or display_last
            names[pid] = full
            last_names[pid] = display_last

    teams: Dict[str, TeamMeta] = {}
    goals: List[Goal] = []
    lineup_rows = []

    match_data = doc.find("MatchData")
    for td in (match_data.findall("TeamData") if match_data is not None else []):
        tid = _strip("t", td.get("TeamRef"))
        side = td.get("Side", "")
        meta = TeamMeta(
            uid=td.get("TeamRef"),
            team_id=tid,
            name=team_names.get(tid, ""),
            formation=td.get("Formation", ""),
            score=int(td.get("Score")) if td.get("Score") is not None else 0,
            side=side,
        )
        teams[side.lower()] = meta

        for goal in td.findall("Goal"):
            assist_el = goal.find("Assist")
            goals.append(
                Goal(
                    minute=int(goal.get("Min")) if goal.get("Min") is not None else 0,
                    second=int(goal.get("Sec")) if goal.get("Sec") is not None else None,
                    scorer_id=_strip("p", goal.get("PlayerRef")),
                    assist_id=_strip("p", assist_el.get("PlayerRef")) if assist_el is not None else None,
                    team_id=tid,
                )
            )

        lineup = td.find("PlayerLineUp")
        for mp in (lineup.findall("MatchPlayer") if lineup is not None else []):
            pid = _strip("p", mp.get("PlayerRef"))
            lineup_rows.append(
                {
                    "player_id": pid,
                    "team_id": tid,
                    "side": side.lower(),
                    "full_name": names.get(pid),
                    "last_name": last_names.get(pid),
                    "shirt_number": int(mp.get("ShirtNumber")) if mp.get("ShirtNumber") else None,
                    "position": mp.get("Position"),
                    "formation_place": int(mp.get("Formation_Place")) if mp.get("Formation_Place") else None,
                    "status": mp.get("Status"),
                    "sub_position": mp.get("SubPosition"),
                }
            )

    lineups = pd.DataFrame(lineup_rows)
    if not lineups.empty:
        lineups["player_id"] = lineups["player_id"].astype("string")
        lineups["team_id"] = lineups["team_id"].astype("string")

    home = teams.get("home")
    away = teams.get("away")
    if home is None or away is None:
        raise ValueError("F7 XML is missing a Home or Away TeamData block")

    return F7Match(
        game_id=game_id,
        home=home,
        away=away,
        goals=goals,
        lineups=lineups,
        _names=names,
    )

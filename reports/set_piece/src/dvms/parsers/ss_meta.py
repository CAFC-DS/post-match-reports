"""Parser for the Second Spectrum match metadata (DVMS ASSET_SUBTYPE=40, JSON).

Small JSON header describing the tracking file: real pitch dimensions (metres),
frame rate, the period frame-index ranges with each period's attack direction
(``homeAttPositive``), and the two rosters carrying the ``optaId`` join key.

The pitch dimensions and ``homeAttPositive`` flags are what let event
coordinates (Opta 0-100) and tracking coordinates (pitch-centred metres) be put
in the same, direction-normalised frame — see :mod:`dvms.coords`.

Only the passed JSON text is touched — no file or network I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional
import json


@dataclass
class Period:
    number: int
    start_frame: int
    end_frame: int
    home_att_positive: bool


@dataclass
class RosterPlayer:
    opta_id: Optional[str]
    name: str
    number: Optional[int]
    position: Optional[str]
    ss_id: Optional[str]


@dataclass
class PitchMeta:
    pitch_length: float
    pitch_width: float
    fps: float
    periods: List[Period]
    home_players: List[RosterPlayer]
    away_players: List[RosterPlayer]
    game_id: Optional[str] = None
    home_team_id: Optional[str] = None
    away_team_id: Optional[str] = None

    def home_att_positive(self, period_number: int) -> Optional[bool]:
        for p in self.periods:
            if p.number == period_number:
                return p.home_att_positive
        return None

    def opta_id_map(self) -> Dict[str, str]:
        """``optaId -> 'home'/'away'`` for every rostered player."""
        out: Dict[str, str] = {}
        for pl in self.home_players:
            if pl.opta_id:
                out[pl.opta_id] = "home"
        for pl in self.away_players:
            if pl.opta_id:
                out[pl.opta_id] = "away"
        return out


def _roster(entries) -> List[RosterPlayer]:
    out = []
    for e in entries or []:
        out.append(
            RosterPlayer(
                opta_id=str(e["optaId"]) if e.get("optaId") is not None else None,
                name=e.get("name", ""),
                number=e.get("number"),
                position=e.get("position"),
                ss_id=e.get("ssiId"),
            )
        )
    return out


def parse_ss_metadata(json_text: str) -> PitchMeta:
    """Parse Second Spectrum metadata JSON into a :class:`PitchMeta`."""
    d = json.loads(json_text)
    periods = [
        Period(
            number=int(p["number"]),
            start_frame=int(p["startFrameIdx"]),
            end_frame=int(p["endFrameIdx"]),
            home_att_positive=bool(p["homeAttPositive"]),
        )
        for p in d.get("periods", [])
    ]
    return PitchMeta(
        pitch_length=float(d["pitchLength"]),
        pitch_width=float(d["pitchWidth"]),
        fps=float(d["fps"]),
        periods=periods,
        home_players=_roster(d.get("homePlayers")),
        away_players=_roster(d.get("awayPlayers")),
        game_id=str(d["optaId"]) if d.get("optaId") is not None else None,
        home_team_id=str(d["homeOptaId"]) if d.get("homeOptaId") is not None else None,
        away_team_id=str(d["awayOptaId"]) if d.get("awayOptaId") is not None else None,
    )

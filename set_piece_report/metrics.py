"""Set-piece metric computation for a single fixture.

Three families are produced:

* ``stat_rows``        – the central bar-chart rows (corners / throw-ins /
  indirect free-kicks), each with the match value for both teams plus the
  season per-90 baseline and the % change of this match vs that baseline.
* ``first_contact``    – attacking & defending first-contact tables for corners
  and free-kicks (won / lost / uncontested).
* ``corner_deliveries`` / ``fk_deliveries`` – tidy per-event frames the pitch
  module turns into delivery maps.

All attribution uses the raw IMPECT fields: shots, goals and xG already carry a
``setPieceCategory`` on the event, so set-piece threat is read directly off the
shot/goal events rather than re-stitched from sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from set_piece_report.config import (
    CORNER_CATEGORIES,
    CORNER_SHORT,
    CORNER_TYPE_ORDER,
    DIRECT_FREE_KICK_ACTION,
    FREE_KICK_CATEGORY,
    FREE_KICK_SHOT_TYPE,
    IMPECT_CORNER_TYPE_MAP,
    THROW_IN_CATEGORY,
)
from set_piece_report.data import MatchContext


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
def _is_corner(events: pd.DataFrame) -> pd.Series:
    return events["setPieceCategory"].isin(CORNER_CATEGORIES)


def _indirect_fk_delivery(events: pd.DataFrame) -> pd.Series:
    """A free-kick *played into the game* (not a direct shot at goal)."""
    return (events["actionType"] == "FREE_KICK") & (
        events["setPieceSubPhaseFreeKickType"].astype(str) != FREE_KICK_SHOT_TYPE
    )


def _indirect_fk_event(events: pd.DataFrame) -> pd.Series:
    """Any event (shot/goal) belonging to an indirect free-kick phase."""
    return (events["setPieceCategory"] == FREE_KICK_CATEGORY) & (
        events["action"].astype(str) != DIRECT_FREE_KICK_ACTION
    )


def _first_touch_state(events: pd.DataFrame) -> pd.Series:
    """Normalise the stringified first-touch flag into won/lost/none."""
    ft = events["setPieceSubPhaseFirstTouchWon"].astype(str)
    return ft.map({"True": "won", "False": "lost"}).fillna("none").where(
        ft.isin(["True", "False"]), "none"
    )


# --------------------------------------------------------------------------- #
# Raw per-team match counts
# --------------------------------------------------------------------------- #
def _team_match_counts(events: pd.DataFrame, team: str) -> dict[str, float]:
    atk = events["attackingSquadName"] == team
    corner = _is_corner(events)
    fk_deliv = _indirect_fk_delivery(events)
    fk_event = _indirect_fk_event(events)
    throw = events["setPieceCategory"] == THROW_IN_CATEGORY
    shot = events["actionType"] == "SHOT"
    goal = events["actionType"] == "GOAL"
    xg = pd.to_numeric(events["SHOT_XG"], errors="coerce").fillna(0.0)

    return {
        "corners": float((atk & (events["actionType"] == "CORNER")).sum()),
        "corner_shots": float((atk & corner & shot).sum()),
        "corner_goals": float((atk & corner & goal).sum()),
        "corner_xg": float(xg[atk & corner & shot].sum()),
        # Count throw-ins *taken* (the delivery), not every event in the phase.
        "throw_ins": float((atk & (events["actionType"] == "THROW_IN")).sum()),
        "throw_in_shots": float((atk & throw & shot).sum()),
        "throw_in_goals": float((atk & throw & goal).sum()),
        "throw_in_xg": float(xg[atk & throw & shot].sum()),
        "indirect_fks": float((atk & fk_deliv).sum()),
        "fk_shots": float((atk & fk_event & shot).sum()),
        "fk_goals": float((atk & fk_event & goal).sum()),
        "fk_xg": float(xg[atk & fk_event & shot].sum()),
    }


def _season_per90(events: pd.DataFrame, team: str) -> dict[str, float]:
    """Season totals divided by matches played (≈ per-90 for team counts)."""
    matches = int(events["matchId"].nunique())
    if matches == 0:
        return {}
    totals = _team_match_counts(events, team)
    return {k: v / matches for k, v in totals.items()}


# --------------------------------------------------------------------------- #
# Stat bar rows
# --------------------------------------------------------------------------- #
@dataclass
class StatRow:
    label: str
    home_value: float
    away_value: float
    home_per90: float
    away_per90: float
    decimals: int = 0
    section: str = ""  # optional group header shown above the row

    @staticmethod
    def _pct_change(value: float, base: float) -> float | None:
        if base in (0, None) or pd.isna(base):
            return None
        return (value - base) / base * 100.0

    @property
    def home_pct(self) -> float | None:
        return self._pct_change(self.home_value, self.home_per90)

    @property
    def away_pct(self) -> float | None:
        return self._pct_change(self.away_value, self.away_per90)

    def fmt(self, value: float) -> str:
        if self.decimals == 0:
            return f"{value:.0f}"
        return f"{value:.{self.decimals}f}"


def build_stat_rows(ctx: MatchContext) -> list[StatRow]:
    home, away = ctx.home_team, ctx.away_team
    m_home = _team_match_counts(ctx.match_events, home)
    m_away = _team_match_counts(ctx.match_events, away)
    s_home = _season_per90(ctx.home_season_events, home)
    s_away = _season_per90(ctx.away_season_events, away)

    def row(label, key, decimals=0, section=""):
        return StatRow(
            label=label,
            home_value=m_home[key],
            away_value=m_away[key],
            home_per90=s_home.get(key, 0.0),
            away_per90=s_away.get(key, 0.0),
            decimals=decimals,
            section=section,
        )

    return [
        row("Total Corners", "corners", section="CORNERS"),
        row("Shots Created From Corners", "corner_shots"),
        row("Goals From Corners", "corner_goals"),
        row("xG Created From Corners", "corner_xg", decimals=2),
        row("Total Throw-Ins", "throw_ins", section="THROW-INS"),
        row("Shots Created From Throw-Ins", "throw_in_shots"),
        row("Goals From Throw-Ins", "throw_in_goals"),
        row("xG Created From Throw-Ins", "throw_in_xg", decimals=2),
        row("Total Indirect Free-Kicks", "indirect_fks", section="INDIRECT FREE-KICKS"),
        row("Shots Created From Indirect Free-Kicks", "fk_shots"),
        row("Goals From Indirect Free-Kicks", "fk_goals"),
        row("xG Created From Indirect Free-Kicks", "fk_xg", decimals=2),
    ]


# --------------------------------------------------------------------------- #
# First-contact tables
# --------------------------------------------------------------------------- #
@dataclass
class ContactRow:
    label: str
    deliveries: int
    won: int       # team that we report on won the first contact
    lost: int
    uncontested: int

    @property
    def win_rate(self) -> float | None:
        contested = self.won + self.lost
        return (self.won / contested * 100.0) if contested else None


@dataclass
class FirstContactTable:
    team: str
    attacking_corners: ContactRow
    defending_corners: ContactRow
    attacking_fks: ContactRow
    defending_fks: ContactRow


def _contact_for(events: pd.DataFrame, mask: pd.Series, attacking_team: str,
                 report_perspective: str, label: str) -> ContactRow:
    """First-contact tally.

    ``report_perspective`` is ``"attacking"`` (team taking the set-piece) or
    ``"defending"`` (team facing it). ``setPieceSubPhaseFirstTouchWon`` is from
    the *attacking* team's view, so the defending team's wins are the attack's
    losses.
    """
    sel = events.loc[mask & (events["attackingSquadName"] == attacking_team)]
    state = _first_touch_state(sel)
    atk_won = int((state == "won").sum())
    atk_lost = int((state == "lost").sum())
    none = int((state == "none").sum())
    if report_perspective == "attacking":
        return ContactRow(label, len(sel), atk_won, atk_lost, none)
    return ContactRow(label, len(sel), atk_lost, atk_won, none)


def build_first_contact(ctx: MatchContext) -> dict[str, FirstContactTable]:
    ev = ctx.match_events
    corner_mask = ev["actionType"] == "CORNER"
    fk_mask = _indirect_fk_delivery(ev)
    tables: dict[str, FirstContactTable] = {}
    for team, opp in ((ctx.home_team, ctx.away_team), (ctx.away_team, ctx.home_team)):
        tables[team] = FirstContactTable(
            team=team,
            attacking_corners=_contact_for(ev, corner_mask, team, "attacking", "Attacking corners"),
            defending_corners=_contact_for(ev, corner_mask, opp, "defending", "Defending corners"),
            attacking_fks=_contact_for(ev, fk_mask, team, "attacking", "Attacking free-kicks"),
            defending_fks=_contact_for(ev, fk_mask, opp, "defending", "Defending free-kicks"),
        )
    return tables


# --------------------------------------------------------------------------- #
# Delivery frames (for the pitch maps)
# --------------------------------------------------------------------------- #
def classify_corner_type(row: pd.Series) -> str:
    """Corner category straight from the IMPECT ``setPieceSubPhaseCornerType``.

    Values map to near post / central / far post / short (open play). A delivery
    that stops well short of the box is treated as ``SHORT`` even if the type is
    missing, so worked corners never masquerade as a target-zone delivery.
    """
    raw = str(row.get("setPieceSubPhaseCornerType"))
    mapped = IMPECT_CORNER_TYPE_MAP.get(raw)
    if mapped is not None:
        return mapped

    end_x = row.get("endAdjCoordinatesX")
    end_y = row.get("endAdjCoordinatesY")
    if (pd.notna(end_x) and float(end_x) < 41.0) or (pd.notna(end_y) and abs(float(end_y)) > 26.0):
        return CORNER_SHORT
    return CORNER_SHORT  # unknown / uncrossed → treat as a worked corner


def corner_deliveries(ctx: MatchContext, team: str) -> pd.DataFrame:
    ev = ctx.match_events
    corners = ev.loc[
        (ev["actionType"] == "CORNER") & (ev["attackingSquadName"] == team)
    ].copy()
    if corners.empty:
        return corners.assign(corner_type=pd.Series(dtype=str), first_touch=pd.Series(dtype=str))
    corners["corner_type"] = corners.apply(classify_corner_type, axis=1)
    corners["first_touch"] = _first_touch_state(corners).values
    return corners


def fk_deliveries(ctx: MatchContext, team: str) -> pd.DataFrame:
    ev = ctx.match_events
    fks = ev.loc[_indirect_fk_delivery(ev) & (ev["attackingSquadName"] == team)].copy()
    if fks.empty:
        return fks.assign(fk_group=pd.Series(dtype=str), first_touch=pd.Series(dtype=str))

    def group(t: str) -> str:
        t = str(t)
        if "CROSS" in t or "BOX" in t:
            return "CROSS"
        if "HIGH_BALL" in t:
            return "HIGH_BALL"
        if "POSSESSION" in t:
            return "INTO_POSSESSION"
        return "OTHER"

    fks["fk_group"] = fks["setPieceSubPhaseFreeKickType"].map(group)
    fks["first_touch"] = _first_touch_state(fks).values
    return fks


# --------------------------------------------------------------------------- #
# Convenience aggregate
# --------------------------------------------------------------------------- #
@dataclass
class ReportData:
    stat_rows: list[StatRow]
    first_contact: dict[str, "FirstContactTable"]
    corner_type_counts: dict[str, dict[str, int]] = field(default_factory=dict)


def build_report_data(ctx: MatchContext) -> ReportData:
    type_counts: dict[str, dict[str, int]] = {}
    for team in (ctx.home_team, ctx.away_team):
        deliveries = corner_deliveries(ctx, team)
        counts = {t: 0 for t in CORNER_TYPE_ORDER}
        if not deliveries.empty:
            for corner_type, n in deliveries["corner_type"].value_counts().items():
                counts[corner_type] = int(n)
        type_counts[team] = counts
    return ReportData(
        stat_rows=build_stat_rows(ctx),
        first_contact=build_first_contact(ctx),
        corner_type_counts=type_counts,
    )

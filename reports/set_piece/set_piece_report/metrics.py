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

import numpy as np
import pandas as pd

from set_piece_report.config import (
    ANOMALY_THROW,
    BOX_THROW,
    CORNER_CATEGORIES,
    CORNER_SHORT,
    CORNER_TYPE_ORDER,
    DIRECT_FREE_KICK_ACTION,
    FREE_KICK_CATEGORY,
    FREE_KICK_SHOT_TYPE,
    IMPECT_CORNER_TYPE_MAP,
    THROW_IN_CATEGORY,
    OTHER_THROW,
    THROW_BOX_MAX_ABS_Y,
    THROW_BOX_MIN_X,
    THROW_BOX_START_ZONES,
    THROW_MAX_DISTANCE,
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
    """Any event (shot/goal) belonging to an *indirect* free-kick phase.

    Excludes direct free-kick attempts, which are recorded either as an
    ``action == DIRECT_FREE_KICK`` or with sub-phase type ``FREE_KICK_SHOT``
    (some are logged as a plain long-range shot in a FREE_KICK_SHOT phase).
    """
    return (
        (events["setPieceCategory"] == FREE_KICK_CATEGORY)
        & (events["action"].astype(str) != DIRECT_FREE_KICK_ACTION)
        & (events["setPieceSubPhaseFreeKickType"].astype(str) != FREE_KICK_SHOT_TYPE)
    )


def _direct_fk_shot(events: pd.DataFrame) -> pd.Series:
    """A direct free-kick attempt (a shot straight from the set-piece)."""
    return (events["actionType"] == "SHOT") & (
        events["setPieceSubPhaseFreeKickType"].astype(str) == FREE_KICK_SHOT_TYPE
    )


def _scoring_set_piece_ids(events: pd.DataFrame) -> set:
    """setPieceIds that produced a goal — used to flag deliveries that scored."""
    goals = events.loc[events["actionType"] == "GOAL", "setPieceId"].dropna()
    return set(goals.unique())


def _led_to_goal(deliveries: pd.DataFrame, scoring_ids: set) -> pd.Series:
    if "setPieceId" not in deliveries.columns:
        return pd.Series(False, index=deliveries.index)
    return deliveries["setPieceId"].isin(scoring_ids)


def _first_touch_state(events: pd.DataFrame) -> pd.Series:
    """Normalise the stringified first-touch flag into won/lost/none."""
    ft = events["setPieceSubPhaseFirstTouchWon"].astype(str)
    return ft.map({"True": "won", "False": "lost"}).fillna("none").where(
        ft.isin(["True", "False"]), "none"
    )


def _fallback_throw_start_zone(x: float, y: float) -> str | None:
    """Conservatively derive IMPECT-style start context when it is absent."""
    if not (np.isfinite(x) and np.isfinite(y)):
        return None
    side = "LEFT" if y > 0 else "RIGHT"
    if x >= 36.0:
        return f"{side}_CORNER" if abs(y) > 20.16 else "FIRST_THIRD"
    if x >= 20.0:
        return f"{side}_WING_BESIDES_BOX" if abs(y) > 20.16 else f"{side}_WING_IN_FRONT_OF_BOX"
    if x >= -17.5:
        return "SECOND_THIRD_LEFT" if y > 0 else "SECOND_THIRD_RIGHT"
    return "FIRST_THIRD"


def classify_throw_ins(throws: pd.DataFrame) -> pd.DataFrame:
    """Attach the shared BOX_THROW / OTHER_THROW / ANOMALY taxonomy."""
    out = throws.copy()
    if out.empty:
        out["throw_group"] = pd.Series(dtype=object)
        out["throw_start_zone"] = pd.Series(dtype=object)
        out["throw_anomaly_reason"] = pd.Series(dtype=object)
        out["throw_distance"] = pd.Series(dtype=float)
        return out
    values = {}
    for name in ("startAdjCoordinatesX", "startAdjCoordinatesY",
                 "endAdjCoordinatesX", "endAdjCoordinatesY"):
        values[name] = pd.to_numeric(out.get(name), errors="coerce")
    sx, sy = values["startAdjCoordinatesX"], values["startAdjCoordinatesY"]
    ex, ey = values["endAdjCoordinatesX"], values["endAdjCoordinatesY"]
    out["throw_distance"] = np.hypot(ex - sx, ey - sy)
    zone_col = out.get("setPieceSubPhaseStartZone", pd.Series(index=out.index, dtype=object))
    zones = zone_col.astype(str).str.upper().where(zone_col.notna(), None)
    out["throw_start_zone"] = [
        _fallback_throw_start_zone(a, b) if pd.isna(z) or z in ("NONE", "NAN") else z
        for a, b, z in zip(sx, sy, zones)
    ]
    missing = sx.isna() | sy.isna() | ex.isna() | ey.isna() | ~np.isfinite(out["throw_distance"])
    overlong = out["throw_distance"] > THROW_MAX_DISTANCE
    reaches_box = (ex >= THROW_BOX_MIN_X) & (ey.abs() <= THROW_BOX_MAX_ABS_Y)
    attacking_start = out["throw_start_zone"].isin(THROW_BOX_START_ZONES)
    out["throw_anomaly_reason"] = np.where(
        missing, "missing/non-finite coordinates",
        np.where(overlong, "distance > 45 m", None),
    )
    out["throw_group"] = np.where(
        missing | overlong, ANOMALY_THROW,
        np.where(reaches_box & attacking_start, BOX_THROW, OTHER_THROW),
    )
    return out


# --------------------------------------------------------------------------- #
# Raw per-team match counts
# --------------------------------------------------------------------------- #
def _team_match_counts(events: pd.DataFrame, team: str) -> dict[str, float]:
    atk = events["attackingSquadName"] == team
    corner = _is_corner(events)
    fk_deliv = _indirect_fk_delivery(events)
    fk_event = _indirect_fk_event(events)
    direct_fk = _direct_fk_shot(events)
    throw_deliveries = classify_throw_ins(events.loc[events["actionType"] == "THROW_IN"])
    valid_throw_deliveries = throw_deliveries[throw_deliveries["throw_group"] != ANOMALY_THROW]
    anomaly_ids = set(
        throw_deliveries.loc[throw_deliveries["throw_group"] == ANOMALY_THROW, "setPieceId"].dropna()
    ) if "setPieceId" in throw_deliveries else set()
    throw = (events["setPieceCategory"] == THROW_IN_CATEGORY) & ~events["setPieceId"].isin(anomaly_ids)
    shot = events["actionType"] == "SHOT"
    goal = events["actionType"] == "GOAL"
    success = events["result"].astype(str) == "SUCCESS"
    xg = pd.to_numeric(events["SHOT_XG"], errors="coerce").fillna(0.0)

    return {
        "corners": float((atk & (events["actionType"] == "CORNER")).sum()),
        "corner_shots": float((atk & corner & shot).sum()),
        "corner_goals": float((atk & corner & goal).sum()),
        "corner_xg": float(xg[atk & corner & shot].sum()),
        # Count throw-ins *taken* (the delivery), not every event in the phase.
        "throw_ins": float((valid_throw_deliveries["attackingSquadName"] == team).sum()),
        "throw_in_shots": float((atk & throw & shot).sum()),
        "throw_in_goals": float((atk & throw & goal).sum()),
        "throw_in_xg": float(xg[atk & throw & shot].sum()),
        "indirect_fks": float((atk & fk_deliv).sum()),
        "fk_shots": float((atk & fk_event & shot).sum()),
        "fk_goals": float((atk & fk_event & goal).sum()),
        "fk_xg": float(xg[atk & fk_event & shot].sum()),
        # Direct free-kicks: the attempt is itself the shot, so goals come off the
        # shot result (avoids double-counting the paired GOAL event).
        "direct_fks": float((atk & direct_fk).sum()),
        "direct_fk_goals": float((atk & direct_fk & success).sum()),
        "direct_fk_xg": float(xg[atk & direct_fk].sum()),
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
        row("Direct Free-Kicks Taken", "direct_fks", section="DIRECT FREE-KICKS"),
        row("Goals From Direct Free-Kicks", "direct_fk_goals"),
        row("xG From Direct Free-Kicks", "direct_fk_xg", decimals=2),
        row("Total Indirect Free-Kicks", "indirect_fks", section="INDIRECT FREE-KICKS"),
        row("Shots Created From Indirect Free-Kicks", "fk_shots"),
        row("Goals From Indirect Free-Kicks", "fk_goals"),
        row("xG Created From Indirect Free-Kicks", "fk_xg", decimals=2),
        row("Total Throw-Ins", "throw_ins", section="THROW-INS"),
        row("Shots Created From Throw-Ins", "throw_in_shots"),
        row("Goals From Throw-Ins", "throw_in_goals"),
        row("xG Created From Throw-Ins", "throw_in_xg", decimals=2),
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
        return corners.assign(
            corner_type=pd.Series(dtype=str), first_touch=pd.Series(dtype=str),
            led_to_goal=pd.Series(dtype=bool),
        )
    corners["corner_type"] = corners.apply(classify_corner_type, axis=1)
    corners["first_touch"] = _first_touch_state(corners).values
    corners["led_to_goal"] = _led_to_goal(corners, _scoring_set_piece_ids(ev)).values
    return corners


def set_piece_shots_from_events(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """All shots a team created from set-pieces (corners, free-kicks, throw-ins)
    within ``events`` — the shared selection behind :func:`set_piece_shots`,
    generalised to any events frame (a single match, or a team's season) so
    both a match value and its season per-90 baseline can be built from the
    same non-double-counting logic.

    Broader than the indirect-free-kick bar section: this includes direct
    free-kick shots too, since it's about every set-piece chance created.
    Goals are flagged from the shot ``result`` (``SUCCESS``) rather than a
    separate ``GOAL``-actionType row, since the feed emits both for the same
    goal and summing them would double-count it.
    """
    categories = list(CORNER_CATEGORIES) + [FREE_KICK_CATEGORY, THROW_IN_CATEGORY]
    shots = events.loc[
        (events["actionType"] == "SHOT")
        & (events["attackingSquadName"] == team)
        & (events["setPieceCategory"].isin(categories))
    ].copy()
    if shots.empty:
        return shots.assign(is_goal=pd.Series(dtype=bool))
    shots["is_goal"] = shots["result"].astype(str).eq("SUCCESS")
    return shots


def set_piece_shots(ctx: MatchContext, team: str) -> pd.DataFrame:
    """All shots a team created from set-pieces in this match — see
    :func:`set_piece_shots_from_events` for the selection logic."""
    return set_piece_shots_from_events(ctx.match_events, team)


def fk_deliveries(ctx: MatchContext, team: str) -> pd.DataFrame:
    """Indirect free-kick deliveries *and* direct free-kick attempts for a team.

    Direct free-kicks (shots straight at goal) are tagged ``fk_group == "DIRECT"``
    so the pitch map can distinguish them from played-in deliveries.
    """
    ev = ctx.match_events
    scoring = _scoring_set_piece_ids(ev)

    def group(t: str) -> str:
        t = str(t)
        # Distinguish a driven cross from a lofted high ball from deep.
        if "CROSS" in t:
            return "CROSS"
        if "HIGH_BALL" in t:      # includes HIGH_BALL and HIGH_BALL_BOX
            return "HIGH_BALL"
        # Everything else played into the game = short / recycled / worked.
        return "SHORT"

    indirect = ev.loc[_indirect_fk_delivery(ev) & (ev["attackingSquadName"] == team)].copy()
    if not indirect.empty:
        indirect["fk_group"] = indirect["setPieceSubPhaseFreeKickType"].map(group)
        indirect["first_touch"] = _first_touch_state(indirect).values

    direct = ev.loc[_direct_fk_shot(ev) & (ev["attackingSquadName"] == team)].copy()
    if not direct.empty:
        direct["fk_group"] = "SHOT"
        # A direct free-kick is the shot; its "first contact" is the strike itself.
        direct["first_touch"] = direct["result"].astype(str).map(
            {"SUCCESS": "won"}
        ).fillna("none").values

    fks = pd.concat([indirect, direct], ignore_index=True)
    if fks.empty:
        return fks.assign(
            fk_group=pd.Series(dtype=str), first_touch=pd.Series(dtype=str),
            led_to_goal=pd.Series(dtype=bool), is_direct=pd.Series(dtype=bool),
        )
    fks["is_direct"] = fks["fk_group"] == "SHOT"
    goal_by_id = _led_to_goal(fks, scoring)
    goal_by_result = fks["is_direct"] & (fks["result"].astype(str) == "SUCCESS")
    fks["led_to_goal"] = (goal_by_id | goal_by_result).values
    return fks


def throw_in_deliveries(ctx: MatchContext, team: str) -> pd.DataFrame:
    """Valid throws, classified identically to the pre-match report.

    ``first_touch`` here encodes **possession**: ``"won"`` when the team keeps the
    ball after the throw (retained), ``"lost"`` otherwise — so the end marker's
    ring reads as retained (green) vs lost (red), which is what matters for the
    short throw-and-retain routines.
    """
    ev_all = _chronological(ctx.match_events)
    mask = (ev_all["actionType"] == "THROW_IN") & (ev_all["attackingSquadName"] == team)
    positions = np.where(mask.to_numpy())[0]
    throws = ev_all[mask].copy()
    if throws.empty:
        return throws.assign(
            throw_group=pd.Series(dtype=str), first_touch=pd.Series(dtype=str),
            retained=pd.Series(dtype=bool), led_to_goal=pd.Series(dtype=bool),
        )

    retained = []
    for pos in positions:
        nxt = ev_all.iloc[pos + 1 : pos + 3]
        nxt = nxt[nxt["squadName"].astype(str) != "nan"]
        retained.append(bool(len(nxt)) and str(nxt.iloc[0]["squadName"]) == team)

    throws["retained"] = retained
    throws = classify_throw_ins(throws)
    throws = throws.loc[throws["throw_group"] != ANOMALY_THROW].copy()
    throws["first_touch"] = np.where(throws["retained"], "won", "lost")
    throws["led_to_goal"] = _led_to_goal(throws, _scoring_set_piece_ids(ctx.match_events)).values
    return throws


# --------------------------------------------------------------------------- #
# Per-player first-contact winners (for the "by team" table variant)
# --------------------------------------------------------------------------- #
# Defending first contacts aren't named in the feed (the first-touch player is
# only recorded when the *attacking* team wins). We recover the defender from the
# next aerial event after the delivery, which matches the official winner exactly
# on the cases the feed does name.
_CONTEST_ACTIONS = {"HEADER", "CLEARANCE", "BLOCK", "INTERCEPTION", "LOOSE_BALL_REGAIN"}


@dataclass
class PlayerContact:
    player: str
    corner_att: int = 0
    corner_def: int = 0
    fk_att: int = 0
    fk_def: int = 0
    shots: int = 0
    goals: int = 0

    @property
    def total(self) -> int:
        return self.corner_att + self.corner_def + self.fk_att + self.fk_def


def _chronological(ev: pd.DataFrame) -> pd.DataFrame:
    order = [c for c in ("period", "gameTimeInSec", "sequenceIndex") if c in ev.columns]
    return ev.sort_values(order).reset_index(drop=True) if order else ev.reset_index(drop=True)


def _next_contact_player(ev: pd.DataFrame, pos: int) -> tuple[str | None, str | None]:
    """Player + squad of the first genuine contact after row ``pos``."""
    for j in range(pos + 1, min(pos + 4, len(ev))):
        row = ev.iloc[j]
        player = str(row.get("playerName"))
        if player in ("nan", "None", ""):
            continue
        if str(row.get("action")) in _CONTEST_ACTIONS:
            return player, str(row.get("squadName"))
        return None, None       # first touch was a pass/reception → uncontested
    return None, None


def build_player_contacts(ctx: MatchContext) -> dict[str, dict[str, "PlayerContact"]]:
    """Per team, ``{player -> PlayerContact}`` of first contacts won."""
    ev = _chronological(ctx.match_events)
    teams = {ctx.home_team, ctx.away_team}
    tally: dict[str, dict[str, PlayerContact]] = {t: {} for t in teams}

    def bump(team: str, player: str, category: str, phase: str) -> None:
        if team not in tally or player in ("nan", "None", ""):
            return
        pc = tally[team].setdefault(player, PlayerContact(player))
        setattr(pc, f"{category}_{phase}", getattr(pc, f"{category}_{phase}") + 1)

    for i in range(len(ev)):
        row = ev.iloc[i]
        action = str(row.get("actionType"))
        is_corner = action == "CORNER"
        is_fk = action == "FREE_KICK" and str(row.get("setPieceSubPhaseFreeKickType")) != FREE_KICK_SHOT_TYPE
        if not (is_corner or is_fk):
            continue
        category = "corner" if is_corner else "fk"
        atk = str(row.get("attackingSquadName"))
        defending = (teams - {atk}).pop() if atk in teams else None
        won = str(row.get("setPieceSubPhaseFirstTouchWon"))
        if won == "True":
            player = str(row.get("setPieceSubPhaseFirstTouchPlayerName"))
            # Guard against feed mis-tags: only credit the attacking team if
            # that player's own (majority-vote) squad this match is actually atk.
            if ctx.player_team.get(player, atk) == atk:
                bump(atk, player, category, "att")
        elif won == "False" and defending is not None:
            player, squad = _next_contact_player(ev, i)
            if player and squad == defending:
                bump(defending, player, category, "def")

    # Include attacking players whose set-piece shot came in a recycled
    # (second-phase) sub-phase, even if they did not win the initial contact.
    # The category propagation in the raw-source loader makes these shots
    # visible through the same set-piece selection used by the headline stats.
    for team in teams:
        shots = set_piece_shots_from_events(ctx.match_events, team)
        for _, shot in shots.iterrows():
            player = str(shot.get("playerName"))
            if player in ("nan", "None", ""):
                continue
            pc = tally[team].setdefault(player, PlayerContact(player))
            pc.shots += 1
            pc.goals += int(bool(shot.get("is_goal", False)))
    return tally


# --------------------------------------------------------------------------- #
# Convenience aggregate
# --------------------------------------------------------------------------- #
@dataclass
class ReportData:
    stat_rows: list[StatRow]
    first_contact: dict[str, "FirstContactTable"]
    player_contacts: dict[str, dict[str, "PlayerContact"]] = field(default_factory=dict)
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
        player_contacts=build_player_contacts(ctx),
        corner_type_counts=type_counts,
    )

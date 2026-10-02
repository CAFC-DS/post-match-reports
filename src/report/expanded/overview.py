"""Team sheet, lineup and match-timeline data for the analyst report's overview.

Built from the Opta feeds already loaded for DVMS: the F7 team sheet (who
started, shirt numbers, formation, goals and assists) and the F24 event log
(paired "player off" / "player on" events give exact substitution minutes,
card events give cards). The Impect event feed has no substitution rows, so
it cannot supply minutes played.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

_T_OFF, _T_ON, _T_CARD = 18, 19, 17

# One x-axis for the match-flow chart and the xG race beneath it. It runs to 98
# (not 95) so stoppage-time events are not cut off at the edge.
X_AXIS_MAX = 98.0
X_AXIS_TICKS = [0, 15, 30, 45, 60, 75, 90]
X_AXIS_LABELS = ["0'", "15'", "30'", "HT", "60'", "75'", "90'"]
_Q_YELLOW, _Q_SECOND_YELLOW, _Q_RED = 31, 32, 33
_ABBREV = {"Goalkeeper": "GK", "Defender": "DEF", "Midfielder": "MID", "Forward": "FWD", "Striker": "FWD"}


@dataclass
class SheetPlayer:
    player_id: str
    name: str
    last_name: str
    shirt: int | None
    starter: bool
    role: str                       # e.g. "RB"; a sub inherits the role of who they replaced
    on_min: float = 0.0
    off_min: float | None = None
    goals: list[int] = field(default_factory=list)
    assists: list[int] = field(default_factory=list)
    yellows: list[int] = field(default_factory=list)
    reds: list[int] = field(default_factory=list)
    replaced: str | None = None     # id of the player a substitute came on for
    played: bool = True             # False for unused substitutes
    pos_class: str = ""             # F7 class: Goalkeeper / Defender / Midfielder / Striker

    def minutes(self, match_end: float) -> int:
        if not self.played:
            return 0
        return int(round((self.off_min if self.off_min is not None else match_end) - self.on_min))


@dataclass
class TeamSheet:
    team_id: str
    side: str            # "home" / "away"
    name: str
    formation: str       # "4231" (Opta) or ""
    players: list[SheetPlayer]

    @property
    def starters(self) -> list[SheetPlayer]:
        return [p for p in self.players if p.starter]

    @property
    def substitutes(self) -> list[SheetPlayer]:
        return [p for p in self.players if not p.starter]


def _clock(row) -> float:
    return float(row["minute"]) + float(row["second"]) / 60.0


def match_end_minute(f24_events: pd.DataFrame) -> float:
    played = f24_events[f24_events["period_id"].isin([1, 2, 3, 4])]
    return max(90.0, float(np.ceil(max((_clock(r) for _, r in played.iterrows()), default=90.0))))


def substitution_pairs(f24_events: pd.DataFrame, team_id: str) -> list[dict[str, Any]]:
    """``[{"off": id, "on": id, "minute": float}]`` in match order.

    Opta records a substitution as an "off" event immediately followed by an
    "on" event for the same team, so each "on" is matched with the oldest
    unmatched "off".
    """
    ev = f24_events[(f24_events["team_id"].astype(str) == str(team_id))
                    & f24_events["type_id"].isin([_T_OFF, _T_ON])]
    ev = ev.sort_values(["period_id", "minute", "second", "seq"])
    pending: list[tuple[str, float]] = []
    pairs: list[dict[str, Any]] = []
    for _, row in ev.iterrows():
        if row["type_id"] == _T_OFF:
            pending.append((str(row["player_id"]), _clock(row)))
        elif pending:
            off_id, minute = pending.pop(0)
            pairs.append({"off": off_id, "on": str(row["player_id"]), "minute": minute})
    return pairs


def card_events(f24_events: pd.DataFrame, team_id: str) -> list[dict[str, Any]]:
    """``[{"player": id, "kind": "yellow"|"red", "minute": int}]``.

    A second yellow is reported as a red (the first yellow is its own event).
    """
    ev = f24_events[(f24_events["team_id"].astype(str) == str(team_id))
                    & (f24_events["type_id"] == _T_CARD)]
    out = []
    for _, row in ev.iterrows():
        quals = row["qualifiers"] if isinstance(row["qualifiers"], dict) else {}
        if _Q_RED in quals or _Q_SECOND_YELLOW in quals:
            kind = "red"
        elif _Q_YELLOW in quals:
            kind = "yellow"
        else:
            continue
        out.append({"player": str(row["player_id"]), "kind": kind, "minute": int(row["minute"])})
    return out


# --------------------------------------------------------------------------- #
# Formation rows and role labels
# --------------------------------------------------------------------------- #
def formation_rows(formation: str) -> list[int] | None:
    """``"4231"`` -> ``[4, 2, 3, 1]`` (defence to attack); None if unusable."""
    digits = [int(c) for c in str(formation or "") if c.isdigit()]
    return digits if digits and sum(digits) == 10 else None


def role_labels(rows: list[int]) -> list[list[str]]:
    """Left-to-right role labels for each outfield row of a formation."""
    def defence(n: int) -> list[str]:
        return {2: ["LCB", "RCB"], 3: ["LCB", "CB", "RCB"], 4: ["LB", "LCB", "RCB", "RB"],
                5: ["LWB", "LCB", "CB", "RCB", "RWB"]}.get(n, ["CB"] * n)

    def attack(n: int) -> list[str]:
        return {1: ["CF"], 2: ["LS", "RS"], 3: ["LW", "CF", "RW"]}.get(n, ["CF"] * n)

    def midfield(n: int, depth: str) -> list[str]:
        if depth == "AM":
            return {1: ["AM"], 2: ["LAM", "RAM"], 3: ["LW", "AM", "RW"], 4: ["LW", "LAM", "RAM", "RW"]}.get(n, ["AM"] * n)
        if depth == "DM":
            return {1: ["DM"], 2: ["LDM", "RDM"], 3: ["LDM", "DM", "RDM"]}.get(n, ["DM"] * n)
        return {1: ["CM"], 2: ["LCM", "RCM"], 3: ["LCM", "CM", "RCM"], 4: ["LM", "LCM", "RCM", "RM"],
                5: ["LM", "LCM", "CM", "RCM", "RM"]}.get(n, ["CM"] * n)

    labels = [defence(rows[0])]
    mids = rows[1:-1]
    for i, n in enumerate(mids):
        if len(mids) == 1:
            depth = "CM"
        elif i == 0:
            depth = "DM"
        elif i == len(mids) - 1:
            depth = "AM"
        else:
            depth = "CM"
        labels.append(midfield(n, depth))
    labels.append(attack(rows[-1]))
    return labels


def lineup_slots(sheet: TeamSheet, positions: dict[str, tuple[float, float]] | None,
                 roles: dict[str, tuple[str, int]] | None = None) -> list[dict[str, Any]]:
    """Place the starters on a formation grid.

    ``positions`` maps player id -> (depth, lateral) from tracking: depth grows
    towards the opponent's goal, lateral grows towards the attacker's left. The
    grid gives every player a row from the formation string (defenders, then
    midfielders, then strikers, each ordered by depth, fill the rows from the
    back) and a left-to-right order inside the row.
    Returns ``[]`` (no lineup graphic) when there are no tracked positions or
    the formation string does not describe the ten outfielders.
    """
    starters = sheet.starters
    keeper = [p for p in starters if p.role == "GK"] or starters[:1]
    outfield = [p for p in starters if p not in keeper]
    rows = formation_rows(sheet.formation)
    if rows is None or sum(rows) != len(outfield):
        return []
    have = positions or {}
    if not all(p.player_id in have for p in outfield):
        return []
    # Class first (F7 is reliable about defender vs midfielder vs striker), then
    # depth inside a class: depth alone mixes full-backs with holding midfielders.
    class_rank = {"Defender": 0, "Midfielder": 1, "Striker": 2, "Forward": 2}
    ordered = sorted(outfield, key=lambda p: (class_rank.get(p.pos_class, 1), have[p.player_id][0]))
    labels = role_labels(rows)
    slots = [{"player": keeper[0], "row": 0, "x": 0.0, "role": "GK", "rows": len(rows) + 1}]
    cursor = 0
    for r, n in enumerate(rows, start=1):
        members = ordered[cursor:cursor + n]
        # Left to right: Impect's side tag when present (robust to inverted
        # full-backs and drifting wingers), otherwise tracked lateral position.
        group = sorted(members, key=lambda p: (roles[p.player_id][1], -have[p.player_id][1])
                       if roles and p.player_id in roles else (2, -have[p.player_id][1]))
        cursor += n
        for i, p in enumerate(group):
            x = (i + 1) / (n + 1)
            role = roles[p.player_id][0] if roles and p.player_id in roles else labels[r - 1][i]
            slots.append({"player": p, "row": r, "x": x, "role": role, "rows": len(rows) + 1})
    return slots


def build_team_sheets(f7, f24_events: pd.DataFrame,
                      avg_positions: dict[str, pd.DataFrame] | None = None,
                      to_adj=None,
                      impect_events: pd.DataFrame | None = None) -> tuple[dict[str, TeamSheet], float]:
    """``({"home": sheet, "away": sheet}, match_end_minute)``.

    ``avg_positions`` is ``DvmsMatch.avg_positions`` (per-side frames with
    ``opta_id``, ``phase``, ``x``, ``y`` in metres) and ``to_adj`` converts
    those to the 105x68 frame. When tracking has not been preprocessed the
    lineup falls back to the median location of each starter's Impect events
    (``impect_events``). All three are optional and only place the lineup.
    """
    lineups = f7.lineups
    match_end = match_end_minute(f24_events)
    sheets: dict[str, TeamSheet] = {}
    for side, meta in (("home", f7.home), ("away", f7.away)):
        team_lineup = lineups[lineups["team_id"] == meta.team_id]
        players: dict[str, SheetPlayer] = {}
        for _, row in team_lineup.iterrows():
            starter = row["status"] == "Start"
            pid = str(row["player_id"])
            players[pid] = SheetPlayer(
                player_id=pid, name=str(row["full_name"]), last_name=str(row["last_name"]),
                shirt=int(row["shirt_number"]) if pd.notna(row["shirt_number"]) else None,
                starter=starter, played=starter,
                pos_class=str(row["position"] if starter else row["sub_position"]),
                role=_ABBREV.get(str(row["position"]) if starter else str(row["sub_position"]),
                                 str(row["position"])[:3].upper()),
            )

        for pair in substitution_pairs(f24_events, meta.team_id):
            off, on = players.get(pair["off"]), players.get(pair["on"])
            if off is not None:
                off.off_min = pair["minute"]
            if on is not None:
                on.on_min, on.played, on.replaced = pair["minute"], True, pair["off"]

        for goal in f7.goals:
            scorer = players.get(str(goal.scorer_id))
            if scorer is not None and str(goal.team_id) == meta.team_id:
                scorer.goals.append(int(goal.minute))
            assister = players.get(str(goal.assist_id)) if goal.assist_id else None
            if assister is not None:
                assister.assists.append(int(goal.minute))
        for card in card_events(f24_events, meta.team_id):
            player = players.get(card["player"])
            if player is not None:
                (player.reds if card["kind"] == "red" else player.yellows).append(card["minute"])

        sheet = TeamSheet(team_id=meta.team_id, side=side, name=meta.name,
                          formation=meta.formation, players=list(players.values()))
        positions = _positions_for(avg_positions, side, to_adj, sheet) or impect_positions(impect_events, sheet)
        _assign_roles(sheet, positions, impect_roles(impect_events, sheet))
        sheets[side] = sheet
    return sheets, match_end


def _positions_for(avg_positions, side, to_adj, sheet: TeamSheet) -> dict[str, tuple[float, float]] | None:
    if not avg_positions or to_adj is None:
        return None
    frame = avg_positions.get(side)
    if frame is None or frame.empty:
        return None
    frame = frame[frame["phase"] == "in_possession"]
    starters = {p.player_id for p in sheet.starters}
    frame = frame[frame["opta_id"].astype(str).isin(starters)]
    if frame.empty:
        return None
    ax, ay = to_adj(frame["x"], frame["y"])
    return {str(pid): (float(x), float(y)) for pid, x, y in zip(frame["opta_id"], ax, ay)}


def _norm(name: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(name).lower())
                   if c.isalnum() or c == " ").strip()


def _impect_squad(events: pd.DataFrame | None, sheet: TeamSheet) -> pd.DataFrame | None:
    if events is None or events.empty or "playerName" not in events.columns:
        return None
    squad = events[events["squadName"].astype(str).str.lower() == sheet.name.lower()]
    squad = squad[squad["playerName"].notna()]
    return None if squad.empty else squad


def _impect_names(squad: pd.DataFrame, sheet: TeamSheet) -> dict[str, str]:
    """F7 player id -> Impect playerName.

    Impect and Opta share no player id, so a player is matched on the full
    name, then on the last word of their last name when that is unique in
    the squad.
    """
    by_full = {_norm(n): n for n in squad["playerName"].unique()}
    by_last: dict[str, list[str]] = {}
    for n in squad["playerName"].unique():
        by_last.setdefault(_norm(n).split()[-1], []).append(n)
    out: dict[str, str] = {}
    for p in sheet.players:
        match = by_full.get(_norm(p.name))
        if match is None:
            candidates = by_last.get(_norm(p.last_name).split()[-1], [])
            match = candidates[0] if len(candidates) == 1 else None
        if match is not None:
            out[p.player_id] = match
    return out


def impect_positions(events: pd.DataFrame | None, sheet: TeamSheet) -> dict[str, tuple[float, float]] | None:
    """Median event location per starter, matched to Impect by name."""
    squad = _impect_squad(events, sheet)
    if squad is None:
        return None
    squad = squad[squad["startAdjCoordinatesX"].notna()]
    names = _impect_names(squad, sheet)
    out: dict[str, tuple[float, float]] = {}
    for p in sheet.starters:
        if p.player_id in names:
            rows = squad[squad["playerName"] == names[p.player_id]]
            out[p.player_id] = (float(rows["startAdjCoordinatesX"].median()),
                                float(rows["startAdjCoordinatesY"].median()))
    return out or None


# Impect tags every event with the player's position and side for that match.
_SIDE_RANK = {"LEFT": 0, "CENTRE_LEFT": 1, "CENTRE": 2, "CENTRE_RIGHT": 3, "RIGHT": 4}
_POSITION_LABEL = {
    "GOALKEEPER": "GK", "LEFT_WINGBACK_DEFENDER": "LB", "RIGHT_WINGBACK_DEFENDER": "RB",
    "LEFT_BACK": "LB", "RIGHT_BACK": "RB", "DEFENSE_MIDFIELD": "DM", "CENTRAL_MIDFIELD": "CM",
    "ATTACKING_MIDFIELD": "AM", "LEFT_MIDFIELD": "LM", "RIGHT_MIDFIELD": "RM",
    "LEFT_WINGER": "LW", "RIGHT_WINGER": "RW", "CENTER_FORWARD": "CF", "CENTRE_FORWARD": "CF",
    "SECOND_STRIKER": "SS",
}


def impect_role(position: str | None, side: str | None) -> str | None:
    """``("CENTRAL_DEFENDER", "CENTRE_LEFT")`` -> ``"LCB"``; None if untagged."""
    if not position or not isinstance(position, str):
        return None
    side = side if isinstance(side, str) else ""
    if position == "CENTRAL_DEFENDER":
        return {"CENTRE_LEFT": "LCB", "CENTRE_RIGHT": "RCB"}.get(side, "CB")
    label = _POSITION_LABEL.get(position)
    if label is None:
        return None
    if label in ("DM", "CM") and side in ("CENTRE_LEFT", "LEFT"):
        return "L" + label
    if label in ("DM", "CM") and side in ("CENTRE_RIGHT", "RIGHT"):
        return "R" + label
    return label


def impect_roles(events: pd.DataFrame | None, sheet: TeamSheet) -> dict[str, tuple[str, int]] | None:
    """F7 player id -> (role label, left-to-right rank) from Impect's own
    position tags (the most frequent tag across the player's events)."""
    squad = _impect_squad(events, sheet)
    if squad is None or "playerPosition" not in squad.columns:
        return None
    squad = squad[squad["playerPosition"].notna()]
    names = _impect_names(squad, sheet)
    out: dict[str, tuple[str, int]] = {}
    for pid, name in names.items():
        rows = squad[squad["playerName"] == name]
        if rows.empty:
            continue
        pair = rows.groupby(["playerPosition", "playerPositionSide"], dropna=False).size().idxmax()
        role = impect_role(pair[0], pair[1])
        if role is not None:
            out[pid] = (role, _SIDE_RANK.get(pair[1] if isinstance(pair[1], str) else "CENTRE", 2))
    return out or None


def _assign_roles(sheet: TeamSheet, positions, roles=None) -> None:
    """Give starters a role (Impect's tag, else formation-derived); substitutes
    inherit from whoever they replaced."""
    slots = lineup_slots(sheet, positions, roles)
    by_id = {s["player"].player_id: s["role"] for s in slots}
    for p in sheet.starters:
        p.role = by_id.get(p.player_id, p.role)
    known = {p.player_id: p for p in sheet.players}
    for p in sheet.substitutes:
        if p.replaced and p.replaced in known:
            p.role = known[p.replaced].role


def timeline_events(sheet: TeamSheet) -> list[dict[str, Any]]:
    """Goals, cards and substitutions for one team, for the match timeline."""
    out: list[dict[str, Any]] = []
    for p in sheet.players:
        out += [{"minute": m, "kind": "goal", "player": p.last_name} for m in p.goals]
        out += [{"minute": m, "kind": "yellow", "player": p.last_name} for m in p.yellows]
        out += [{"minute": m, "kind": "red", "player": p.last_name} for m in p.reds]
        if not p.starter and p.played and p.replaced:
            out.append({"minute": p.on_min, "kind": "sub", "player": p.last_name})
    return sorted(out, key=lambda e: e["minute"])


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
def _png_uri(fig, *, tight: bool = True, dpi: int = 200) -> str:
    import base64
    import io

    import matplotlib.pyplot as plt

    from src.report import palette

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight" if tight else None, facecolor=palette.PAPER)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _draw_vertical_pitch(ax, colour: str, aspect: str = "equal") -> None:
    """A plain 68 x 105 pitch, attacking up, in the report's hairline style."""
    from matplotlib.patches import Circle

    ax.set_xlim(-2, 70); ax.set_ylim(-2, 107); ax.set_aspect(aspect); ax.axis("off")
    line = dict(color=colour, lw=.9, solid_capstyle="round")
    ax.plot([0, 68, 68, 0, 0], [0, 0, 105, 105, 0], **line)
    ax.plot([0, 68], [52.5, 52.5], **line)
    ax.add_patch(Circle((34, 52.5), 9.15, fill=False, color=colour, lw=.9))
    for y0, y1, yg in ((0, 16.5, 5.5), (105, 88.5, 99.5)):
        ax.plot([13.84, 13.84, 54.16, 54.16], [y0, y1, y1, y0], **line)
        ax.plot([24.84, 24.84, 43.16, 43.16], [y0, yg, yg, y0], **line)


def lineup_chart(slots: list[dict[str, Any]], is_charlton: bool, match_end: float) -> str:
    """Starting XI on a formation grid, attacking up; number in the disc, surname below."""
    import matplotlib.pyplot as plt

    from src.report import palette

    fig, ax = plt.subplots(figsize=(2.9, 5.5), facecolor=palette.PAPER)     # stretched downwards: taller than true scale
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_facecolor(palette.PAPER_2)
    _draw_vertical_pitch(ax, palette.HAIR, aspect="auto")
    colour = palette.CHARLTON_RED if is_charlton else palette.OPPONENT_GREY
    n_rows = slots[0]["rows"] if slots else 5
    for s in slots:
        player = s["player"]
        x = 6 + s["x"] * 56 if s["row"] else 34
        y = 9 + s["row"] * (84 / max(n_rows - 1, 1))
        ax.scatter([x], [y], s=560, c=colour, edgecolors=palette.PAPER, linewidths=1.6, zorder=3)
        ax.text(x, y, "" if player.shirt is None else str(player.shirt), ha="center", va="center",
                fontsize=10.5, fontweight="bold", color="white", zorder=4)
        ax.text(x, y - 6.8, player.last_name.split()[-1], ha="center", va="top", fontsize=7.8,
                fontweight="bold", color=palette.INK, zorder=4)
        if player.off_min is not None:
            ax.text(x, y - 11.9, f"▼ {int(player.off_min)}'", ha="center", va="top", fontsize=6.6,
                    color=palette.MUTED, zorder=4)
    return _png_uri(fig, tight=False)


def _merge_substitutions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One marker per moment: substitutions within a minute of each other become
    a single "A / B 82'" event so their labels never overprint."""
    out: list[dict[str, Any]] = []
    for e in events:
        prev = out[-1] if out else None
        if (e["kind"] == "sub" and prev is not None and prev["kind"] == "sub"
                and abs(float(e["minute"]) - float(prev["minute"])) <= 1.0):
            prev["player"] = f"{prev['player']} / {e['player']}"
        else:
            out.append(dict(e))
    return out


def _style_time_axis(ax, font: float) -> None:
    """The 0-98 minute axis shared by the flow chart, the timeline and the xG race,
    so their x-axes line up when they are printed under one another."""
    from src.report import palette

    ax.set_xlim(0, X_AXIS_MAX)
    ax.set_xticks(X_AXIS_TICKS)
    ax.set_xticklabels(X_AXIS_LABELS)
    ax.tick_params(labelsize=font, colors=palette.MUTED, length=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(palette.HAIR)
    ax.axvline(45, color=palette.HAIR, linewidth=1.0, linestyle=(0, (3, 3)), zorder=1)


def flow_timeline_chart(x, y, *, y_label: str = "Territory (m)", figsize=(16.0, 3.9), font: float = 10.5) -> str:
    """Match flow: the rolling territory wave (``y`` > 0 is the subject's
    attacking half, red; below zero is the opponent's, grey) on the 0-98 minute
    axis. The figure width and margins match the timeline and the xG race, so
    the x-axes line up. Set at print size (the figure is shown at about two
    thirds of its width)."""
    import matplotlib.pyplot as plt
    import numpy as np

    from src.report import palette

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    peak = max(float(np.abs(y).max()) if len(y) else 0.0, 5.0)
    fig, ax = plt.subplots(figsize=figsize, facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.07 if figsize[0] > 8 else 0.15, right=0.99, top=0.97, bottom=0.12 if figsize[1] > 2.5 else 0.17)
    ax.set_facecolor(palette.PAPER)
    ax.fill_between(x, y, 0, where=y >= 0, interpolate=True, color=palette.CHARLTON_RED, alpha=.9, linewidth=0, zorder=3)
    ax.fill_between(x, y, 0, where=y <= 0, interpolate=True, color=palette.OPPONENT_GREY, alpha=.85, linewidth=0, zorder=3)
    ax.plot(x, y, color=palette.INK, linewidth=.7, alpha=.35, zorder=4)
    ax.axhline(0, color=palette.INK, linewidth=1.0, zorder=5)
    _style_time_axis(ax, font)
    ax.set_ylim(-peak * 1.2, peak * 1.2)
    ax.set_ylabel(y_label, fontsize=font, color=palette.MUTED)
    return _png_uri(fig, tight=False, dpi=200)


def timeline_chart(timeline_by_team: list[tuple[str, bool, list[dict[str, Any]]]]) -> str:
    """Match timeline: each team's goals, cards and substitutions on the 0-98
    minute axis, the subject above the line and the opponent below it.

    One type scale (goals bold, everything else regular); substitutions at the
    same minute share one label; labels stack on three levels so they never
    overlap and late events are pulled inside the axis.

    ``timeline_by_team`` is ``[(team name, is_subject, events), ...]`` as
    returned by :func:`timeline_events`.
    """
    import matplotlib.patheffects as pe
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    from src.report import palette

    font, levels, x_max = 10.5, 4, X_AXIS_MAX
    base, label_gap, step = .5, .26, .45          # in marker units: lane offset, label offset, label level spacing
    fig, ax = plt.subplots(figsize=(16.0, 2.6), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.07, right=0.99, top=0.99, bottom=0.2)
    ax.set_facecolor(palette.PAPER)
    _style_time_axis(ax, font)
    ax.set_ylim(-2.5, 2.5)
    ax.set_yticks([])
    ax.spines["bottom"].set_visible(False)
    ax.axhline(0, color=palette.INK, linewidth=1.0, zorder=5)

    halo = [pe.withStroke(linewidth=2.6, foreground=palette.PAPER)]
    char_w = .56                       # width of one character in minutes at this size
    for lane, (team, is_subject, events) in enumerate(timeline_by_team):
        sign = 1 if lane == 0 else -1
        colour = palette.CHARLTON_RED if is_subject else palette.OPPONENT_GREY
        right_edge = [-99.0] * levels  # where each label level is already occupied up to
        for e in _merge_substitutions(events):
            m, kind = min(float(e["minute"]), x_max - 1.6), e["kind"]
            y0 = sign * base
            if kind == "goal":
                ax.scatter([m], [y0], s=170, c=colour, edgecolors=palette.PAPER, linewidths=1.3, zorder=6)
            elif kind in ("yellow", "red"):
                face = "#e0b12a" if kind == "yellow" else palette.CHARLTON_RED_DARK
                ax.add_patch(FancyBboxPatch((m - .55, y0 - .2), 1.1, .4, boxstyle="round,pad=0,rounding_size=.15",
                                            facecolor=face, edgecolor="none", zorder=6))
            else:
                ax.scatter([m], [y0], s=95, marker="^" if sign > 0 else "v", c=palette.SUCCESS_GREEN,
                           edgecolors=palette.PAPER, linewidths=.9, zorder=6)
            text = f"{e['player']} {int(e['minute'])}'"
            half = len(text) * char_w / 2
            centre = min(max(m, half + .3), x_max - half - .3)       # keep the label inside the axes
            level = next((i for i in range(levels) if centre - half > right_edge[i] + .8), levels - 1)
            right_edge[level] = centre + half
            label_y = sign * (base + label_gap + level * step)
            if level:                                                   # a thin stem ties a raised label to its marker
                ax.plot([m, m], [sign * (base + .16), label_y - sign * .03], color=palette.HAIR, linewidth=.8, zorder=2)
            ax.text(centre, label_y, text, ha="center",
                    va="bottom" if sign > 0 else "top", fontsize=font, zorder=7, path_effects=halo,
                    fontweight="bold" if kind == "goal" else "normal",
                    color=colour if kind == "goal" else palette.INK)
    legend = [(f"{timeline_by_team[0][0]} (above)", palette.CHARLTON_RED, "\u25cf"),
              (f"{timeline_by_team[1][0]} (below)", palette.OPPONENT_GREY, "\u25cf")] if len(timeline_by_team) > 1 else []
    legend += [("goal", palette.INK, "\u25cf"), ("yellow card", "#c99a1c", "\u25a0"),
               ("red card", palette.CHARLTON_RED_DARK, "\u25a0"), ("substitution (player on)", palette.SUCCESS_GREEN, "\u25b2")]
    x0 = 0.07
    for label, face, marker in legend:
        fig.text(x0, 0.015, f"{marker} {label}", fontsize=font, color=face, ha="left")
        x0 += 0.012 * len(label) * .62 + 0.04
    return _png_uri(fig, tight=False, dpi=200)


# --------------------------------------------------------------------------- #
# Template context
# --------------------------------------------------------------------------- #
def _formation_label(formation: str) -> str:
    rows = formation_rows(formation)
    return "-".join(str(n) for n in rows) if rows else (formation or "")


def _sheet_rows(players: list[SheetPlayer], match_end: float) -> list[dict[str, Any]]:
    rows = []
    for p in players:
        marks: list[dict[str, Any]] = []
        marks += [{"kind": "goal", "text": f"{m}'"} for m in p.goals]
        marks += [{"kind": "assist", "text": f"{m}'"} for m in p.assists]
        marks += [{"kind": "yellow", "text": f"{m}'"} for m in p.yellows]
        marks += [{"kind": "red", "text": f"{m}'"} for m in p.reds]
        if not p.starter and p.played:
            marks.append({"kind": "on", "text": f"{int(p.on_min)}'"})
        if p.off_min is not None:
            marks.append({"kind": "off", "text": f"{int(p.off_min)}'"})
        rows.append({"shirt": "" if p.shirt is None else p.shirt, "name": p.name, "role": p.role,
                     "minutes": p.minutes(match_end), "marks": marks})
    return rows


def team_goals(f7, team_id: str) -> list[dict[str, Any]]:
    """``[{"who", "min", "assist"}]`` for goals *credited to* ``team_id``
    (an own goal counts for the side it benefits), in match order."""
    names = {str(r["player_id"]): str(r["last_name"]) for _, r in f7.lineups.iterrows()}
    out = []
    for goal in sorted(f7.goals, key=lambda g: (g.minute, g.second or 0)):
        if str(goal.team_id) != str(team_id):
            continue
        out.append({"who": names.get(str(goal.scorer_id), "?"), "min": f"{int(goal.minute)}'",
                    "assist": names.get(str(goal.assist_id)) if goal.assist_id else None})
    return out


def half_time_score(f7, f24_events: pd.DataFrame) -> dict[str, int]:
    """Goals per team id scored in the first half. Each F7 goal is matched to its
    F24 goal event (same player, within a minute) for the period; without a
    match it falls back to "minute <= 45"."""
    goal_events = f24_events[f24_events["type_id"] == 16]
    out: dict[str, int] = {f7.home.team_id: 0, f7.away.team_id: 0}
    for goal in f7.goals:
        hit = goal_events[(goal_events["player_id"].astype(str) == str(goal.scorer_id))
                          & ((goal_events["minute"] - int(goal.minute)).abs() <= 1)]
        first_half = bool((hit["period_id"] == 1).any()) if len(hit) else int(goal.minute) <= 45
        if first_half and str(goal.team_id) in out:
            out[str(goal.team_id)] += 1
    return out


def overview_context(f7, f24_events: pd.DataFrame, avg_positions, to_adj, impect_events: pd.DataFrame,
                     subject: str) -> dict[str, Any]:
    """Everything the overview page needs: per-team sheet rows, lineup images
    and the timeline image. Teams are ordered subject first."""
    sheets, match_end = build_team_sheets(f7, f24_events, avg_positions, to_adj, impect_events)
    ordered = sorted(sheets.values(), key=lambda sh: sh.name.lower() != subject.lower())
    cards = []
    for sheet in ordered:
        is_subject = sheet.name.lower() == subject.lower()
        slots = lineup_slots(sheet, _positions_for(avg_positions, sheet.side, to_adj, sheet)
                             or impect_positions(impect_events, sheet), impect_roles(impect_events, sheet))
        used = [p for p in sheet.substitutes if p.played]
        cards.append({
            "name": sheet.name, "is_charlton": is_subject,
            "formation": _formation_label(sheet.formation),
            "lineup_img": lineup_chart(slots, is_subject, match_end) if slots else "",
            "starters": _sheet_rows(sheet.starters, match_end),
            "subs": _sheet_rows(used, match_end),
            "unused": len(sheet.substitutes) - len(used),
            "unused_names": [p.last_name for p in sheet.substitutes if not p.played],
            "score": int(f7.home.score if sheet.side == "home" else f7.away.score),
            "goals": team_goals(f7, sheet.team_id),
            "ht": half_time_score(f7, f24_events)[sheet.team_id],
        })
    timeline_by_team = [(sh.name, sh.name.lower() == subject.lower(), timeline_events(sh)) for sh in ordered]
    return {"team_sheets": cards, "timeline_by_team": timeline_by_team, "match_end_minute": match_end}

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


def lineup_slots(sheet: TeamSheet, positions: dict[str, tuple[float, float]] | None) -> list[dict[str, Any]]:
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
        group = sorted(ordered[cursor:cursor + n], key=lambda p: -have[p.player_id][1])  # left first
        cursor += n
        for i, p in enumerate(group):
            x = (i + 1) / (n + 1)
            slots.append({"player": p, "row": r, "x": x, "role": labels[r - 1][i], "rows": len(rows) + 1})
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
        _assign_roles(sheet, positions)
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


def impect_positions(events: pd.DataFrame | None, sheet: TeamSheet) -> dict[str, tuple[float, float]] | None:
    """Median event location per starter, matched to Impect by name.

    Impect and Opta share no player id, so a starter is matched on the full
    name, then on the last word of their last name within the same squad.
    """
    if events is None or events.empty or "playerName" not in events.columns:
        return None
    squad = events[events["squadName"].astype(str).str.lower() == sheet.name.lower()]
    squad = squad[squad["playerName"].notna() & squad["startAdjCoordinatesX"].notna()]
    if squad.empty:
        return None
    by_full = {_norm(n): n for n in squad["playerName"].unique()}
    by_last: dict[str, list[str]] = {}
    for n in squad["playerName"].unique():
        by_last.setdefault(_norm(n).split()[-1], []).append(n)
    out: dict[str, tuple[float, float]] = {}
    for p in sheet.starters:
        match = by_full.get(_norm(p.name))
        if match is None:
            candidates = by_last.get(_norm(p.last_name).split()[-1], [])
            match = candidates[0] if len(candidates) == 1 else None
        if match is None:
            continue
        rows = squad[squad["playerName"] == match]
        out[p.player_id] = (float(rows["startAdjCoordinatesX"].median()),
                            float(rows["startAdjCoordinatesY"].median()))
    return out or None


def _assign_roles(sheet: TeamSheet, positions) -> None:
    """Give starters formation-derived roles; substitutes inherit from whoever they replaced."""
    slots = lineup_slots(sheet, positions)
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


def _draw_vertical_pitch(ax, colour: str) -> None:
    """A plain 68 x 105 pitch, attacking up, in the report's hairline style."""
    from matplotlib.patches import Circle

    ax.set_xlim(-2, 70); ax.set_ylim(-2, 107); ax.set_aspect("equal"); ax.axis("off")
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

    fig, ax = plt.subplots(figsize=(2.9, 4.35), facecolor=palette.PAPER)
    fig.subplots_adjust(0, 0, 1, 1)
    ax.set_facecolor(palette.PAPER_2)
    _draw_vertical_pitch(ax, palette.HAIR)
    colour = palette.CHARLTON_RED if is_charlton else palette.OPPONENT_GREY
    n_rows = slots[0]["rows"] if slots else 5
    for s in slots:
        player = s["player"]
        x = 6 + s["x"] * 56 if s["row"] else 34
        y = 9 + s["row"] * (84 / max(n_rows - 1, 1))
        ax.scatter([x], [y], s=430, c=colour, edgecolors=palette.PAPER, linewidths=1.6, zorder=3)
        ax.text(x, y, "" if player.shirt is None else str(player.shirt), ha="center", va="center",
                fontsize=8.5, fontweight="bold", color="white", zorder=4)
        ax.text(x, y - 6.3, player.last_name.split()[-1], ha="center", va="top", fontsize=6.0,
                fontweight="bold", color=palette.INK, zorder=4)
        if player.off_min is not None:
            ax.text(x, y - 10.6, f"▼ {int(player.off_min)}'", ha="center", va="top", fontsize=5.6,
                    color=palette.MUTED, zorder=4)
    return _png_uri(fig, tight=False)


def timeline_chart(events_by_team: list[tuple[str, bool, list[dict[str, Any]]]], match_end: float) -> str:
    """Both teams' goals, cards and substitutions on one 0-90+ axis.

    ``events_by_team`` is ``[(team name, is_charlton, events), ...]`` and is
    drawn top to bottom in that order.
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    from src.report import palette

    fig, ax = plt.subplots(figsize=(13.6, 2.35), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.115, right=0.985, top=0.93, bottom=0.2)
    ax.set_facecolor(palette.PAPER)
    end = max(match_end, 90.0)
    ax.set_xlim(-1.5, end + 1.5)
    ax.set_ylim(-1.75, 1.75)
    ax.axvspan(0, 45, color=palette.PAPER_2, zorder=0)
    ax.axvline(45, color=palette.HAIR, lw=1.0, zorder=1)
    ax.axhline(0, color=palette.INK, lw=.8, zorder=1)
    ax.set_yticks([]); ax.spines[:].set_visible(False)
    ticks = [0, 15, 30, 45, 60, 75, 90] + ([int(end)] if end > 92 else [])
    ax.set_xticks(ticks)
    ax.set_xticklabels(["0'", "15'", "30'", "HT", "60'", "75'", "90'"] + ([f"{int(end)}'"] if end > 92 else []),
                       fontsize=7.5, color=palette.MUTED)
    ax.tick_params(length=0)

    for lane, (team, is_charlton, events) in enumerate(events_by_team):
        sign = 1 if lane == 0 else -1
        colour = palette.CHARLTON_RED if is_charlton else palette.OPPONENT_GREY
        fig.text(0.005, 0.5 + sign * 0.28, team.upper(), fontsize=7.5, fontweight="bold", color=colour, va="center")
        last_label_end = {0: -99.0, 1: -99.0, 2: -99.0}
        for e in events:
            m, kind = float(e["minute"]), e["kind"]
            if kind == "goal":
                ax.scatter([m], [sign * .62], s=150, c=colour, edgecolors=palette.PAPER, linewidths=1.2, zorder=4)
                text, size, weight = f"{e['player']} {int(m)}'", 7.2, "bold"
            elif kind in ("yellow", "red"):
                face = "#e0b12a" if kind == "yellow" else palette.CHARLTON_RED_DARK
                ax.add_patch(Rectangle((m - .45, sign * .62 - .2), .9, .4, color=face, zorder=4, lw=0))
                text, size, weight = f"{e['player']} {int(m)}'", 6.3, "normal"
            else:
                ax.scatter([m], [sign * .62], s=42, marker="^" if sign > 0 else "v", c=palette.SUCCESS_GREEN,
                           edgecolors=palette.PAPER, linewidths=.8, zorder=4)
                text, size, weight = f"{e['player']} {int(m)}'", 6.0, "normal"
            # Stack labels on three rows so neighbours never overprint.
            level = next((i for i in range(3) if m - last_label_end[i] > 6.2), 2)
            last_label_end[level] = m
            ax.text(m, sign * (.98 + level * .27), text, ha="center", va="bottom" if sign > 0 else "top",
                    fontsize=size, fontweight=weight, color=colour if kind == "goal" else palette.INK, zorder=5)
    handles = [
        ("goal", "o", palette.INK), ("yellow card", "s", "#e0b12a"),
        ("red card", "s", palette.CHARLTON_RED_DARK), ("substitution (player on)", "^", palette.SUCCESS_GREEN),
    ]
    for i, (label, marker, face) in enumerate(handles):
        fig.text(0.56 + i * 0.105, 0.045, ("●" if marker == "o" else "■" if marker == "s" else "▲") + " " + label,
                 fontsize=6.8, color=face if marker != "o" else palette.INK, ha="left")
    return _png_uri(fig, tight=False)


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
                             or impect_positions(impect_events, sheet))
        used = [p for p in sheet.substitutes if p.played]
        cards.append({
            "name": sheet.name, "is_charlton": is_subject,
            "formation": _formation_label(sheet.formation),
            "lineup_img": lineup_chart(slots, is_subject, match_end) if slots else "",
            "starters": _sheet_rows(sheet.starters, match_end),
            "subs": _sheet_rows(used, match_end),
            "unused": len(sheet.substitutes) - len(used),
        })
    timeline_img = timeline_chart(
        [(sh.name, sh.name.lower() == subject.lower(), timeline_events(sh)) for sh in ordered], match_end)
    return {"team_sheets": cards, "timeline_img": timeline_img, "match_end_minute": match_end}

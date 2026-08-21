"""Derived match metrics, computed directly from the raw IMPECT event log
(``IMPECT_EVENTS_STAGING`` / ``data/processed/match_<id>_events.parquet``).

Every formula here was checked against the club's existing analyst-facing
Tableau post-match report for the Swansea City (A) fixture and matches it
exactly, column for column, unless noted otherwise. See DATA_MODEL.md for the
full validation record. Where this report intentionally uses a cleaner or
better-documented formula than the legacy Tableau workbook (whose internal
calculated-field names did not always match their own formulas), that is
called out explicitly below.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

ATTACKING_ZONES = {"FINAL_THIRD", "OPPONENT_BOX"}

# ``gameTimeInSec`` is NOT a continuous match clock: the second half restarts it
# at an arbitrary 10000s marker (period 1 runs 0 -> ~2940, period 2 runs 10000 ->
# ~13100). It is therefore safe for *ordering* events but useless as a minute.
# The ``gameTime`` string, by contrast, is already absolute match time in both
# halves ("73:40.6120", "45:00.0000 (+04:01.6070)"), so every minute in this
# module is derived from that string via ``minute_num`` / ``_minute_label``.


# --------------------------------------------------------------------------- #
# Match metadata
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MatchMeta:
    match_id: int
    kickoff: pd.Timestamp
    competition: str
    season: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int

    @property
    def charlton_team(self) -> str:
        return self.home_team if self.home_team == "Charlton Athletic" else self.away_team

    @property
    def opponent_team(self) -> str:
        return self.away_team if self.home_team == "Charlton Athletic" else self.home_team

    @property
    def charlton_goals(self) -> int:
        return self.home_goals if self.home_team == "Charlton Athletic" else self.away_goals

    @property
    def opponent_goals(self) -> int:
        return self.away_goals if self.home_team == "Charlton Athletic" else self.home_goals

    @property
    def result(self) -> str:
        if self.charlton_goals > self.opponent_goals:
            return "win"
        if self.charlton_goals < self.opponent_goals:
            return "loss"
        return "draw"


def _team_goals(events: pd.DataFrame, team: str) -> int:
    return int(
        ((events["action"] == "GOAL") & (events["squadName"] == team)).sum()
        + ((events["action"] == "OWN_GOAL") & (events["squadName"] != team)).sum()
    )


def match_meta(events: pd.DataFrame) -> MatchMeta:
    row = events.iloc[0]
    home, away = str(row["homeSquadName"]), str(row["awaySquadName"])
    return MatchMeta(
        match_id=int(row["matchId"]),
        kickoff=pd.to_datetime(row["dateTime"], utc=True),
        competition=str(row["competitionName"]),
        season=str(row["season"]),
        home_team=home,
        away_team=away,
        home_goals=_team_goals(events, home),
        away_goals=_team_goals(events, away),
    )


# --------------------------------------------------------------------------- #
# Goal scorers with minutes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GoalEvent:
    team: str
    player: str
    minute_label: str   # football-standard label, e.g. "74'" / "45+3'"
    minute: float       # numeric minute, for x-axis placement
    game_time_sec: float


def _minute_label(game_time: str) -> str:
    """Football-standard minute label from IMPECT's 'MM:SS.mmm' gameTime
    string (e.g. '73:40.2110' -> "74'"; a goal struck partway through a
    minute falls "in" the next minute, the standard football-commentary
    convention). Stoppage time is expressed relative to the half
    ('45:00.0000 (+02:37.2150)' -> "45+3'").

    This is derived straight from the event clock and may differ by a minute
    or two from a broadcaster's official minute for the same goal — both are
    reading slightly different clocks (video review, whistle vs. ball-crossing
    the line, etc.). It is internally consistent across the whole report.
    """
    base = game_time.split(" ")[0]
    mm_str, ss_str = base.split(":")
    mm, ss = int(mm_str), float(ss_str)
    if "(+" in game_time:
        extra = game_time.split("(+")[1].rstrip(")")
        emm_str, ess_str = extra.split(":")
        emm, ess = int(emm_str), float(ess_str)
        extra_minute = emm + (1 if ess > 0 else 0)
        extra_minute = max(extra_minute, 1)
        return f"{mm}+{extra_minute}'"
    minute = mm + (1 if ss > 0 else 0)
    return f"{minute}'"


def goal_events(events: pd.DataFrame) -> list[GoalEvent]:
    goals = events.loc[events["action"] == "GOAL"].sort_values("gameTimeInSec")
    return [
        GoalEvent(
            team=str(r["squadName"]),
            player=str(r["playerName"]),
            minute_label=_minute_label(str(r["gameTime"])),
            minute=minute_num(str(r["gameTime"])),
            game_time_sec=float(r["gameTimeInSec"]),
        )
        for _, r in goals.iterrows()
    ]


# --------------------------------------------------------------------------- #
# Match stats comparison table
# --------------------------------------------------------------------------- #
# (group, key, label). Twelve rows in three blocks, not the sixteen the analyst
# workbook carries: every row here has to earn a comparison bar and still be
# readable at board-report size, and a board cannot act on the difference
# between sixteen numbers. Cut from the analyst set: unsuccessful passes (already
# implied by successful passes + accuracy), second-ball wins, set-piece xG (the
# club has a dedicated set-piece report), and packing xG (needs a paragraph of
# explanation to mean anything to a non-analyst).
STAT_ROWS: list[tuple[str, str, str]] = [
    ("On the ball", "possession_pct", "Possession"),
    ("On the ball", "pass_accuracy_pct", "Pass accuracy"),
    ("On the ball", "successful_passes", "Successful passes"),
    ("On the ball", "passes_forward_pct", "Passes forward"),
    ("Attack", "shots", "Shots"),
    ("Attack", "shots_on_target", "Shots on target"),
    ("Attack", "non_penalty_xg", "Non-penalty xG"),
    ("Attack", "set_piece_xg", "Set-piece xG"),
    ("Attack", "postshot_xg", "Post-shot xG"),
    ("Duels & pressing", "touches_in_opposition_box", "Touches in opposition box"),
    ("Duels & pressing", "won_ground_duels", "Ground duels won"),
    ("Duels & pressing", "won_aerial_duels", "Aerial duels won"),
    # Spelled out rather than called "opponent-half regains", so it needs no gloss.
    ("Duels & pressing", "opponent_half_regains", "Ball wins in opposition half"),
]

# Only the rows a non-analyst genuinely cannot infer from the label alone, and
# kept short: this gloss has a fixed slot at the foot of the stats panel, and an
# overlong one is simply clipped by it.
STAT_GLOSS: dict[str, str] = {
    "non_penalty_xg": "chance quality created. 1.00 ≈ one clear-cut chance.",
    "set_piece_xg": "the part of it from corners and free-kicks.",
    "postshot_xg": "the same chances, re-priced by where each shot went. Below xG = poor finishing.",
}


def team_stats(events: pd.DataFrame, home: str, away: str) -> pd.DataFrame:
    rows = []
    for team in (home, away):
        t = events.loc[events["squadName"] == team]
        successful_passes = t["SUCCESSFUL_PASSES"].sum()
        unsuccessful_passes = t["UNSUCCESSFUL_PASSES"].sum()
        total_passes = successful_passes + unsuccessful_passes
        forward_passes = (
            (t["endAdjCoordinatesX"] > t["startAdjCoordinatesX"]) & (t["SUCCESSFUL_PASSES"] == 1)
        ).sum()
        opp_half_regains = t.loc[t["startAdjCoordinatesX"] > 0, "BALL_WIN_NUMBER"].sum()
        non_penalty_xg = t.loc[t["action"] != "PENALTY_KICK", "SHOT_XG"].sum()
        set_piece_xg = t.loc[t["phase"] == "SET_PIECE", "SHOT_XG"].sum()
        touches_opp_box = t.loc[t["startPitchPosition"] == "OPPONENT_BOX", "OFFENSIVE_TOUCHES"].sum()
        rows.append(
            {
                "team": team,
                "successful_passes": int(successful_passes),
                "unsuccessful_passes": int(unsuccessful_passes),
                "_total_passes": total_passes,
                "pass_accuracy_pct": (successful_passes / total_passes * 100) if total_passes else 0.0,
                "passes_forward_pct": (forward_passes / successful_passes * 100) if successful_passes else 0.0,
                "opponent_half_regains": int(opp_half_regains),
                "won_ground_duels": int(t["WON_GROUND_DUELS"].sum()),
                "won_aerial_duels": int(t["WON_AERIAL_DUELS"].sum()),
                "second_ball_wins": int(t["SECOND_BALL_WIN"].sum()),
                "shots": int(t["SHOT_AT_GOAL_NUMBER"].sum()),
                "shots_on_target": int(t["SHOT_AT_GOAL_NUMBER_ON_TARGET"].sum()),
                "non_penalty_xg": float(non_penalty_xg),
                "packing_xg": float(t["PACKING_XG"].sum()),
                "set_piece_xg": float(set_piece_xg),
                "postshot_xg": float(t["POSTSHOT_XG"].sum()),
                "touches_in_opposition_box": int(touches_opp_box),
            }
        )
    df = pd.DataFrame(rows).set_index("team")
    total_passes_both = df["_total_passes"].sum()
    df["possession_pct"] = (df["_total_passes"] / total_passes_both * 100) if total_passes_both else 50.0
    return df.drop(columns="_total_passes")


# --------------------------------------------------------------------------- #
# Shot map
# --------------------------------------------------------------------------- #
SHOT_CATEGORY_ORDER = ["Goal", "On target", "Blocked", "Off target", "Other"]


def _shot_category(row: pd.Series) -> str:
    if row.get("SHOT_AT_GOAL_NUMBER_SUCCESS") == 1:
        return "Goal"
    if row.get("SHOT_AT_GOAL_NUMBER_BLOCKED") == 1:
        return "Blocked"
    if row.get("SHOT_AT_GOAL_NUMBER_ON_TARGET") == 1:
        return "On target"
    if row.get("SHOT_AT_GOAL_NUMBER_OTHER") == 1:
        return "Other"
    return "Off target"


def shot_events(events: pd.DataFrame) -> pd.DataFrame:
    shots = events.loc[events["SHOT_AT_GOAL_NUMBER"] == 1].copy()
    shots["category"] = shots.apply(_shot_category, axis=1)
    return shots
def minute_num(game_time: str) -> float:
    """Numeric minute (float, base + fraction) for x-axis placement; stoppage
    time is folded onto the end of its half (45:xx / 90:xx keep climbing past
    45 / 90 rather than resetting), matching how the minute labels read.
    """
    base = game_time.split(" ")[0]
    mm_str, ss_str = base.split(":")
    mm, ss = int(mm_str), float(ss_str)
    minute = mm + ss / 60.0
    if "(+" in game_time:
        extra = game_time.split("(+")[1].rstrip(")")
        emm_str, ess_str = extra.split(":")
        emm, ess = int(emm_str), float(ess_str)
        minute += emm + ess / 60.0
    return minute
# --------------------------------------------------------------------------- #
# Passing network
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PassingNetwork:
    nodes: pd.DataFrame   # playerName, surname, x, y, passes (node size),
                           # threat (node colour: net PXT_PASS from that
                           # player's own passes, +ve/-ve either side of zero),
                           # is_starter (node shape: circle if started, triangle
                           # if they came on as a substitute)
    edges: pd.DataFrame   # a, b, ax, ay, bx, by, passes (line width)
    first_sub_minute: float   # informational only: when the team's first sub came on
    total_passes: int     # successful passes between any two of the team's players, full match


def starting_xi(events: pd.DataFrame, team: str) -> tuple[list[str], float]:
    """The 11 starters and the minute of the team's first substitution.

    The event feed carries no SUBSTITUTION action, so both are inferred from
    first appearances: order the team's players by the minute of their first
    event and take the first 11 as the XI; the 12th player's first event is,
    by definition, the moment the first substitute became involved. In this
    fixture the split is unambiguous (11 players inside the opening 3.2
    minutes, then a clear gap), which is what you would expect from any team
    that did not make an unusually early change.
    """
    t = events.loc[(events["squadName"] == team) & events["playerName"].notna() & (events["playerName"] != "nan")]
    first_seen = t.assign(minute=t["gameTime"].apply(minute_num)).groupby("playerName")["minute"].min().sort_values()
    starters = list(first_seen.index[:11])
    # No 12th player => no substitute ever touched the ball; the window is the whole match.
    until = float(first_seen.iloc[11]) if len(first_seen) > 11 else float("inf")
    return starters, until


def passing_network(events: pd.DataFrame, team: str, min_edge_passes: int = 3,
                     min_node_passes: int = 2) -> PassingNetwork:
    """Passing network for every player who passed for the team across the
    *full match* — starters and substitutes alike, not just the starting XI up
    to the first change.

    An earlier version stopped at the first substitution, on the reasoning that
    a network only means something for a fixed set of eleven: once someone is
    replaced, the "average position" of a shirt stops describing one person.
    That is still true, but in practice it produced its own, worse problem —
    on a fixture with an early change (e.g. a 37th-minute substitution), several
    starters ended up with one or two passes each inside that short window,
    which is not an average position, it is noise from wherever that one touch
    happened to land, and nothing to draw a line to (min_edge_passes filters
    out the resulting stray lines, but not the misleading dot). Using the whole
    match for every player who featured trades a smaller, honest cost — a
    player's average position can blend two shapes either side of a change —
    for a much larger fix: most nodes now rest on a real sample, and
    substitutes are shown rather than silently dropped. Starters and
    substitutes get different markers (circle / triangle, see
    ``pitch.passing_network_map``) precisely so the reader can discount a
    triangle's position accordingly — the same convention the momentum chart
    already uses for a substitute coming on.

    Nodes are undirected pass counts as before: sized by how many passes a
    player played, coloured by the net packing threat (``PXT_PASS``) those
    same passes carried — the passer's own credit, not ``PXT_ATTACK`` (split
    with the receiver, right for a team total but wrong for crediting one
    player) or ``PXT_REC`` (the receiver's side of it). Nodes below
    ``min_node_passes`` are dropped rather than plotted from a single
    misleading touch. Edges keep their own, higher bar (``min_edge_passes``,
    a pair's *combined* passes both ways) so a line still means a real,
    repeated pattern rather than one hopeful ball.
    """
    starters, first_sub = starting_xi(events, team)
    passes = events.loc[
        (events["squadName"] == team)
        & (events["actionType"] == "PASS")
        & (events["result"] == "SUCCESS")
        & events["playerName"].notna() & (events["playerName"] != "nan")
        & events["passReceiverPlayerName"].notna() & (events["passReceiverPlayerName"] != "nan")
    ].copy()

    nodes = (
        passes.groupby("playerName")
        .agg(x=("startAdjCoordinatesX", "mean"), y=("startAdjCoordinatesY", "mean"),
             passes=("playerName", "size"), threat=("PXT_PASS", "sum"))
        .reset_index()
    )
    nodes = nodes.loc[nodes["passes"] >= min_node_passes].copy()
    nodes["surname"] = nodes["playerName"].apply(lambda n: n.split()[-1])
    nodes["is_starter"] = nodes["playerName"].isin(starters)

    pair_key = [tuple(sorted((a, b))) for a, b in zip(passes["playerName"], passes["passReceiverPlayerName"])]
    counts = passes.assign(_pair=pair_key).groupby("_pair").size()
    counts = counts.loc[counts >= min_edge_passes]

    pos = nodes.set_index("playerName")[["x", "y"]]
    edges = pd.DataFrame(
        [
            {"a": a, "b": b, "ax": pos.at[a, "x"], "ay": pos.at[a, "y"],
             "bx": pos.at[b, "x"], "by": pos.at[b, "y"], "passes": int(n)}
            for (a, b), n in counts.items()
            if a in pos.index and b in pos.index
        ],
        columns=["a", "b", "ax", "ay", "bx", "by", "passes"],
    )
    return PassingNetwork(
        nodes=nodes.sort_values("passes", ascending=False).reset_index(drop=True),
        edges=edges.sort_values("passes").reset_index(drop=True),
        first_sub_minute=first_sub,
        total_passes=int(len(passes)),
    )


# --------------------------------------------------------------------------- #
# Momentum + the match timeline that sits on it
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TimelineEvent:
    minute: float
    team: str
    kind: str    # "goal" | "sub" | "yellow" | "red"
    label: str


def momentum(events: pd.DataFrame, team_up: str, team_down: str,
             window: int = 5) -> pd.DataFrame:
    """Rolling net packing expected threat: ``team_up`` positive, ``team_down``
    negative, summed per minute and then totalled over a centred ``window``-minute
    window.

    Built on ``PXT_ATTACK`` — IMPECT's packing expected threat added by the
    attacking action itself, and the only pxT column that can be summed to a team
    total. The player-facing fields cannot: a pass's value is credited twice over,
    to the passer as ``PXT_PASS`` and again to the receiver as ``PXT_REC``.
    ``PXT_ATTACK`` splits that same value across the pass and reception rows, so
    summing it recovers the true total exactly once (Charlton 0.24, Swansea 1.12
    on this fixture — the right way round, unlike any reconstruction from the

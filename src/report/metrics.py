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
                # Packing: raw opponents/defenders taken out of the game by a
                # pass or dribble (expanded report's Progression group).
                # Optional -- older fixtures/tests built before this field
                # existed still get a usable (zero) row rather than a KeyError.
                "opponents_bypassed": int(t["BYPASSED_OPPONENTS"].sum()) if "BYPASSED_OPPONENTS" in t else 0,
                "defenders_bypassed": int(t["BYPASSED_DEFENDERS"].sum()) if "BYPASSED_DEFENDERS" in t else 0,
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
    player-attributed columns).

    A rolling *sum* is deliberately the whole of the method. Because nothing is
    transformed, the y-axis stays in real pxT units and can be labelled and
    ticked honestly: the height of the curve is the net packing xT each side
    created in the surrounding five minutes, and that is a sentence you can say
    out loud to a board. An earlier version smoothed a signed square root of the
    per-event values through a Gaussian kernel, which drew a prettier wave whose
    y-axis was in no unit at all.
    """
    e = events.loc[events["PXT_ATTACK"].notna() & events["squadName"].isin([team_up, team_down])].copy()
    e["minute"] = e["gameTime"].apply(minute_num)
    sign = np.where(e["squadName"] == team_up, 1.0, -1.0)
    e["net"] = e["PXT_ATTACK"].to_numpy() * sign

    last = int(np.ceil(e["minute"].max())) if len(e) else 90
    per_minute = (
        e.groupby(e["minute"].astype(int))["net"].sum()
        .reindex(pd.RangeIndex(0, max(last, 90) + 1), fill_value=0.0)
    )
    rolled = per_minute.rolling(window, center=True, min_periods=1).sum()
    return pd.DataFrame({"minute": rolled.index.to_numpy() + 0.5, "momentum": rolled.to_numpy()})


def timeline(events: pd.DataFrame, home: str, away: str) -> list[TimelineEvent]:
    """Goals, cards and substitutions, for annotating the momentum chart.

    Substitutions are *inferred*: the feed has no SUBSTITUTION action, so a
    substitute's arrival is taken as their first touch of the ball (see
    ``starting_xi``). That lags the real change by however long the player went
    untouched, so the marker says "on" rather than pretending to be the 4th
    official's board.

    Cards come from ``YELLOW_CARD`` / ``SECOND_YELLOW_CARD`` / ``RED_CARD``. Those
    columns exist but are entirely NULL on this warehouse — 19 fouls in the
    reference fixture and not one card recorded — so in practice nothing is
    drawn for them today. The code is here so that the day the feed starts
    populating them, they appear with no further change.
    """
    out: list[TimelineEvent] = [
        TimelineEvent(g.minute, g.team, "goal", g.player.split()[-1]) for g in goal_events(events)
    ]

    for col, kind in (("YELLOW_CARD", "yellow"), ("SECOND_YELLOW_CARD", "red"), ("RED_CARD", "red")):
        if col not in events.columns:
            continue
        carded = events.loc[events[col] == 1]
        for _, r in carded.iterrows():
            out.append(TimelineEvent(minute_num(str(r["gameTime"])), str(r["squadName"]), kind,
                                     str(r["playerName"]).split()[-1]))

    for team in (home, away):
        t = events.loc[(events["squadName"] == team) & events["playerName"].notna() & (events["playerName"] != "nan")]
        first_seen = t.assign(m=t["gameTime"].apply(minute_num)).groupby("playerName")["m"].min().sort_values()
        for player, minute in first_seen.iloc[11:].items():
            out.append(TimelineEvent(float(minute), team, "sub", str(player).split()[-1]))

    return sorted(out, key=lambda e: e.minute)


# --------------------------------------------------------------------------- #
# Final third / penalty box entries
# --------------------------------------------------------------------------- #
def zone_entries(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Passes and carries (dribbles) that start outside the final third /
    opposition box and end inside it — i.e. genuine entries, not the many
    short passes already recycled inside the attacking third.

    ``carry`` separates the two, and it is worth separating: on the reference
    fixture Swansea ran the ball in 16 times to Charlton's 2 (against 46 and 39
    passes respectively), which is a real difference in how the two sides got
    there and is invisible if both are drawn as the same arrow.

    ``threat`` is the packing xT the entry itself added, so the map can show not
    just that a side got in, but whether getting in was worth anything.
    """
    t = events.loc[
        (events["squadName"] == team) & (events["actionType"].isin(["PASS", "DRIBBLE"]))
    ].copy()
    entries = t.loc[
        t["endPitchPosition"].isin(ATTACKING_ZONES) & ~t["startPitchPosition"].isin(ATTACKING_ZONES)
    ].copy()
    entries["success"] = entries["result"] == "SUCCESS"
    entries["carry"] = entries["actionType"] == "DRIBBLE"
    entries["threat"] = entries["PXT_ATTACK"].fillna(0.0).clip(lower=0.0)
    return entries


# --------------------------------------------------------------------------- #
# Where the chances came from
# --------------------------------------------------------------------------- #
# IMPECT's own phase tags, in the order they are shown, with board-readable names.
CHANCE_PHASES: list[tuple[str, str]] = [
    ("SET_PIECE", "Set piece"),
    ("ATTACKING_TRANSITION", "Transition"),
    ("IN_POSSESSION", "Open play"),
    ("SECOND_BALL", "Second ball"),
]


def chance_sources(events: pd.DataFrame, home: str, away: str) -> pd.DataFrame:
    """Non-penalty xG split by the phase of play that produced the shot.

    This is the row of the stats table that turned out to be the story of the
    match, given its own panel: Charlton took 1.08 of their 1.36 xG from set
    pieces and created 0.07 in open play across ninety minutes, while Swansea's
    single biggest source was the counter-attack (0.71).
    """
    shots = shot_events(events)
    shots = shots.loc[shots["action"] != "PENALTY_KICK"]
    out = pd.DataFrame(index=[label for _, label in CHANCE_PHASES])
    for team in (home, away):
        t = shots.loc[shots["squadName"] == team]
        out[team] = [float(t.loc[t["phase"] == key, "SHOT_XG"].sum()) for key, _ in CHANCE_PHASES]
    return out


# --------------------------------------------------------------------------- #
# Season context: where this result leaves us
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeasonContext:
    position: int
    played: int
    points: int
    goal_difference: int
    form: list[str]          # oldest -> newest, "W"/"D"/"L", this match last
    form_opponents: list[str]


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def season_context(results: pd.DataFrame, team: str, as_of: pd.Timestamp,
                    form_matches: int = 6) -> SeasonContext:
    """League position, points and recent form *as at* this fixture.

    ``results``: one row per league match (see sql/extracts/season_results.sql).
    Only matches played up to and including the reported one are counted, so a
    report generated for a mid-season fixture shows the table as it stood that
    day rather than as it stands now — the board is being told where *this
    result* left the club, which is the whole point of the strip.
    """
    r = results.copy()
    r["kickoff_utc"] = pd.to_datetime(r["kickoff_utc"], utc=True)

    # Drop duplicate ingests of the same fixture. In a double round-robin a pair
    # of teams meets exactly twice, once at each ground, so a second row with the
    # SAME home team and away team is by definition an artefact -- and there is
    # one in this warehouse: Blackburn Rovers v Sheffield Wednesday is present as
    # both matchId 206746 (06/12/2025) and matchId 245449 (03/02/2026), identical
    # venue, identical 1-0 scoreline. It is not a postponement or a replay, it is
    # the same match ingested twice under a matchId from a different range.
    #
    # This is not cosmetic. Left in, it credits Blackburn three phantom points and
    # a 47th fixture, which lifts them from 22nd to 18th and pushes Charlton from
    # 20th down to 21st -- i.e. the report would misstate both the club's own final
    # position and who went down. Keep the earlier fixture; the later row is the
    # re-ingest.
    r = r.sort_values("kickoff_utc").drop_duplicates(subset=["home_team", "away_team"], keep="first")

    r = r.loc[r["kickoff_utc"] <= as_of]

    rows = []
    for _, m in r.iterrows():
        for side, opp_side in (("home", "away"), ("away", "home")):
            gf, ga = int(m[f"{side}_goals"]), int(m[f"{opp_side}_goals"])
            rows.append(
                {
                    "team": m[f"{side}_team"],
                    "opponent": m[f"{opp_side}_team"],
                    "kickoff": m["kickoff_utc"],
                    "points": 3 if gf > ga else (1 if gf == ga else 0),
                    "result": "W" if gf > ga else ("D" if gf == ga else "L"),
                    "gd": gf - ga,
                    "gf": gf,
                }
            )
    long = pd.DataFrame(rows)

    table = (
        long.groupby("team")
        .agg(played=("points", "size"), points=("points", "sum"), gd=("gd", "sum"), gf=("gf", "sum"))
        .sort_values(["points", "gd", "gf"], ascending=False)
        .reset_index()
    )
    table["position"] = range(1, len(table) + 1)
    me = table.loc[table["team"] == team].iloc[0]

    recent = long.loc[long["team"] == team].sort_values("kickoff").tail(form_matches)
    return SeasonContext(
        position=int(me["position"]),
        played=int(me["played"]),
        points=int(me["points"]),
        goal_difference=int(me["gd"]),
        form=list(recent["result"]),
        form_opponents=list(recent["opponent"]),
    )


# --------------------------------------------------------------------------- #
# Player contribution table (Charlton only)
# --------------------------------------------------------------------------- #
def player_contributions(events: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """The match's top contributors from *both* sides, ranked by expected threat,
    with the counting stats that put that threat in context.

    This is the expected-threat leaderboard and the player-contribution table in
    one panel, because separately they were two answers to the same question and
    a single A4 page does not have room to ask it twice.

    Deliberately carries no "minutes played" column. The feed has no substitution
    event, so while a substitute's *arrival* can be inferred from their first
    touch, there is no way to know when the player they replaced went off — every
    starter's minutes would be a guess. Invented minutes on a board report are
    worse than no minutes at all.

    Ground and aerial duels are shown separately, not as one "duels" total: they
    are different jobs, and a centre-half who wins eight headers and a midfielder
    who wins eight tackles are not interchangeable.

    ``BALL_LOSS_NUMBER`` is deliberately **not** a column here. It correlates 0.86
    with touches on this fixture — it is a volume measure wearing a judgement's
    clothing, and putting it in front of a board would mark down whoever saw most
    of the ball (Coventry tops both lists). Ball *wins* correlate only 0.59 with
    touches, so they carry information of their own and are shown.
    """
    g = (
        events.groupby(["playerName", "squadName"])
        .agg(
            passes=("SUCCESSFUL_PASSES", "sum"),
            ground=("WON_GROUND_DUELS", "sum"),
            aerial=("WON_AERIAL_DUELS", "sum"),
            ball_wins=("BALL_WIN_NUMBER", "sum"),
            shots=("SHOT_AT_GOAL_NUMBER", "sum"),
            xg=("SHOT_XG", "sum"),
            xt=("PXT_ATTACK", "sum"),
        )
        .reset_index()
    )
    g["surname"] = g["playerName"].apply(lambda n: n.split()[-1])
    return g.sort_values("xt", ascending=False).head(top_n).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Shot-map summary line (sits under each shot map)
# --------------------------------------------------------------------------- #
def shot_summary(shots: pd.DataFrame, team: str) -> dict[str, float | int]:
    t = shots.loc[shots["squadName"] == team]
    npx = t.loc[t["action"] != "PENALTY_KICK", "SHOT_XG"]
    n = int(len(t))
    return {
        "shots": n,
        "on_target": int((t["category"].isin(["Goal", "On target"])).sum()),
        "xg": float(npx.sum()),
        "xg_per_shot": float(npx.sum() / n) if n else 0.0,
    }

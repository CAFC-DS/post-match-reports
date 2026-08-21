"""Page 3 (Out of Possession) metrics: pressing structure, pressure activity,
duels (won/lost via the reverse-lookup DATA_MODEL.md documents), second balls,
and what was conceded. No existing report to validate against — every
formula here is this project's own, first-checked-live design; see
DATA_MODEL.md "New panels" for the reasoning behind each cutoff.
"""

from __future__ import annotations

import pandas as pd

from .shared import shot_events

# Named, documented constant -- PPDA has no single agreed zone definition
# across providers; adjusted coordinates run roughly -52.5..52.5, positive x
# always the attacking direction. 35 marks the boundary between a team's own
# defensive two-thirds and its attacking third.
PPDA_ZONE_X = 35

DEFENSIVE_ACTION_TYPES = {"GROUND_DUEL", "AERIAL_DUEL", "INTERCEPTION", "FOUL", "CLEARANCE", "BLOCK"}


def _is_missing(series: pd.Series) -> pd.Series:
    """Object columns use the literal string "nan" as their missing-value
    sentinel, not a true null -- see DATA_MODEL.md. Numeric columns use real
    NaN and don't need this.
    """
    return series.isna() | (series.astype(str) == "nan")


def ppda(events: pd.DataFrame, defending_team: str, attacking_team: str,
         zone_x: float = PPDA_ZONE_X) -> float:
    """Opponent's completed passes in their own defensive two-thirds, divided
    by the defending team's own defensive actions in the opponent's attacking
    two-thirds. Lower = more intense pressing.
    """
    opp = events.loc[events["squadName"] == attacking_team]
    opp_passes_deep = opp.loc[
        (opp["actionType"] == "PASS") & (opp["result"] == "SUCCESS") & (opp["startAdjCoordinatesX"] < zone_x)
    ]
    own = events.loc[events["squadName"] == defending_team]
    own_def_actions_high = own.loc[
        own["actionType"].isin(DEFENSIVE_ACTION_TYPES) & (own["startAdjCoordinatesX"] > -zone_x)
    ]
    denom = len(own_def_actions_high)
    return float(len(opp_passes_deep) / denom) if denom else float("nan")


def defensive_line_height(events: pd.DataFrame, team: str) -> float:
    """Mean startAdjCoordinatesX of the team's own defensive actions --
    distance from their own goal line that defensive activity happens at.
    """
    t = events.loc[(events["squadName"] == team) & events["actionType"].isin(DEFENSIVE_ACTION_TYPES)]
    return float(t["startAdjCoordinatesX"].mean()) if len(t) else float("nan")


def engagement_zone(events: pd.DataFrame, team: str) -> dict:
    """The pitch third where the team's defensive actions most frequently
    occur -- the mode of startPitchPosition over the same action set as PPDA.
    """
    t = events.loc[(events["squadName"] == team) & events["actionType"].isin(DEFENSIVE_ACTION_TYPES)]
    counts = t["startPitchPosition"].value_counts()
    if counts.empty:
        return {"zone": None, "share": 0.0, "counts": counts}
    top = counts.index[0]
    return {"zone": str(top), "share": float(counts.iloc[0] / counts.sum()), "counts": counts}


def pressure_zones(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Rows where ``team`` applied a named press (``pressingPlayerId`` not
    null) -- the discrete "who pressed" signal. Locations are the ball-
    carrier's own event coordinates (where the press was applied), the
    convention the HFC-pack pressure heatmaps use. ``pressure`` (0-100
    intensity on the carrier's action) is carried through as a weight for
    "most intense zone" framing, not as the definition of a press.
    """
    t = events.loc[
        (events["squadName"] != team)  # pressing TEAM applies pressure to the OPPONENT's on-ball action
        & (~_is_missing(events["pressingPlayerName"]))
    ].copy()
    # pressingPlayerName identifies who from the OTHER side applied the press;
    # keep only rows where the presser belongs to `team`.
    t = t.loc[t["pressingPlayerName"].notna()]
    return t[["pressingPlayerId", "pressingPlayerName", "startAdjCoordinatesX", "startAdjCoordinatesY",
              "pressure", "gameTime", "playerName", "squadName"]].rename(
        columns={"playerName": "pressed_player", "squadName": "pressed_team"}
    )


def opp_half_regains_detail(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Located, timestamped opposition-half regains -- extends team_stats'
    scalar count into rows a map/table can use, and a base for pairing with
    transition.regain_sequences for the "regain-to-shot" framing.
    """
    t = events.loc[
        (events["squadName"] == team) & (events["BALL_WIN_NUMBER"] == 1) & (events["startAdjCoordinatesX"] > 0)
    ].copy()
    return t[["eventId", "playerName", "startAdjCoordinatesX", "startAdjCoordinatesY", "gameTime"]]


def duel_performance(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Per-player ground/aerial duel record, won AND lost. Wins come from the
    winner's own row (``WON_GROUND_DUELS``/``WON_AERIAL_DUELS`` == 1). Losses
    are derived by reverse lookup on ``duelPlayerName`` -- the opponent named
    on someone else's winning row -- since ``LOST_GROUND_DUELS``/
    ``LOST_AERIAL_DUELS`` are confirmed 100% null on this feed (see
    DATA_MODEL.md). Verified: every GROUND_DUEL/AERIAL_DUEL-tagged row has its
    matching WON_* flag set, no exceptions.
    """
    duels = events.loc[~_is_missing(events["duelType"])].copy()

    def _record(kind: str, won_col: str) -> pd.DataFrame:
        k = duels.loc[duels["duelType"] == kind]
        wins = (
            k.loc[(k["squadName"] == team) & (k[won_col] == 1)]
            .groupby("playerName").size().rename("won")
        )
        losses = (
            k.loc[(k["squadName"] != team) & (k[won_col] == 1)]
            .groupby("duelPlayerName").size().rename("lost")
        )
        out = pd.concat([wins, losses], axis=1).fillna(0).astype(int)
        out["duel_type"] = kind
        return out.reset_index().rename(columns={"index": "playerName"})

    ground = _record("GROUND_DUEL", "WON_GROUND_DUELS")
    aerial = _record("AERIAL_DUEL", "WON_AERIAL_DUELS")
    combined = pd.concat([ground, aerial], ignore_index=True)
    combined["total"] = combined["won"] + combined["lost"]
    combined["win_pct"] = (combined["won"] / combined["total"] * 100).where(combined["total"] > 0)
    return combined.sort_values(["duel_type", "won"], ascending=[True, False]).reset_index(drop=True)


def second_ball_wins_detail(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Second-ball contests (SECOND_BALL_START) and wins (SECOND_BALL_WIN)
    with locations -- defensive framing: where the team is winning/losing the
    loose-ball fight. Both columns are real numeric flags (1.0 or NaN), not
    subject to the object-column "nan"-string trap.
    """
    t = events.loc[events["squadName"] == team].copy()
    starts = t.loc[t["SECOND_BALL_START"] == 1, ["eventId", "playerName", "startAdjCoordinatesX", "startAdjCoordinatesY", "gameTime"]].assign(won=False)
    wins = t.loc[t["SECOND_BALL_WIN"] == 1, ["eventId", "playerName", "startAdjCoordinatesX", "startAdjCoordinatesY", "gameTime"]].assign(won=True)
    win_ids = set(wins["eventId"])
    starts = starts.loc[~starts["eventId"].isin(win_ids)]
    return pd.concat([starts, wins], ignore_index=True)


def conceded_summary(events: pd.DataFrame, team: str, opponent: str) -> dict:
    """What we conceded: opponent's shot map inputs (via shot_events,
    filtered to opponent), crosses conceded, set-piece concession summary.
    """
    shots = shot_events(events)
    opp_shots = shots.loc[shots["squadName"] == opponent]
    crosses = events.loc[
        (events["squadName"] == opponent)
        & (events["action"].isin(["HIGH_CROSS", "LOW_CROSS"]))
    ]
    set_piece_shots = opp_shots.loc[opp_shots["phase"] == "SET_PIECE"]
    return {
        "shots_faced": int(len(opp_shots)),
        "xg_faced": float(opp_shots.loc[opp_shots["action"] != "PENALTY_KICK", "SHOT_XG"].sum()),
        "crosses_faced": int(len(crosses)),
        "set_piece_shots_faced": int(len(set_piece_shots)),
        "set_piece_xg_faced": float(set_piece_shots["SHOT_XG"].sum()),
        "goals_conceded": int((opp_shots["category"] == "Goal").sum()),
    }

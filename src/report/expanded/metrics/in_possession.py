"""Page 2 (In Possession) metrics: pass matrix, threat maps by zone/lane/
packing-zone, per-player xT by action type, build-up quality, key passes.
``passing_network`` and ``zone_entries`` are vendored unchanged from
``shared.py`` -- imported here for convenience, not redefined.
"""

from __future__ import annotations

import pandas as pd

from .shared import PassingNetwork, passing_network, zone_entries  # noqa: F401  (re-export)

# Empirical decode of Impect's own packing-zone codes -- see DATA_MODEL.md.
# Not a published Impect glossary; cross-validated against
# full-season-analysis's ASSISTS_FROM_PACKING_ZONE_* column vocabulary.
PACKING_ZONE_LABELS: dict[str, str] = {
    "GKC": "Goalkeeper", "CBC": "Centre-back", "CBL": "Centre-back (L)", "CBR": "Centre-back (R)",
    "FBL": "Full-back (L)", "FBR": "Full-back (R)",
    "DML": "Def. mid (L)", "DMC": "Def. mid (C)", "DMR": "Def. mid (R)",
    "CML": "Central mid (L)", "CMC": "Central mid (C)", "CMR": "Central mid (R)",
    "AML": "Att. mid (L)", "AMC": "Att. mid (C)", "AMR": "Att. mid (R)",
    "WL": "Wing (L)", "WR": "Wing (R)",
    "IB": "In the box", "IBWL": "In the box, wide (L)", "IBWR": "In the box, wide (R)",
}


def _zone_label(code: str) -> str:
    base = code[4:] if code.startswith("OPP_") else code
    label = PACKING_ZONE_LABELS.get(base, base)
    return f"Opponent's {label.lower()}" if code.startswith("OPP_") else label


# Median (x, y) occurrence position per packing-zone code, in IMPECT adjusted
# coordinates -- derived empirically from a season of events (see DATA_MODEL.md),
# not a fixed rectangle. A packing zone is a defensive-role zone (the code
# names literally are "CBC" = centre-back-central, "DMC" = def-mid-central,
# etc.), not a fixed patch of grass: a single zone code's events range
# almost the full length of the pitch (e.g. CBC spans x=-52 to x=52), because
# it fires wherever the attacking action passed through that role's nominal
# territory, not at one physical spot. Drawing it as a bounded rectangle would
# misrepresent the data; plotting a badge at its median occurrence point --
# the way a formation diagram places "CB" at a representative spot even
# though the player range far wider than that dot -- is the honest read.
PACKING_ZONE_POSITIONS: dict[str, tuple[float, float]] = {
    "GKC": (-42.2, 0.0), "GKL": (-40.4, 6.7), "GKR": (-39.3, -9.3),
    "CBL": (-17.4, 18.5), "CBR": (-16.5, -17.8), "CBC": (-15.0, 0.0),
    "FBL": (-3.6, 29.4), "DMC": (-1.2, 0.5), "FBR": (0.0, -29.1),
    "DML": (1.0, 18.9), "DMR": (3.9, -19.2),
    "CMC": (4.8, 0.0), "CML": (4.9, 17.5), "CMR": (7.7, -17.8),
    "AMR": (12.2, -16.1), "AML": (12.8, 15.7), "AMC": (13.2, 0.2),
    "WL": (15.9, 28.2), "WR": (17.6, -28.0),
    "IBWL": (37.5, 21.4), "IBWR": (38.3, -19.4), "IBL": (38.9, 4.0),
    "IBC": (39.1, 0.4), "IBR": (40.8, -5.6),
}

# Coarse grouping of the packing-zone taxonomy above, merging the L/C/R split
# into one cell per role-line -- for the zone choropleth map (pitch.zone_choropleth_map),
# which needs cells large enough to read at a glance. The full 23-zone taxonomy
# renders as legitimate zones too (each is still a nearest-anchor partition,
# not a fabricated boundary) but produces slivers through central midfield
# that are no easier to read than the badges they replace; this 12-cell
# version is the one that actually matches the Hibernian reference pack's
# "xT By Packing Zone" panel's legibility. Threat by Lane already carries the
# separate L/C/R-by-wing read, so nothing is lost by merging it out here.
PACKING_ZONE_GROUPS: dict[str, str] = {
    "GKC": "GK", "GKL": "GK", "GKR": "GK",
    "CBL": "CB", "CBR": "CB", "CBC": "CB",
    "FBL": "FBL", "FBR": "FBR",
    "DML": "DM", "DMC": "DM", "DMR": "DM",
    "CML": "CM", "CMC": "CM", "CMR": "CM",
    "AML": "AM", "AMR": "AM", "AMC": "AM",
    "WL": "WL", "WR": "WR",
    "IBWL": "IBWL", "IBWR": "IBWR", "IBL": "IB", "IBC": "IB", "IBR": "IB",
}
PACKING_ZONE_GROUP_LABELS: dict[str, str] = {
    "GK": "Goalkeeper", "CB": "Centre-back", "FBL": "Full-back (L)", "FBR": "Full-back (R)",
    "DM": "Def. mid", "CM": "Central mid", "AM": "Att. mid",
    "WL": "Wing (L)", "WR": "Wing (R)", "IB": "In the box",
    "IBWL": "In the box, wide (L)", "IBWR": "In the box, wide (R)",
}
# Median anchor position per group -- the mean of the merged codes' own
# PACKING_ZONE_POSITIONS anchors above (GK collapses its three sub-anchors
# to one central point; CB/DM/CM/AM likewise), not re-derived from raw events.
PACKING_ZONE_GROUP_POSITIONS: dict[str, tuple[float, float]] = {
    "GK": (-40.6, 0.0), "CB": (-16.3, 0.0), "FBL": (-3.6, 29.4), "FBR": (0.0, -29.1),
    "DM": (1.2, 0.0), "CM": (5.8, 0.0), "AM": (12.7, 0.0),
    "WL": (15.9, 28.2), "WR": (17.6, -28.0),
    "IB": (39.6, 0.0), "IBWL": (37.5, 21.4), "IBWR": (38.3, -19.4),
}


def group_zone_totals(zone_df: pd.DataFrame, code_col: str = "startPackingZone") -> pd.DataFrame:
    """Collapse a fine packing-zone breakdown (xt_by_zone / xt_by_packing_zone)
    onto PACKING_ZONE_GROUPS for the choropleth map -- sums pxT per coarse
    group, dropping the handful of ungrouped codes (e.g. a stray ``None``
    zone) rather than guessing where they belong.
    """
    if zone_df.empty:
        return zone_df.assign(group=[])
    d = zone_df.copy()
    d["group"] = d[code_col].map(PACKING_ZONE_GROUPS)
    d = d.loc[d["group"].notna()]
    g = d.groupby("group", as_index=False)["xt"].sum()
    g["label"] = g["group"].map(PACKING_ZONE_GROUP_LABELS)
    return g


# Lane bands are genuinely spatial (fixed Y ranges, independent of X) --
# confirmed empirically, unlike packing zones above. Attacking goal at +52.5.
LANE_BANDS: dict[str, tuple[float, float]] = {
    "RIGHT_WING": (-34.0, -20.2),
    "RIGHT_HALF_SPACE": (-20.2, -9.2),
    "CENTER": (-9.2, 9.2),
    "LEFT_HALF_SPACE": (9.2, 20.2),
    "LEFT_WING": (20.2, 34.0),
}
LANE_LABELS: dict[str, str] = {
    "CENTER": "C", "LEFT_HALF_SPACE": "LHS", "RIGHT_HALF_SPACE": "RHS",
    "LEFT_WING": "LW", "RIGHT_WING": "RW",
}


def average_touch_positions(events: pd.DataFrame, team: str, starters: list[str],
                             min_touches: int = 3) -> pd.DataFrame:
    """Each player's average position across every on-ball action this match
    -- deliberately different from the passing network's nodes, which are
    each player's average position when *starting a successful pass* only.
    Shown alongside the network so the two can't be mistaken for the same
    thing: this one answers "where did they generally operate," the network
    answers "where did they play the ball from."
    """
    t = events.loc[(events["squadName"] == team) & events["playerName"].notna() & (events["playerName"] != "nan")]
    g = (
        t.groupby("playerName")
        .agg(x=("startAdjCoordinatesX", "mean"), y=("startAdjCoordinatesY", "mean"), touches=("playerName", "size"))
        .reset_index()
    )
    g = g.loc[g["touches"] >= min_touches].copy()
    g["surname"] = g["playerName"].apply(lambda n: n.split()[-1])
    g["is_starter"] = g["playerName"].isin(starters)
    return g.sort_values("touches", ascending=False).reset_index(drop=True)



def xt_by_zone(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """PXT_REC (threat gained on reception) summed by IMPECT's own packing
    zone -- receptions and threat between the lines, using Impect's grid, not
    an invented one.
    """
    t = events.loc[(events["squadName"] == team) & (events["actionType"] == "RECEPTION")].copy()
    g = t.groupby("startPackingZone").agg(receptions=("eventId", "size"), xt=("PXT_REC", "sum")).reset_index()
    g = g.loc[g["startPackingZone"] != "nan"]
    g["label"] = g["startPackingZone"].apply(_zone_label)
    return g.sort_values("xt", ascending=False)


def xt_by_lane(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """PXT_ATTACK by lane (centre / half-spaces / wings) of the action's
    start location -- the classic "which channel did the threat come down."
    """
    t = events.loc[events["squadName"] == team].copy()
    t = t.loc[(t["startLane"].notna()) & (t["startLane"] != "nan")]
    g = t.groupby("startLane").agg(actions=("eventId", "size"), xt=("PXT_ATTACK", "sum")).reset_index()
    g["label"] = g["startLane"].map(LANE_LABELS)
    return g


def xt_by_packing_zone(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """PXT_ATTACK by packing zone of the action's start location -- the
    line-by-line breakdown (defensive mid, central mid, attacking mid, wing,
    etc.) rather than the coarser lane view above.
    """
    t = events.loc[events["squadName"] == team].copy()
    t = t.loc[(t["startPackingZone"].notna()) & (t["startPackingZone"] != "nan")]
    g = t.groupby("startPackingZone").agg(actions=("eventId", "size"), xt=("PXT_ATTACK", "sum")).reset_index()
    g["label"] = g["startPackingZone"].apply(_zone_label)
    return g.sort_values("xt", ascending=False)


def player_xt_by_action_type(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Per-player xT, broken down by HOW it was created: passing (PXT_PASS,
    the passer's own credit), carrying/dribbling (PXT_DRIBBLE), receiving
    (PXT_REC). Extends the vendored ``player_contributions`` (which uses the
    summed PXT_ATTACK) into the "how" breakdown the brief specifically asks
    for.
    """
    t = events.loc[events["squadName"] == team].copy()
    g = t.groupby("playerName").agg(
        passing_xt=("PXT_PASS", "sum"),
        carrying_xt=("PXT_DRIBBLE", "sum"),
        receiving_xt=("PXT_REC", "sum"),
    ).reset_index()
    g["total_xt"] = g["passing_xt"] + g["carrying_xt"] + g["receiving_xt"]
    g["surname"] = g["playerName"].apply(lambda n: n.split()[-1])
    return g.sort_values("total_xt", ascending=False).reset_index(drop=True)


def buildup_quality(events: pd.DataFrame, home: str, away: str) -> pd.DataFrame:
    """Progressive passes/carries, passes into the final third, and field
    tilt (share of final-third touches), both teams side by side.
    """
    rows = []
    for team in (home, away):
        t = events.loc[events["squadName"] == team]
        prog_pass = (
            (t["actionType"] == "PASS") & (t["result"] == "SUCCESS")
            & (t["endAdjCoordinatesX"] - t["startAdjCoordinatesX"] >= 10)
        ).sum()
        prog_carry = (
            (t["actionType"] == "DRIBBLE") & (t["result"] == "SUCCESS")
            & (t["endAdjCoordinatesX"] - t["startAdjCoordinatesX"] >= 5)
        ).sum()
        into_final_third = (
            (t["actionType"] == "PASS") & (t["result"] == "SUCCESS")
            & (t["endPitchPosition"].isin(["FINAL_THIRD", "OPPONENT_BOX"]))
            & (~t["startPitchPosition"].isin(["FINAL_THIRD", "OPPONENT_BOX"]))
        ).sum()
        final_third_touches = (t["startPitchPosition"] == "FINAL_THIRD").sum() + (t["startPitchPosition"] == "OPPONENT_BOX").sum()
        rows.append({"team": team, "progressive_passes": int(prog_pass), "progressive_carries": int(prog_carry),
                      "passes_into_final_third": int(into_final_third), "final_third_touches": int(final_third_touches)})
    df = pd.DataFrame(rows).set_index("team")
    total_ft = df["final_third_touches"].sum()
    df["field_tilt_pct"] = (df["final_third_touches"] / total_ft * 100) if total_ft else 50.0
    return df


def key_passes(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Key passes (SHOT_ASSISTS) and pre-key passes (PRE_ASSISTS). Both are
    string-typed '1'/NaN flags on this warehouse -- cast with
    pd.to_numeric before filtering, per DATA_MODEL.md.
    """
    t = events.loc[events["squadName"] == team].copy()
    t["shot_assist"] = pd.to_numeric(t["SHOT_ASSISTS"], errors="coerce").fillna(0)
    t["pre_assist"] = pd.to_numeric(t["PRE_ASSISTS"], errors="coerce").fillna(0)
    t["xa"] = pd.to_numeric(t["EXPECTED_SHOT_ASSISTS"], errors="coerce").fillna(0)
    key = t.loc[t["shot_assist"] == 1]
    pre = t.loc[t["pre_assist"] == 1]
    return pd.concat([
        key[["playerName", "startAdjCoordinatesX", "startAdjCoordinatesY", "endAdjCoordinatesX",
             "endAdjCoordinatesY", "xa", "gameTime"]].assign(kind="key_pass"),
        pre[["playerName", "startAdjCoordinatesX", "startAdjCoordinatesY", "endAdjCoordinatesX",
             "endAdjCoordinatesY", "xa", "gameTime"]].assign(kind="pre_key_pass"),
    ], ignore_index=True)


def apex_actions(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Actions inside the opponent box -- passes, crosses and shots that
    reached the most advanced ("apex") point of a possession, in the pack's
    style. Uses OFFENSIVE_TOUCHES location + actionType inside OPPONENT_BOX.
    """
    t = events.loc[
        (events["squadName"] == team)
        & (events["startPitchPosition"] == "OPPONENT_BOX")
        & (events["actionType"].isin(["PASS", "SHOT", "DRIBBLE"]))
    ].copy()
    return t[["playerName", "actionType", "action", "result", "startAdjCoordinatesX",
              "startAdjCoordinatesY", "endAdjCoordinatesX", "endAdjCoordinatesY", "PXT_ATTACK"]]

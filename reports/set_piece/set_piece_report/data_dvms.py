"""DVMS (Opta + tracking) data layer for the set-piece report.

Maps the vendored ``src.dvms`` set-piece derivations onto the exact frame
contracts the existing ``pitch.py`` graphics consume (IMPECT-era adjusted
coordinates, this report's corner/FK/throw taxonomies), so every map on the
page is drawn by the same functions as the IMPECT version. The derivation
caveats live in ``src/dvms/metrics/opta_setpiece_map.py`` docstrings and are
quoted in the report footnote.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.dvms.loaders import assets
from src.dvms.loaders.fixtures import FixtureRef
from src.dvms.metrics import opta_setpiece_map as spm
from src.dvms.metrics.xg_lite import add_xg
from src.dvms.parsers.f24 import F24Match, parse_f24
from src.dvms.parsers.f7 import F7Match, parse_f7
from src.dvms.parsers.ss_meta import PitchMeta, parse_ss_metadata
from src.dvms.preprocess import load_artifact

# opta_setpiece_map zone -> this report's corner taxonomy (config.py).
_CORNER_TYPE = {"near_post": "NEAR_POST", "central": "CENTRAL",
                "far_post": "FAR_POST", "short": "SHORT"}
# fk_type -> this report's fk_group taxonomy (pitch.free_kick_overview).
_FK_GROUP = {"into_box_cross": "CROSS", "into_box": "HIGH_BALL",
             "short": "INTO_POSSESSION", "direct": "SHOT"}


@dataclass
class DvmsSetPieceContext:
    fixture: FixtureRef
    f24: F24Match
    f7: F7Match
    meta: PitchMeta
    frames: pd.DataFrame          # tracking long df (for freeze-frames)
    events: pd.DataFrame          # play periods, with xg
    corners: pd.DataFrame         # all deliveries, both teams, first-contact joined
    fks: pd.DataFrame
    throws: pd.DataFrame

    @property
    def home_team(self) -> str:
        return self.f24.home_team_name

    @property
    def away_team(self) -> str:
        return self.f24.away_team_name

    def team_id(self, team: str) -> str:
        return (self.f24.home_team_id if team == self.home_team
                else self.f24.away_team_id)

    def last_name(self, player_id) -> str:
        lu = self.f7.lineups
        hit = lu[lu["player_id"] == str(player_id)]
        if not hit.empty and pd.notna(hit.iloc[0]["last_name"]):
            return str(hit.iloc[0]["last_name"])
        return str(self.f7.player_name(str(player_id)) or player_id)


def load_context(fixture: FixtureRef, env_path: str = ".env") -> DvmsSetPieceContext:
    f24 = parse_f24(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 20, env_path=env_path))
    f7 = parse_f7(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 21, env_path=env_path))
    meta = parse_ss_metadata(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 40, env_path=env_path))
    frames = load_artifact(fixture.opta_match_id, "frames_5hz.parquet")

    events = f24.events[f24.events["period_id"].isin([1, 2, 3, 4])].copy()
    events["xg"] = add_xg(events, meta.pitch_length, meta.pitch_width)

    corners = spm.first_contact(events, spm.corners(events))
    corners["led_to_goal"] = spm.led_to_goal(events, corners)
    fks = spm.first_contact(events, spm.free_kicks(events))
    fks["led_to_goal"] = spm.led_to_goal(events, fks)
    throws = spm.first_contact(events, spm.throw_ins(events))
    throws["led_to_goal"] = spm.led_to_goal(events, throws)

    return DvmsSetPieceContext(fixture=fixture, f24=f24, f7=f7, meta=meta,
                               frames=frames, events=events,
                               corners=corners, fks=fks, throws=throws)


def _adj(x, y):
    return (np.asarray(x, dtype=float) - 50.0) * 1.05, \
           (np.asarray(y, dtype=float) - 50.0) * 0.68


def _contact_label(won) -> str:
    if won is True:
        return "won"
    if won is False:
        return "lost"
    return "none"


def _pitch_frame(d: pd.DataFrame, extra: dict) -> pd.DataFrame:
    sx, sy = _adj(d["x"], d["y"])
    ex, ey = _adj(d["end_x"], d["end_y"])
    out = pd.DataFrame({
        "startAdjCoordinatesX": sx, "startAdjCoordinatesY": sy,
        "endAdjCoordinatesX": ex, "endAdjCoordinatesY": ey,
        "first_touch": [_contact_label(w) for w in d["won"]],
        "led_to_goal": d["led_to_goal"].to_numpy(),
    })
    for col, values in extra.items():
        out[col] = values
    return out


def corner_deliveries(ctx: DvmsSetPieceContext, team: str) -> pd.DataFrame:
    d = ctx.corners[ctx.corners["team_id"] == ctx.team_id(team)]
    if d.empty:
        return pd.DataFrame()
    return _pitch_frame(d, {"corner_type": d["corner_type"].map(_CORNER_TYPE).to_numpy()})


def fk_deliveries(ctx: DvmsSetPieceContext, team: str) -> pd.DataFrame:
    d = ctx.fks[ctx.fks["team_id"] == ctx.team_id(team)]
    if d.empty:
        return pd.DataFrame()
    return _pitch_frame(d, {"fk_group": d["fk_type"].map(_FK_GROUP).to_numpy()})


def throw_in_deliveries(ctx: DvmsSetPieceContext, team: str) -> pd.DataFrame:
    d = ctx.throws[ctx.throws["team_id"] == ctx.team_id(team)]
    if d.empty:
        return pd.DataFrame()
    return _pitch_frame(d, {"throw_group": d["throw_group"]})


# --------------------------------------------------------------------------- #
# Central stat table
# --------------------------------------------------------------------------- #
def _shots_in_window(ctx: DvmsSetPieceContext, deliveries: pd.DataFrame,
                     within_seconds: float = 10.0) -> tuple[int, float]:
    """(shots, xG) by the delivering team within the window of any delivery."""
    shots = ctx.events[ctx.events["is_shot"]]
    n, xg = 0, 0.0
    counted: set = set()
    for _, d in deliveries.iterrows():
        t0 = d["minute"] * 60 + d["second"]
        hits = shots[(shots["period_id"] == d["period_id"])
                     & (shots["team_id"] == d["team_id"])
                     & ((shots["minute"] * 60 + shots["second"]).between(t0, t0 + within_seconds))]
        for eid, sxg in zip(hits["event_id"], hits["xg"]):
            if eid not in counted:
                counted.add(eid)
                n += 1
                xg += float(sxg) if sxg == sxg else 0.0
    return n, xg


def stat_sections(ctx: DvmsSetPieceContext) -> list[dict]:
    """The centre table: per-section rows of match values for both teams."""
    def per_team(frame_all: pd.DataFrame, direct: bool | None = None):
        out = {}
        for team in (ctx.home_team, ctx.away_team):
            d = frame_all[frame_all["team_id"] == ctx.team_id(team)]
            if direct is True:
                d = d[d.get("fk_type", pd.Series(dtype=str)) == "direct"]
            elif direct is False and "fk_type" in d:
                d = d[d["fk_type"] != "direct"]
            shots, xg = _shots_in_window(ctx, d)
            out[team] = {"n": len(d), "shots": shots,
                         "goals": int(d["led_to_goal"].sum()), "xg": xg}
        return out

    sections = []
    for label, data in (("CORNERS", per_team(ctx.corners)),
                        ("THROW-INS", per_team(ctx.throws)),
                        ("INDIRECT FREE-KICKS", per_team(ctx.fks, direct=False))):
        sections.append({"section": label, "rows": [
            {"label": f"Total {label.title().replace('-', ' ')}", "key": "n"},
            {"label": "Shots Created (within 10s)", "key": "shots"},
            {"label": "Goals", "key": "goals"},
            {"label": "xG (CAFC-lite)", "key": "xg"},
        ], "data": data})
    return sections


def first_contact_rows(ctx: DvmsSetPieceContext, team: str) -> list[dict]:
    """Corners/FKs × attacking/defending first-contact summary for one side."""
    tid = ctx.team_id(team)

    def cell(frame: pd.DataFrame, attacking: bool) -> dict:
        d = frame[frame["team_id"] == tid] if attacking else frame[frame["team_id"] != tid]
        contested = d[d["won"].notna()]
        # 'Won' is always from this team's perspective: the delivering team
        # won the contact when won=True; the defending team when won=False.
        won = int(contested["won"].sum()) if attacking else int((~contested["won"].astype(bool)).sum())
        lost = len(contested) - won
        rate = f"{won / len(contested) * 100:.0f}%" if len(contested) else "—"
        return {"n": len(d), "won": won, "lost": lost, "win_rate": rate}

    return [
        {"label": "Corners · att", "c": cell(ctx.corners, True)},
        {"label": "Corners · def", "c": cell(ctx.corners, False)},
        {"label": "Free-kicks · att", "c": cell(ctx.fks, True)},
        {"label": "Free-kicks · def", "c": cell(ctx.fks, False)},
    ]


# --------------------------------------------------------------------------- #
# Freeze-frames (the tracking-data differentiator)
# --------------------------------------------------------------------------- #
def best_corner(ctx: DvmsSetPieceContext, team: str) -> pd.Series | None:
    """The corner to freeze-frame: a goal if there was one, else the delivery
    whose 10s window carried the most xG, else the first corner."""
    d = ctx.corners[(ctx.corners["team_id"] == ctx.team_id(team))
                    & (ctx.corners["corner_type"] != "short")]
    if d.empty:
        d = ctx.corners[ctx.corners["team_id"] == ctx.team_id(team)]
    if d.empty:
        return None
    goals = d[d["led_to_goal"]]
    if not goals.empty:
        return goals.iloc[0]
    best, best_xg = None, -1.0
    for _, row in d.iterrows():
        _, xg = _shots_in_window(ctx, pd.DataFrame([row]))
        if xg > best_xg:
            best, best_xg = row, xg
    return best if best is not None else d.iloc[0]


def freeze_frame_data(ctx: DvmsSetPieceContext, team: str):
    """(frame df, delivery row, defending line-drop metres) for the chosen corner."""
    from src.dvms.metrics.set_piece_frames import (
        corner_line_drop,
        delivery_freeze_frame,
    )

    delivery = best_corner(ctx, team)
    if delivery is None:
        return None, None, None
    frame = delivery_freeze_frame(delivery, ctx.events, ctx.frames, ctx.meta)
    defending = ctx.away_team if team == ctx.home_team else ctx.home_team
    drop = corner_line_drop(
        delivery, ctx.events, ctx.frames, ctx.meta, ctx.f7.lineups,
        defending_team_id=ctx.team_id(defending),
        defending_is_home=(defending == ctx.home_team),
    )
    return frame, delivery, drop

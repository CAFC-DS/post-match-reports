"""Board-report metrics from the DVMS feeds (Opta F24/F7 + Second Spectrum).

The DVMS twin of ``metrics.py``/``metrics_v2.py``: the same single-page
panels, re-derived from Opta event data where the IMPECT version used IMPECT
columns, and *upgraded* to tracking truth where event data was only ever a
proxy:

* possession is the tracked share of live frames (``lastTouch``), not a
  pass-count ratio;
* average positions cover all 11 players per phase from tracking — including
  the out-of-possession map that had to be cut from the IMPECT report because
  event data only sees players who touch the ball;
* the defensive line height is a real median height in metres;
* xG is the deterministic CAFC-lite model (F24 carries no xG), labelled as
  such everywhere it appears.

Chart/pitch functions are reused from the existing modules by adapting
DataFrames to the IMPECT-era column contract (``startAdjCoordinatesX`` on the
105×68 centred frame etc.) rather than forking the drawing code.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.dvms.loaders import assets
from src.dvms.loaders.fixtures import FixtureRef
from src.dvms.metrics.xg_lite import XG_MODEL_LABEL, add_xg
from src.dvms.parsers.f24 import F24Match, parse_f24
from src.dvms.parsers.f7 import F7Match, parse_f7
from src.dvms.parsers.ss_meta import PitchMeta, parse_ss_metadata
from src.dvms.parsers.ss_physical import parse_physical_summary
from src.dvms.preprocess import load_artifact

CHARLTON = "Charlton Athletic"

# Opta fixed-frame geometry (0-100 units).
_BOX_X, _BOX_Y_LO, _BOX_Y_HI = 83.0, 21.1, 78.9
_FINAL_THIRD_X = 100 * 2 / 3

# Event types that are a touch of the ball (for box-touch counts).
_TOUCH_TYPES = frozenset({1, 2, 3, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 42,
                          44, 49, 50, 54, 61, 74})

_Q_THROW_IN = 107
_Q_BIG_CHANCE = 214
_Q_BLOCKED = 82
_Q_CORNER_SHOT = 25
_Q_FK_SHOT = 26
_Q_SET_PIECE_SHOT = 24
_Q_COUNTER_SHOT = 23


@dataclass
class DvmsMatch:
    """Everything the DVMS board report needs for one fixture."""

    fixture: FixtureRef
    f24: F24Match
    f7: F7Match
    meta: PitchMeta
    physical: pd.DataFrame
    frames: pd.DataFrame
    phases: dict          # side -> phases df
    shape: dict           # side -> shape df
    avg_positions: dict   # side -> avg positions df
    events: pd.DataFrame  # play-period events with xg column added
    issues: tuple[str, ...] = ()

    @property
    def charlton_is_home(self) -> bool:
        return self.f7.home.name == CHARLTON

    def side_of(self, team_id: str) -> str:
        return "home" if str(team_id) == self.f24.home_team_id else "away"

    def team_id_of(self, side: str) -> str:
        return self.f24.home_team_id if side == "home" else self.f24.away_team_id

    def team_name_of(self, side: str) -> str:
        return self.f24.home_team_name if side == "home" else self.f24.away_team_name

    def last_name(self, player_id) -> str:
        lu = self.f7.lineups
        hit = lu[lu["player_id"] == str(player_id)]
        if not hit.empty and pd.notna(hit.iloc[0]["last_name"]):
            return str(hit.iloc[0]["last_name"])
        return str(self.f7.player_name(str(player_id)) or player_id)


def load_match(fixture: FixtureRef, env_path: str = ".env") -> DvmsMatch:
    f24 = parse_f24(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 20, env_path=env_path))
    f7 = parse_f7(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 21, env_path=env_path))
    meta = parse_ss_metadata(assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 40, env_path=env_path))
    issues: list[str] = []
    try:
        physical = parse_physical_summary(
            assets.fetch_asset_text(fixture.fixture_id, fixture.opta_match_id, 43, env_path=env_path))
    except Exception as exc:  # optional enrichment; report remains useful
        physical = pd.DataFrame()
        issues.append(f"physical: {exc}")

    def optional_artifact(name: str) -> pd.DataFrame:
        try:
            return load_artifact(fixture.opta_match_id, name)
        except Exception as exc:  # panel orchestration decides the fallback
            issues.append(f"{name}: {exc}")
            return pd.DataFrame()

    frames = optional_artifact("frames_5hz.parquet")
    phases = {s: optional_artifact(f"phases_{s}.parquet") for s in ("home", "away")}
    shape = {s: optional_artifact(f"shape_{s}.parquet") for s in ("home", "away")}
    avg = {s: optional_artifact(f"avg_positions_{s}.parquet") for s in ("home", "away")}

    events = f24.events[f24.events["period_id"].isin([1, 2, 3, 4])].copy()
    events["xg"] = add_xg(events, meta.pitch_length, meta.pitch_width)

    return DvmsMatch(fixture=fixture, f24=f24, f7=f7, meta=meta,
                     physical=physical, frames=frames, phases=phases,
                     shape=shape, avg_positions=avg, events=events,
                     issues=tuple(issues))


# --------------------------------------------------------------------------- #
# Coordinate adapters: Opta 0-100 / tracking metres -> the IMPECT-era 105×68
# centred frame the existing pitch.py drawing functions expect.
# --------------------------------------------------------------------------- #
def _opta_to_adj(x, y):
    return (np.asarray(x, dtype=float) - 50.0) * 1.05, \
           (np.asarray(y, dtype=float) - 50.0) * 0.68


def _metres_to_adj(x_m, y_m, meta: PitchMeta):
    sx = 52.5 / (meta.pitch_length / 2.0)
    sy = 34.0 / (meta.pitch_width / 2.0)
    return np.asarray(x_m, dtype=float) * sx, np.asarray(y_m, dtype=float) * sy


# --------------------------------------------------------------------------- #
# Possession & team stats
# --------------------------------------------------------------------------- #
def tracked_possession(match: DvmsMatch) -> dict:
    """Share of live frames per side, from ``lastTouch``."""
    ball = match.frames[(match.frames["team"] == "ball")
                        & (match.frames["live"] == True)]  # noqa: E712
    n = len(ball)
    home = float((ball["last_touch"] == "home").sum()) / n * 100 if n else 50.0
    return {"home": home, "away": 100.0 - home}


def _team_events(match: DvmsMatch, side: str) -> pd.DataFrame:
    return match.events[match.events["team_id"] == match.team_id_of(side)]


def _quals_flag(df: pd.DataFrame, qid: int) -> pd.Series:
    return df["qualifiers"].map(lambda q: qid in q)


def team_stat_values(match: DvmsMatch, side: str) -> dict:
    ev = _team_events(match, side)
    passes = ev[ev["is_pass"] & ~_quals_flag(ev, _Q_THROW_IN)]
    completed = passes[passes["outcome"] == 1]
    shots = ev[ev["is_shot"]]
    on_target = shots[(shots["type_id"].isin([15, 16])) & ~_quals_flag(shots, _Q_BLOCKED)]

    in_box = (ev["x"] >= _BOX_X) & ev["y"].between(_BOX_Y_LO, _BOX_Y_HI)
    shape_by_phase = _shape_by_phase(match, side)

    return {
        "possession_pct": tracked_possession(match)[side],
        "pass_accuracy_pct": len(completed) / len(passes) * 100 if len(passes) else 0.0,
        "successful_passes": len(completed),
        "forward_pass_pct": float((completed["end_x"] > completed["x"]).mean() * 100) if len(completed) else 0.0,
        "shots": len(shots),
        "shots_on_target": len(on_target),
        "xg": float(shots["xg"].sum()),
        "big_chances": int(_quals_flag(shots, _Q_BIG_CHANCE).sum()),
        "touches_in_box": int((in_box & ev["type_id"].isin(_TOUCH_TYPES)).sum()),
        "recoveries_opp_half": int(((ev["type_id"] == 49) & (ev["x"] > 50)).sum()),
        "aerials_won": int(((ev["type_id"] == 44) & (ev["outcome"] == 1)).sum()),
        "tackles_won": int(((ev["type_id"] == 7) & (ev["outcome"] == 1)).sum()),
        "def_line_oop_m": shape_by_phase.get("out_of_possession", {}).get("def_line_m", np.nan),
        "block_depth_oop_m": shape_by_phase.get("out_of_possession", {}).get("depth_m", np.nan),
    }


def _shape_by_phase(match: DvmsMatch, side: str) -> dict:
    from src.dvms.metrics.lines import summarize_by_phase
    summary = summarize_by_phase(match.shape[side], match.phases[side])
    return {r["phase"]: r for _, r in summary.iterrows()}


STAT_ROWS_DVMS = [
    ("On the ball", "possession_pct", "Possession (tracked)"),
    ("On the ball", "pass_accuracy_pct", "Pass accuracy"),
    ("On the ball", "successful_passes", "Successful passes"),
    ("On the ball", "forward_pass_pct", "Passes forward"),
    ("Attack", "shots", "Shots"),
    ("Attack", "shots_on_target", "Shots on target"),
    ("Attack", "xg", "Expected goals"),
    ("Attack", "big_chances", "Big chances"),
    ("Attack", "touches_in_box", "Touches in opposition box"),
    ("Duels & pressing", "recoveries_opp_half", "Ball wins in opposition half"),
    ("Duels & pressing", "aerials_won", "Aerial duels won"),
    ("Duels & pressing", "tackles_won", "Tackles won"),
    ("Shape (tracked)", "def_line_oop_m", "Defensive line height"),
    ("Shape (tracked)", "block_depth_oop_m", "Block depth"),
]

STAT_GLOSS_DVMS = {
    "possession_pct": "share of in-play time the ball was theirs, from tracking.",
    "xg": f"chance quality ({XG_MODEL_LABEL}: distance, angle, header, big chance).",
    "def_line_oop_m": "median height of the back line out of possession, metres from own goal.",
    "block_depth_oop_m": "deepest to highest outfielder out of possession, metres.",
}

_METRE_KEYS = {"def_line_oop_m", "block_depth_oop_m"}


def fmt_stat(key: str, value: float) -> str:
    if key.endswith("_pct"):
        return f"{value:.0f}%"
    if key in _METRE_KEYS:
        return f"{value:.0f}m"
    if key == "xg":
        return f"{value:.2f}"
    return f"{int(round(value))}"


# --------------------------------------------------------------------------- #
# Shots
# --------------------------------------------------------------------------- #
def _shot_category(row: pd.Series) -> str:
    if row["type_id"] == 16:
        return "Goal"
    if row["type_id"] == 14:
        return "Off target"          # woodwork folded into off target
    if row["type_id"] == 13:
        return "Off target"
    if _Q_BLOCKED in row["qualifiers"]:
        return "Blocked"
    return "On target"


def shot_events_dvms(match: DvmsMatch) -> pd.DataFrame:
    """Shots adapted to the pitch.shot_map contract (IMPECT column names)."""
    shots = match.events[match.events["is_shot"]].copy()
    ax, ay = _opta_to_adj(shots["x"], shots["y"])
    shots["startAdjCoordinatesX"] = ax
    shots["startAdjCoordinatesY"] = ay
    shots["SHOT_XG"] = shots["xg"]
    shots["category"] = shots.apply(_shot_category, axis=1)
    shots["playerName"] = shots["player_id"].map(match.last_name)
    shots["squadName"] = shots["team_id"].map(
        {match.f24.home_team_id: match.f24.home_team_name,
         match.f24.away_team_id: match.f24.away_team_name})
    return shots


def shot_summary_dvms(shots: pd.DataFrame, team_name: str) -> dict:
    t = shots[shots["squadName"] == team_name]
    return {
        "shots": len(t),
        "on_target": int((t["category"].isin(["Goal", "On target"])).sum()),
        "xg": float(t["SHOT_XG"].sum()),
    }


# --------------------------------------------------------------------------- #
# Territory (tracked) & chance sources
# --------------------------------------------------------------------------- #
def territory_wave(match: DvmsMatch, window_minutes: float = 3.0) -> pd.DataFrame:
    """Rolling mean tracked ball position, Charlton attacking positive.

    Pure tracking: for every live frame, the ball's x in Charlton's
    attacking-positive frame, averaged over a rolling window. +20m means the
    ball lived 20m inside the opposition half — field tilt, measured
    literally. Returns ``minute`` (cumulative match minutes) and
    ``territory_m``.
    """
    side = "home" if match.charlton_is_home else "away"
    ball = match.frames[(match.frames["team"] == "ball")
                        & (match.frames["live"] == True)].copy()  # noqa: E712
    x = ball["x"].astype(float).to_numpy().copy()
    for p in ball["period"].unique():
        hap = match.meta.home_att_positive(int(p))
        if hap is None:
            continue
        attacks_positive = hap if side == "home" else not hap
        if not attacks_positive:
            mask = (ball["period"] == p).to_numpy()
            x[mask] = -x[mask]
    ball["x_att"] = x
    ball["minute"] = ball["game_clock"] / 60.0 + np.where(ball["period"] == 2, 45.0, 0.0)
    ball = ball.sort_values("minute")

    # Time-based rolling needs a datetime-like index; minutes-as-timedelta
    # keeps the window in real match time across the in-play gaps.
    series = ball.set_index(pd.to_timedelta(ball["minute"], unit="m"))["x_att"]
    rolled = series.rolling(window=pd.Timedelta(minutes=window_minutes),
                            min_periods=10).mean()
    wave = pd.DataFrame({
        "minute": ball["minute"].to_numpy(),
        "territory_m": rolled.to_numpy(),
    })
    return wave.dropna()


def goal_markers(match: DvmsMatch) -> list[dict]:
    out = []
    for g in match.f7.goals:
        team_name = (match.f24.home_team_name
                     if str(g.team_id) == match.f24.home_team_id
                     else match.f24.away_team_name)
        out.append({
            "minute": g.minute + (g.second or 0) / 60.0,
            "team": team_name,
            "label": f"{match.last_name(g.scorer_id)} {g.minute}'" if g.scorer_id else f"{g.minute}'",
        })
    return out


def chance_sources_dvms(match: DvmsMatch) -> pd.DataFrame:
    """xG by shot context, from Opta's own shot-context qualifiers."""
    labels = [("Set piece", lambda q: _Q_SET_PIECE_SHOT in q or _Q_FK_SHOT in q),
              ("Corner", lambda q: _Q_CORNER_SHOT in q),
              ("Counter", lambda q: _Q_COUNTER_SHOT in q),
              ("Open play", lambda q: not any(k in q for k in
               (_Q_SET_PIECE_SHOT, _Q_FK_SHOT, _Q_CORNER_SHOT, _Q_COUNTER_SHOT)))]
    shots = match.events[match.events["is_shot"]]
    out = pd.DataFrame(index=[lbl for lbl, _ in labels])
    for side in ("home", "away"):
        t = shots[shots["team_id"] == match.team_id_of(side)]
        out[match.team_name_of(side)] = [
            float(t.loc[t["qualifiers"].map(fn), "xg"].sum()) for _, fn in labels
        ]
    return out


# --------------------------------------------------------------------------- #
# Average positions (tracked) + line heights
# --------------------------------------------------------------------------- #
def avg_position_frame(match: DvmsMatch, side: str, phase: str) -> pd.DataFrame:
    """Starters' average tracked positions for one phase, in the 105×68 frame
    expected by ``pitch.average_position_map``."""
    lineups = match.f7.lineups
    team_id = match.team_id_of(side)
    starters = set(lineups[(lineups["team_id"] == team_id)
                           & (lineups["status"] == "Start")]["player_id"])
    avg = match.avg_positions[side]
    sub = avg[(avg["phase"] == phase) & avg["opta_id"].isin(starters)].copy()
    ax, ay = _metres_to_adj(sub["x"], sub["y"], match.meta)
    return pd.DataFrame({
        "playerName": sub["opta_id"].map(match.last_name),
        "x": ax, "y": ay,
    })


def line_height_m(match: DvmsMatch, side: str, phase: str) -> float | None:
    row = _shape_by_phase(match, side).get(phase)
    if row is None:
        return None
    v = row.get("def_line_m")
    return float(v) if pd.notna(v) else None


# --------------------------------------------------------------------------- #
# Final third / box entries
# --------------------------------------------------------------------------- #
def zone_entries_dvms(match: DvmsMatch, side: str) -> pd.DataFrame:
    """Passes that took the ball into the final third or the box, adapted to
    the pitch.entry_map contract. Opta has no carry events, so unlike the
    IMPECT version every arrow is a pass — the panel caption says so."""
    ev = _team_events(match, side)
    passes = ev[ev["is_pass"] & ev["end_x"].notna()
                & ~_quals_flag(ev, _Q_THROW_IN)].copy()

    into_ft = (passes["x"] < _FINAL_THIRD_X) & (passes["end_x"] >= _FINAL_THIRD_X)
    in_box_end = (passes["end_x"] >= _BOX_X) & passes["end_y"].between(_BOX_Y_LO, _BOX_Y_HI)
    in_box_start = (passes["x"] >= _BOX_X) & passes["y"].between(_BOX_Y_LO, _BOX_Y_HI)
    into_box = ~in_box_start & in_box_end
    entries = passes[into_ft | into_box].copy()
    if entries.empty:
        return pd.DataFrame(columns=["startAdjCoordinatesX", "startAdjCoordinatesY",
                                     "endAdjCoordinatesX", "endAdjCoordinatesY",
                                     "success", "carry", "threat"])

    sx, sy = _opta_to_adj(entries["x"], entries["y"])
    ex, ey = _opta_to_adj(entries["end_x"], entries["end_y"])
    goal = np.array([52.5, 0.0])
    d_start = np.hypot(goal[0] - sx, goal[1] - sy)
    d_end = np.hypot(goal[0] - ex, goal[1] - ey)
    return pd.DataFrame({
        "startAdjCoordinatesX": sx, "startAdjCoordinatesY": sy,
        "endAdjCoordinatesX": ex, "endAdjCoordinatesY": ey,
        "success": (entries["outcome"] == 1).to_numpy(),
        "carry": False,
        # Threat proxy: metres of progress toward the goal the entry made.
        "threat": np.maximum(d_start - d_end, 0.0),
    })


# --------------------------------------------------------------------------- #
# Player contributions (events + physical)
# --------------------------------------------------------------------------- #
def player_contributions_dvms(match: DvmsMatch, top_n: int = 10) -> pd.DataFrame:
    ev = match.events[match.events["player_id"].notna()]
    per = ev.groupby("player_id").agg(
        passes=("is_pass", lambda s: int(((ev.loc[s.index, "outcome"] == 1) & s).sum())),
        shots=("is_shot", "sum"),
        xg=("xg", lambda s: float(np.nansum(s))),
        recoveries=("type_id", lambda s: int((s == 49).sum())),
        aerials=("type_id", lambda s: int(((s == 44) & (ev.loc[s.index, "outcome"] == 1)).sum())),
        team_id=("team_id", "first"),
    ).reset_index()

    # Second Spectrum physical summary (DVMS subtype 43).  Carry the running
    # totals through to the combined report as well as the two fields used in
    # its contribution ranking.
    phys = match.physical[[
        "opta_player_id", "minutes", "distance", "hsr", "sprinting", "top_speed",
    ]]
    per = per.merge(phys, left_on="player_id", right_on="opta_player_id", how="left")
    per["name"] = per["player_id"].map(match.last_name)
    per["is_charlton"] = per["team_id"].map(
        lambda t: match.team_name_of(match.side_of(t)) == CHARLTON)
    per["involvements"] = per["passes"] + per["recoveries"] + 2 * per["shots"]
    per = per.sort_values(["xg", "involvements"], ascending=False).head(top_n)
    return per.reset_index(drop=True)

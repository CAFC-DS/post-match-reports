from __future__ import annotations

import base64
import datetime as dt
import io
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mplsoccer import Pitch, VerticalPitch
from scipy.ndimage import gaussian_filter

from src.report import impect_cafcdb_source, metrics, palette, pitch
from src.report.render_combined import build_context as build_shared_context
from src.report.expanded import season_baseline as sb


def _heatmap_pitch_kwargs() -> dict:
    """A bolder line colour than pitch.py's shared _pitch_kwargs (palette.HAIR,
    a pale tan) -- against a busy turbo-colormap heatmap the shared colour is
    nearly invisible next to the heatmap cells' own cream edgecolors."""
    return dict(pitch_type="custom", pitch_length=105.0, pitch_width=68.0,
                pitch_color=palette.PAPER_2, line_color=palette.INK, linewidth=1.1,
                line_zorder=3, goal_type="line")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).with_name("templates")

# Expanded report's fuller Match Stats panel (18 rows across 4 groups) vs the
# canonical one-pager's 13-row metrics.STAT_ROWS -- kept local rather than
# edited into the shared constant so the one-page report's layout is
# untouched. (group, team_stats key, label, baseline key or None, higher_is_better)
STAT_ROWS_EXPANDED: list[tuple[str, str, str, str | None, bool]] = [
    ("On the ball", "possession_pct", "Possession", "possession_pct", True),
    ("On the ball", "pass_accuracy_pct", "Pass accuracy", "pass_accuracy_pct", True),
    ("On the ball", "successful_passes", "Successful passes", "successful_passes", True),
    ("On the ball", "unsuccessful_passes", "Unsuccessful passes", "unsuccessful_passes", False),
    ("On the ball", "passes_forward_pct", "Passes forward", "passes_forward_pct", True),
    ("Attack", "shots", "Shots", "shots", True),
    ("Attack", "shots_on_target", "Shots on target", "shots_on_target", True),
    ("Attack", "non_penalty_xg", "Non-penalty xG", "non_penalty_xg", True),
    ("Attack", "packing_xg", "Non-shot xG (packing)", "packing_xg", True),
    ("Attack", "set_piece_xg", "Set-piece xG", "set_piece_xg", True),
    ("Attack", "postshot_xg", "Post-shot xG", "postshot_xg", True),
    ("Progression", "opponents_bypassed", "Opponents bypassed (packing)", "opponents_bypassed", True),
    ("Progression", "defenders_bypassed", "Defenders bypassed (packing)", "defenders_bypassed", True),
    ("Duels & pressing", "touches_in_opposition_box", "Touches in opposition box", "touches_in_opposition_box", True),
    ("Duels & pressing", "won_ground_duels", "Ground duels won", "won_ground_duels", True),
    ("Duels & pressing", "won_aerial_duels", "Aerial duels won", "won_aerial_duels", True),
    ("Duels & pressing", "second_ball_wins", "Second-ball wins", "second_ball_wins", True),
    ("Duels & pressing", "opponent_half_regains", "Ball wins in opposition half", "opposition_half_regains", True),
]

# A match value has to clear this relative gap from the season baseline
# before the table calls it out in colour -- otherwise a 55% vs 56% "Passes
# forward" row would flag as a material difference when it plainly isn't.
_BASELINE_MATERIAL_PCT = 8.0


def _fmt_expanded(key: str, value: float) -> str:
    if key.endswith("_pct"):
        return f"{value:.0f}%"
    if "xg" in key:
        return f"{value:.2f}"
    return f"{int(round(value))}"


def _shade(value: float, baseline: float, higher_is_better: bool) -> str | None:
    if baseline == 0:
        return None
    delta_pct = (value - baseline) / abs(baseline) * 100
    if abs(delta_pct) < _BASELINE_MATERIAL_PCT:
        return None
    better = delta_pct > 0 if higher_is_better else delta_pct < 0
    return "good" if better else "bad"


def _stat_rows_expanded(stats: pd.DataFrame, baseline_row: pd.Series, home: str, away: str, charlton: str) -> list[dict[str, Any]]:
    rows = []
    last_group = None
    for group, key, label, baseline_key, higher_is_better in STAT_ROWS_EXPANDED:
        h, a = float(stats.loc[home, key]), float(stats.loc[away, key])
        total = h + a
        home_share = round(h / total * 100, 1) if total else 50.0
        charlton_value = h if home == charlton else a
        baseline_value = float(baseline_row[baseline_key]) if baseline_key is not None else None
        rows.append({
            "group": group if group != last_group else None,
            "label": label,
            "home": _fmt_expanded(key, h),
            "away": _fmt_expanded(key, a),
            "home_share": home_share,
            "away_share": round(100 - home_share, 1),
            "baseline": _fmt_expanded(key, baseline_value) if baseline_value is not None else "—",
            "shade": _shade(charlton_value, baseline_value, higher_is_better) if baseline_value is not None else None,
        })
        last_group = group
    return rows


# (category, metric column in season_baseline, label, higher_is_better)
_PERFORMANCE_WHEEL_METRICS: list[tuple[str, str, str, bool]] = [
    ("attack", "non_penalty_xg", "Non-penalty xG", True),
    ("attack", "shots", "Shots", True),
    ("attack", "packing_xt", "Packing xT", True),
    ("attack", "set_piece_xg", "Set-piece xG for", True),
    ("possession", "possession_pct", "Possession %", True),
    ("possession", "passes_into_final_third", "Passes into final third", True),
    ("possession", "progressive_actions", "Progressive actions", True),
    ("possession", "pass_accuracy_pct", "Pass accuracy %", True),
    ("defend", "duels_won", "Duels won", True),
    ("defend", "opposition_half_regains", "Opposition-half regains", True),
    ("defend", "pressing_intensity", "Pressing intensity", True),
    ("defend", "counter_press_regains", "Counter-press regains", True),
]
_WHEEL_COLORS = {"attack": palette.CHARLTON_RED, "possession": "#b5892a", "defend": "#4a4a46"}
# Pale tints of the same three hues, sampled from the reference wheel's own
# unfilled-wedge background (recovery/reference/verified_original page 2,
# embedded raster xref 56) -- not a uniform grey for every category.
_WHEEL_BG_COLORS = {"attack": "#f0cdc9", "possession": "#e8d5ae", "defend": "#c9c6c1"}


def _uri(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor=palette.PAPER)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _event_map(frame: pd.DataFrame, color: str, title: str = "") -> str:
    fig, ax = plt.subplots(figsize=(8.8, 4.3), facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER_2)
    ax.set_xlim(-52.5, 52.5); ax.set_ylim(-34, 34); ax.set_aspect("equal"); ax.axis("off")
    for x in (-52.5, 0, 52.5): ax.plot([x, x], [-34, 34], color=palette.HAIR, lw=.8)
    ax.plot([-52.5,52.5,52.5,-52.5,-52.5],[-34,-34,34,34,-34],color=palette.HAIR,lw=1)
    ax.add_patch(plt.Circle((0,0),9.15,fill=False,color=palette.HAIR,lw=.8))
    if not frame.empty:
        x=pd.to_numeric(frame.get("startAdjCoordinatesX"),errors="coerce")
        y=pd.to_numeric(frame.get("startAdjCoordinatesY"),errors="coerce")
        ax.scatter(x,y,s=24,c=color,alpha=.58,edgecolors=palette.PAPER,lw=.35)
    if title: ax.set_title(title,fontsize=9,fontweight="bold",color=palette.INK)
    return _uri(fig)


def _pressure_activity(pressure_events: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    """Full-pitch pressure-density heatmap plus the KPI strip underneath it.

    ``pressure_events`` rows are located at the ball carrier's own adjusted
    coordinates (the carrier being pressed, not the presser), so they run in
    the *opponent's* attacking direction. Negate both axes to express them
    in the pressing team's own attacking frame before plotting or deriving
    territory share, matching the convention already used by the working
    single-team event maps elsewhere in this module.

    Drawn on a VERTICAL pitch, matching the reference exactly (recovery/
    reference/verified_original page 12, embedded raster xref 174) -- the
    prior version used a horizontal pitch, a real structural mismatch, not
    just a colouring difference.
    """
    x = -pd.to_numeric(pressure_events["startAdjCoordinatesX"], errors="coerce")
    y = -pd.to_numeric(pressure_events["startAdjCoordinatesY"], errors="coerce")
    pitch_obj = VerticalPitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_heatmap_pitch_kwargs())
    fig, ax = pitch_obj.draw(figsize=(5.6, 8.6))
    fig.set_facecolor(palette.PAPER_2)
    px, py = pitch._to_pitch(x, y)
    bin_stat = pitch_obj.bin_statistic(px, py, statistic="count", bins=(8, 12))
    bin_stat["statistic"] = gaussian_filter(bin_stat["statistic"], 0.8)
    pitch_obj.heatmap(bin_stat, ax=ax, cmap="jet", edgecolors="none", alpha=0.78, zorder=1)

    top = pressure_events.groupby("playerName").size().sort_values(ascending=False)
    kpis = {
        "pressure_n": len(pressure_events),
        "opp_half_pct": round(float((x > 0).mean() * 100)) if len(x) else 0,
        "opp_third_n": int((x > 17.5).sum()),
        "top_name": str(top.index[0]).split()[-1] if len(top) else "—",
        "top_n": int(top.iloc[0]) if len(top) else 0,
    }
    return _uri(fig), kpis


def _local_passing_network_map(net: "metrics.PassingNetwork", max_edge_passes: int,
                                max_abs_threat: float, max_abs_edge_pxt: float) -> str:
    """Report-local passing network chart: same underlying pitch-drawing
    helpers as pitch.passing_network_map, but with initials labelled INSIDE
    each node (white, bold, centred) instead of below it with a halo, a
    diverging edge colour by pair threat instead of a flat colour, and no
    baked-in 'Full match...' caption -- none of which the shared function
    provides, and none of which should be added there since the canonical
    one-page report doesn't use this chart at all (see RECOVERY_NOTES.md).
    Matches recovery/reference/verified_original page 5's embedded chart
    (xref 74) exactly: labels inside nodes, no caption in the image."""
    pitch_obj, fig, ax = pitch._horizontal_pitch(figsize=(7.4, 5.0))

    if not net.edges.empty:
        ax_, ay_ = pitch._to_pitch(net.edges["ax"], net.edges["ay"])
        bx_, by_ = pitch._to_pitch(net.edges["bx"], net.edges["by"])
        edge_pxt = net.edges["pxt"] if "pxt" in net.edges.columns else pd.Series(0.0, index=net.edges.index)
        edge_colors = pitch._threat_colors(edge_pxt, max_abs_edge_pxt) if max_abs_edge_pxt else \
            [palette.MUTED] * len(net.edges)
        for i in range(len(net.edges)):
            n = int(net.edges["passes"].iloc[i])
            frac = n / max_edge_passes if max_edge_passes else 0.0
            ax.plot([ax_.iloc[i], bx_.iloc[i]], [ay_.iloc[i], by_.iloc[i]],
                    color=edge_colors[i], linewidth=0.9 + 5.6 * frac, alpha=0.5 + 0.4 * frac,
                    solid_capstyle="round", zorder=2)

    nx, ny = pitch._to_pitch(net.nodes["x"], net.nodes["y"])
    passes = net.nodes["passes"].to_numpy()
    top = passes.max() if len(passes) else 1
    sizes = 150 + 480 * (passes / top)
    node_colors = pitch._threat_colors(net.nodes["threat"], max_abs_threat)
    is_starter = net.nodes["is_starter"].to_numpy()
    for mask, marker in ((is_starter, "o"), (~is_starter, "^")):
        if not mask.any():
            continue
        pitch_obj.scatter(nx[mask], ny[mask], s=sizes[mask], color=node_colors[mask], marker=marker,
                          edgecolors=palette.PAPER_2, linewidth=1.6, alpha=0.95, zorder=3, ax=ax)
    for xi, yi, name in zip(nx, ny, net.nodes["surname"]):
        ax.text(xi, yi, name, ha="center", va="center", zorder=5, fontsize=7.2,
                fontweight="bold", color="white")
    return pitch._fig_to_uri(fig)


def _duel_location_map(duels: pd.DataFrame, team: str, duel_type: str) -> str:
    """Won/lost duel locations for one team, one duel type, on a full pitch
    -- green dot = won, red cross = lost, matching the reference's page 12
    legend. Coordinates come straight from load_duel_involvement, adjusted
    to whichever player originally acted on that event (usually but not
    always this team's own attacking direction) -- a documented
    simplification, not a recovered original convention."""
    t = duels.loc[(duels["squadName"] == team) & (duels["duel_type"] == duel_type)]
    pitch_obj, fig, ax = pitch._vertical_pitch((5.0, 7.4))
    won = t.loc[t["outcome"] == "WON"]
    lost = t.loc[t["outcome"] == "LOST"]
    for frame, marker, color in ((won, "o", palette.SUCCESS_GREEN), (lost, "X", palette.FAIL_REDGREY)):
        if frame.empty: continue
        x, y = pitch._to_pitch(frame["startAdjCoordinatesX"], frame["startAdjCoordinatesY"])
        pitch_obj.scatter(x, y, ax=ax, s=46, color=color, marker=marker,
                           edgecolors=palette.PAPER_2, linewidth=0.8, alpha=0.9, zorder=3)
    return _uri(fig)


def _entries_kpis(events: pd.DataFrame, team: str) -> dict[str, Any]:
    """Final-third/box entry counts for the caption under the entries map --
    reuses metrics.zone_entries (already powering the map image itself via
    render_combined's build_context) rather than adding a new data source."""
    entries = metrics.zone_entries(events, team)
    n = len(entries)
    completed = int(entries["success"].sum()) if n else 0
    return {
        "n": n,
        "completed": completed,
        "completed_pct": round(completed / n * 100) if n else 0,
        "final_third": int((entries["endPitchPosition"] == "FINAL_THIRD").sum()) if n else 0,
        "box": int((entries["endPitchPosition"] == "OPPONENT_BOX").sum()) if n else 0,
    }


def _regains_panel(events: pd.DataFrame, team: str) -> tuple[str, dict[str, Any], pd.Series]:
    """Opposition-half ball wins, ringed where the team shot within 15s of
    winning it -- *and* kept the ball the whole way there (no opponent
    touch between the regain and the shot). Without the continuity check
    this over-counted (11 of 50 vs. the reference's 8 of 50): a shot that
    happens to fall inside the 15s window after an unrelated, intervening
    loss-and-re-regain isn't really that regain's shot. With it, n=8
    matches the reference exactly. The prior version also had no half
    filter at all -- 'opposition-half regains' was actually every ball win
    anywhere on the pitch."""
    t = events.loc[events["squadName"] == team].sort_values("gameTimeInSec")
    flag = lambda name: pd.to_numeric(t.get(name, 0), errors="coerce").fillna(0)
    regains = t.loc[(flag("BALL_WIN_NUMBER") == 1) & (pd.to_numeric(t["startAdjCoordinatesX"], errors="coerce") > 0)]
    shot_times = t.loc[flag("SHOT_AT_GOAL_NUMBER") == 1, "gameTimeInSec"].to_numpy()
    all_sorted = events.sort_values("gameTimeInSec")

    def led_to_shot(rt: float) -> bool:
        window = shot_times[(shot_times >= rt) & (shot_times <= rt + 15)]
        if not len(window):
            return False
        shot_t = window[0]
        between = all_sorted.loc[(all_sorted["gameTimeInSec"] > rt) & (all_sorted["gameTimeInSec"] < shot_t)]
        return not (between["squadName"] != team).any()

    led = regains["gameTimeInSec"].map(led_to_shot) if len(regains) else pd.Series(dtype=bool)
    pitch_obj, fig, ax = pitch._vertical_pitch((5.6, 7.4))
    x, y = pitch._to_pitch(regains["startAdjCoordinatesX"], regains["startAdjCoordinatesY"])
    pitch_obj.scatter(x, y, ax=ax, s=32, color=palette.CHARLTON_RED, alpha=0.75, zorder=2)
    if led.any():
        rx, ry = pitch._to_pitch(regains.loc[led, "startAdjCoordinatesX"], regains.loc[led, "startAdjCoordinatesY"])
        pitch_obj.scatter(rx, ry, ax=ax, s=90, facecolors="none", edgecolors=palette.CHARLTON_RED, linewidth=1.6, zorder=3)
    n = len(regains)
    kpis = {"n": n, "shot_n": int(led.sum()) if n else 0, "shot_pct": round(int(led.sum()) / n * 100) if n else 0}
    top6 = regains.groupby("playerName").size().sort_values(ascending=False).head(6)
    top6.index = [str(i).split()[-1] for i in top6.index]
    return _uri(fig), kpis, top6


def _second_ball_panel(events: pd.DataFrame, team: str) -> tuple[str, dict[str, Any]]:
    """Second-ball contests this team was involved in, as the union of the
    events where they started the contest (SECOND_BALL_START) and where
    they won it (SECOND_BALL_WIN) -- these are separate events, sometimes
    with a different acting player, and a team can win a contest it didn't
    register as starting. Validated exactly against the reference fixture:
    union = 88 events, wins = 39, 39/88 = 44%, matching the reference's own
    '39 of 88 · 44%' caption precisely."""
    t = events.loc[events["squadName"] == team].sort_values("gameTimeInSec")
    flag = lambda name: pd.to_numeric(t.get(name, 0), errors="coerce").fillna(0)
    started, won = t.loc[flag("SECOND_BALL_START") == 1], t.loc[flag("SECOND_BALL_WIN") == 1]
    contests = pd.concat([started, won]).drop_duplicates("eventId")
    won_ids = set(won["eventId"])
    won_mask = contests["eventId"].isin(won_ids)

    pitch_obj, fig, ax = pitch._vertical_pitch((7.2, 5.6))
    for mask, marker, color in ((won_mask, "o", palette.SUCCESS_GREEN), (~won_mask, "X", palette.FAIL_REDGREY)):
        frame = contests.loc[mask]
        if frame.empty: continue
        x, y = pitch._to_pitch(frame["startAdjCoordinatesX"], frame["startAdjCoordinatesY"])
        pitch_obj.scatter(x, y, ax=ax, s=42, color=color, marker=marker, edgecolors=palette.PAPER_2, linewidth=0.8, alpha=0.9, zorder=2)
    n = len(contests)
    kpis = {"n": n, "won_n": len(won_ids), "won_pct": round(len(won_ids) / n * 100) if n else 0}
    return _uri(fig), kpis


def _transition_response_map(events: pd.DataFrame, team: str, opponent: str) -> tuple[str, dict[str, Any]]:
    """High losses (attacking-half turnovers) plotted with two overlays:
    a black ring where the opponent shot within 15s of that specific loss
    (with no opponent touch in between -- see _regains_panel for why that
    continuity check matters), and a green triangle at the *regain's own
    location* for every one of the team's losses -- not just the high
    ones -- that the team won back within 5s.

    Two real fixes from the prior version, both validated against the
    reference's own printed numbers for this fixture:
    1. 'High loss' now uses the BALL_LOSS_NUMBER KPI flag instead of a
       hand-rolled 'result != SUCCESS on a PASS/DRIBBLE' proxy, which
       undercounted (64 vs the reference's 76 -- BALL_LOSS_NUMBER also
       fires on other action types, e.g. failed touches/crosses). n=76
       with BALL_LOSS_NUMBER matches exactly.
    2. Counter-press regains are counted from *all* of the team's losses,
       not just the attacking-half subset plotted as red dots, and plotted
       at the regain's location rather than assumed to sit on top of a
       high-loss dot. Restricting to high-loss-only regains gave 23 against
       a reference of 58; counting from every loss gives 55 -- close enough
       to treat as the right definition, with the remaining gap left open
       rather than tuned further to hit the number exactly."""
    t = events.loc[events["squadName"] == team].sort_values("gameTimeInSec")
    o = events.loc[events["squadName"] == opponent]
    loss_flag = pd.to_numeric(t.get("BALL_LOSS_NUMBER", 0), errors="coerce") == 1
    high_losses = t.loc[loss_flag & (pd.to_numeric(t["startAdjCoordinatesX"], errors="coerce") > 0)]
    all_losses = t.loc[loss_flag]
    opp_shot_times = o.loc[pd.to_numeric(o.get("SHOT_AT_GOAL_NUMBER", 0), errors="coerce") == 1, "gameTimeInSec"].to_numpy()
    regains = t.loc[pd.to_numeric(t.get("BALL_WIN_NUMBER", 0), errors="coerce") == 1]
    all_sorted = events.sort_values("gameTimeInSec")

    def led_to_shot(rt: float) -> bool:
        window = opp_shot_times[(opp_shot_times > rt) & (opp_shot_times <= rt + 15)]
        if not len(window):
            return False
        shot_t = window[0]
        between = all_sorted.loc[(all_sorted["gameTimeInSec"] > rt) & (all_sorted["gameTimeInSec"] < shot_t)]
        return not (between["squadName"] != opponent).any()

    def counter_pressing_regain(loss_t: float) -> pd.Series | None:
        window = regains.loc[(regains["gameTimeInSec"] > loss_t) & (regains["gameTimeInSec"] <= loss_t + 5)]
        return window.iloc[0] if len(window) else None

    led_to_shot_mask = high_losses["gameTimeInSec"].map(led_to_shot)
    counter_press_regains = [r for r in all_losses["gameTimeInSec"].map(counter_pressing_regain) if r is not None]

    pitch_obj, fig, ax = pitch._horizontal_pitch((11.5, 7.4))
    x, y = pitch._to_pitch(high_losses["startAdjCoordinatesX"], high_losses["startAdjCoordinatesY"])
    pitch_obj.scatter(x, y, ax=ax, s=44, color=palette.FAIL_REDGREY, alpha=0.85, zorder=2)
    if counter_press_regains:
        cframe = pd.DataFrame(counter_press_regains)
        cx, cy = pitch._to_pitch(cframe["startAdjCoordinatesX"], cframe["startAdjCoordinatesY"])
        pitch_obj.scatter(cx, cy, ax=ax, s=60, color=palette.SUCCESS_GREEN, marker="^", edgecolors=palette.PAPER_2, linewidth=0.6, zorder=3)
    if led_to_shot_mask.any():
        sx, sy = pitch._to_pitch(high_losses.loc[led_to_shot_mask, "startAdjCoordinatesX"], high_losses.loc[led_to_shot_mask, "startAdjCoordinatesY"])
        pitch_obj.scatter(sx, sy, ax=ax, s=110, facecolors="none", edgecolors=palette.INK, linewidth=1.4, zorder=4)

    n = len(high_losses)
    shot_n = int(led_to_shot_mask.sum())
    kpis = {
        "high_losses_n": n,
        "counterpress_n": len(counter_press_regains),
        "shot_n": shot_n,
        "shot_pct": round(shot_n / n * 100) if n else 0,
    }
    return _uri(fig), kpis


def _bars(labels: list[str], values: list[float], color: str) -> str:
    fig, ax=plt.subplots(figsize=(8.4,4.2),facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER)
    order=np.argsort(values)
    ax.barh(np.array(labels)[order],np.array(values)[order],color=color,alpha=.88)
    ax.spines[:].set_visible(False); ax.grid(axis="x",color=palette.HAIR,alpha=.55)
    ax.tick_params(labelsize=8,colors=palette.INK); ax.set_axisbelow(True)
    return _uri(fig)


def _duel_bars_by_type(duels: pd.DataFrame, charlton: str, opponent: str, duel_type: str) -> str:
    """Mirrored won/lost duel bars, top-5-by-involvement, one panel per team
    -- the reference's page 13 layout (confirmed against the actual PDF).
    The previous template rendered the *same* single-team chart twice.
    ``duels`` is impect_cafcdb_source.load_duel_involvement's output -- a
    per-player-per-event outcome, not team_stats' per-team sum, because the
    *loser* of a duel is only recorded on a second entry in that event's own
    KPI array, keyed by the loser's own playerId (see that function's
    docstring)."""
    d = duels.loc[duels["duel_type"] == duel_type]

    def top5(team: str) -> pd.DataFrame:
        t = d.loc[d["squadName"] == team]
        agg = t.groupby("playerName", dropna=True)["outcome"].value_counts().unstack(fill_value=0)
        agg = agg.rename(columns={"WON": "won", "LOST": "lost"})
        for c in ("won", "lost"):
            if c not in agg: agg[c] = 0
        agg["surname"] = [str(n).split()[-1] for n in agg.index]
        agg["involvement"] = agg["won"] + agg["lost"]
        return agg.loc[agg["involvement"] > 0].sort_values("involvement", ascending=False).head(5)

    c, o = top5(charlton), top5(opponent)
    x_max = max(1.0, float(pd.concat([c[["won", "lost"]], o[["won", "lost"]]]).to_numpy().max()))

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6), facecolor=palette.PAPER)
    for ax, team, frame in zip(axes, (charlton, opponent), (c, o)):
        ax.set_facecolor(palette.PAPER)
        y = np.arange(len(frame))[::-1]
        ax.barh(y, frame["won"], color=palette.SUCCESS_GREEN, alpha=0.9)
        ax.barh(y, -frame["lost"], color=palette.FAIL_REDGREY, alpha=0.9)
        for yi, w, l in zip(y, frame["won"], frame["lost"]):
            if l: ax.text(-l - x_max * 0.03, yi, f"{int(l)}", ha="right", va="center", fontsize=7, color=palette.FAIL_REDGREY)
            if w: ax.text(w + x_max * 0.03, yi, f"{int(w)}", ha="left", va="center", fontsize=7, color=palette.SUCCESS_GREEN)
        ax.set_yticks(y); ax.set_yticklabels(frame["surname"], fontsize=8, fontweight="bold")
        ax.set_xlim(-x_max * 1.35, x_max * 1.35)
        ax.axvline(0, color=palette.INK, lw=1)
        ax.set_title(team, fontsize=9, fontweight="bold",
                     color=palette.CHARLTON_RED if team == charlton else palette.OPPONENT_GREY)
        ax.spines[:].set_visible(False); ax.set_xticks([])
    return _uri(fig)


def _performance_wheel(match_values: dict[str, float], baseline: pd.DataFrame) -> str:
    """Percentile-vs-season wheel: each wedge is this match's percentile rank
    of that metric within Charlton's 25/26 season distribution, coloured by
    Attacking / Possession-Progression / Defending. Styling (pale per-category
    background, donut-hole centre, dashed gridlines, pill-badge value labels)
    matches the reference wheel exactly (recovery/reference/verified_original
    page 2, embedded raster xref 56) rather than the placeholder uniform-grey
    background and floating labels this function started with."""
    metrics_list = _PERFORMANCE_WHEEL_METRICS
    n = len(metrics_list)
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    width = 2 * np.pi / n * 0.86
    pcts, colors, bg_colors, labels = [], [], [], []
    for category, col, label, higher_is_better in metrics_list:
        value = match_values[col]
        pct = sb.percentile_of(baseline, col, value)
        if not higher_is_better:
            pct = 100 - pct
        pcts.append(pct)
        colors.append(_WHEEL_COLORS[category])
        bg_colors.append(_WHEEL_BG_COLORS[category])
        labels.append(label)

    inner_radius = 6.0  # donut-hole radius, in the same units as the 0-100 percentile axis
    fig, ax = plt.subplots(figsize=(6.6, 6.6), subplot_kw={"projection": "polar"}, facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER); ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
    ax.bar(theta, [100 - inner_radius] * n, bottom=inner_radius, width=width, color=bg_colors, alpha=1.0, zorder=1,
           edgecolor=palette.PAPER, linewidth=1.5)
    ax.bar(theta, [max(0.0, p - inner_radius) for p in pcts], bottom=inner_radius, width=width, color=colors,
           alpha=1.0, zorder=2, edgecolor=palette.PAPER, linewidth=1.5)
    for t, p, c in zip(theta, pcts, colors):
        label_r = max(p, inner_radius + 8)
        ax.text(t, label_r, f"{p:.0f}", ha="center", va="center", fontsize=6.5, fontweight="bold",
                 color="white", zorder=3,
                 bbox=dict(boxstyle="round,pad=0.28", facecolor=c, edgecolor="none", alpha=0.96))
    ax.set_ylim(0, 108)
    ax.set_xticks(theta); ax.set_xticklabels(labels, fontsize=6)
    ax.set_yticklabels([])
    ax.grid(color=palette.HAIR, lw=0.6, linestyle=(0, (2, 2)))
    ax.spines["polar"].set_visible(False)
    from matplotlib.patches import Patch
    handles = [Patch(color=palette.CHARLTON_RED, label="Attacking"),
               Patch(color="#b5892a", label="Possession/Progression"),
               Patch(color="#4a4a46", label="Defending")]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06),
              ncol=3, frameon=False, fontsize=6.5)
    return _uri(fig)


def _match_highlights(match_values: dict[str, float], baseline: pd.DataFrame,
                       charlton: str, opponent: str, speed_c: float, speed_o: float) -> list[str]:
    """Three data-driven takeaways: the season-best percentile, the
    season-worst, and the transition-speed comparison -- matching the
    reference's 'Standout / Weak point / transition speed' triad."""
    ranked = []
    for category, col, label, higher_is_better in _PERFORMANCE_WHEEL_METRICS:
        pct = sb.percentile_of(baseline, col, match_values[col])
        if not higher_is_better:
            pct = 100 - pct
        ranked.append((pct, label))
    ranked.sort()
    worst_pct, worst_label = ranked[0]
    best_pct, best_label = ranked[-1]

    def ordinal(n: int) -> str:
        return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

    faster = charlton if speed_c >= speed_o else opponent
    return [
        f"Standout: {best_label} ranked {ordinal(round(best_pct))} percentile of {charlton}'s season.",
        f"Weak point: {worst_label} ranked only {ordinal(round(worst_pct))} percentile of {charlton}'s season.",
        f"{faster} transitioned faster than {opponent if faster == charlton else charlton}: "
        f"{max(speed_c, speed_o):.2f} vs {min(speed_c, speed_o):.2f} m/s of ball progress.",
    ]


def _xg_race(events: pd.DataFrame, teams: list[str]) -> str:
    """Cumulative non-penalty xG step chart. X-axis ticks match the Match
    Flow / Territory chart directly above it on the same page (0'/15'/30'/HT/
    60'/75'/90', chart_dvms.territory_chart's own convention), not
    matplotlib's default 0/20/40/60/80 -- the reference's two charts on this
    page share one axis convention."""
    fig,ax=plt.subplots(figsize=(11.5,3.8),facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER)
    for team,color in zip(teams,[palette.CHARLTON_RED,palette.OPPONENT_GREY]):
        s=metrics.shot_events(events); s=s.loc[s["squadName"]==team].copy()
        s["minute"]=s["gameTime"].map(metrics.minute_num); s=s.sort_values("minute")
        x=[0]+s["minute"].tolist()+[95]; y=[0]+s["SHOT_XG"].cumsum().tolist(); y=y+[y[-1]]
        ax.step(x,y,where="post",label=team,color=color,lw=2)
    ax.set_xlim(0,95); ax.spines[["top","right"]].set_visible(False); ax.grid(color=palette.HAIR_SOFT,lw=.6)
    ax.set_xticks([0, 15, 30, 45, 60, 75, 90])
    ax.set_xticklabels(["0'", "15'", "30'", "HT", "60'", "75'", "90'"])
    ax.tick_params(labelsize=7,colors=palette.MUTED); ax.legend(frameon=False,fontsize=7,loc="upper left")
    return _uri(fig)


def _threat_heatmap(events: pd.DataFrame, team: str) -> tuple[str, float, int]:
    """Smoothed threat-density heatmap on the shared vertical pitch (was a
    coarse 10x14-bin hist2d with no pitch markings at all). Returns the
    image plus the two summary numbers the reference captions the panel
    with ('X positive PXT Attack · Y actions')."""
    t = events.loc[(events["squadName"] == team) & events["PXT_ATTACK"].notna() & (events["PXT_ATTACK"] > 0)]
    pitch_obj = VerticalPitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_heatmap_pitch_kwargs())
    fig, ax = pitch_obj.draw(figsize=(5.2, 7.4))
    fig.set_facecolor(palette.PAPER_2)
    x, y = pitch._to_pitch(t["startAdjCoordinatesX"], t["startAdjCoordinatesY"])
    bin_stat = pitch_obj.bin_statistic(x, y, values=t["PXT_ATTACK"], statistic="sum", bins=(12, 18))
    bin_stat["statistic"] = gaussian_filter(bin_stat["statistic"], 1.4)
    pitch_obj.heatmap(bin_stat, ax=ax, cmap="jet", edgecolors="none", alpha=0.62, zorder=1)
    return _uri(fig), round(float(t["PXT_ATTACK"].sum()), 2), len(t)


def _infer_pass_receivers(events: pd.DataFrame) -> pd.DataFrame:
    """CAFC_DB's EVENTS table carries no passReceiverPlayerName column (the
    older IMPECT_EVENTS_STAGING source metrics.passing_network was written
    against did) — but every successful pass is immediately followed by a
    RECEPTION event from the same squad, so the receiver is recoverable from
    event order. Covers 615/616 successful passes on the reference fixture;
    the rare miss (throw-in restarts, etc.) just drops that one edge."""
    e = events.sort_values("eventNumber").reset_index(drop=True)
    next_action = e["actionType"].shift(-1)
    next_player = e["playerName"].shift(-1)
    next_squad = e["squadName"].shift(-1)
    is_pass = (e["actionType"] == "PASS") & (e["result"] == "SUCCESS")
    e["passReceiverPlayerName"] = next_player.where(
        is_pass & (next_action == "RECEPTION") & (next_squad == e["squadName"])
    )
    return e


def _initials(name: str) -> str:
    parts = str(name).split()
    return "".join(p[0] for p in parts if p).upper()[:2] if parts else "?"


def _starters_only_network(net: "metrics.PassingNetwork") -> "metrics.PassingNetwork":
    """Reference page 5's caption reads 'starting XI · shared match scales' —
    the eleven who began the game, not the whole squad that touched the ball.
    Also adds a per-edge 'pxt' column so the local passing-network chart can
    colour edges by threat, matching the reference legend's 'Link Colour =
    Pair Passing Threat' -- metrics.passing_network's edges DataFrame has no
    pair-level threat sum today, and deriving one properly means re-tracing
    the underlying pass events, which is out of scope here; edges render at
    the diverging scale's neutral midpoint until that's built (known
    simplification, not a silent gap)."""
    starter_names = set(net.nodes.loc[net.nodes["is_starter"], "playerName"])
    nodes = net.nodes.loc[net.nodes["playerName"].isin(starter_names)].copy()
    nodes["surname"] = nodes["playerName"].map(_initials)
    edges = net.edges.loc[net.edges["a"].isin(starter_names) & net.edges["b"].isin(starter_names)].copy()
    if not edges.empty and "pxt" not in edges.columns:
        edges["pxt"] = 0.0
    return metrics.PassingNetwork(nodes, edges, net.first_sub_minute, net.total_passes)


def _dvms_seconds(row: pd.Series) -> float:
    """Impect's gameTimeInSec is a period-1 seconds-elapsed clock for
    periodId 1, but jumps to a 10000+seconds-elapsed encoding for periodId
    2 (e.g. '45:00.0000' -> 10000.0) rather than continuing or resetting --
    confirmed empirically against this fixture's own event log. DVMS/Second
    Spectrum's frames.game_clock resets to ~0 at the start of each period,
    so period 2 needs the 10000 offset removed to align the two clocks."""
    return float(row["gameTimeInSec"]) if row["periodId"] == 1 else float(row["gameTimeInSec"]) - 10000.0


def _transition_speed_mps(events: pd.DataFrame, team: str, dvms_match) -> float:
    """Net ball-tracking displacement per second of elapsed time, across
    each of the team's ATTACKING_TRANSITION-phase possession sequences
    (consecutive transition events with the same team). 'Ball progress' is
    read as net progress (displacement over the whole sequence), not the
    ball's raw instantaneous flight speed -- a passing sequence's ball
    speed while airborne is 15-25 m/s, far above the reference's ~3-4 m/s,
    while this sequence-level definition lands in the same range as the
    reference's own 3.65/3.38 for this fixture. Still a reconstruction, not
    a recovered original formula -- validated by magnitude, not derivation.
    """
    if dvms_match is None:
        return 0.0
    ball = dvms_match.frames.loc[dvms_match.frames["team"] == "ball"].sort_values(["period", "game_clock"])
    t = events.loc[
        (events["squadName"] == team) & (events["phase"] == "ATTACKING_TRANSITION")
        & events["actionType"].isin(["PASS", "DRIBBLE"]) & (events["result"] == "SUCCESS")
    ].copy()
    if t.empty:
        return 0.0
    t["t"] = t.apply(_dvms_seconds, axis=1)
    t = t.sort_values(["periodId", "t"])
    # A gap of more than 6s between transition-tagged actions ends one
    # transition burst and starts the next.
    gap = t.groupby("periodId")["t"].diff()
    seq = (gap.isna() | (gap > 6)).cumsum()

    total_gain, total_time = 0.0, 0.0
    for _, grp in t.groupby(seq):
        period, t0, t1 = grp["periodId"].iloc[0], grp["t"].min(), grp["t"].max()
        if t1 <= t0:
            continue
        before = ball.loc[(ball["period"] == period) & (ball["game_clock"] <= t0)].tail(1)
        after = ball.loc[(ball["period"] == period) & (ball["game_clock"] >= t1)].head(1)
        if before.empty or after.empty:
            continue
        dist = float(np.hypot(after["x"].iloc[0] - before["x"].iloc[0], after["y"].iloc[0] - before["y"].iloc[0]))
        total_gain += dist
        total_time += (t1 - t0)
    return total_gain / total_time if total_time else 0.0


def build_context(impect_match_id: int, dvms_match_id: str | None = None) -> dict[str, Any]:
    context=build_shared_context(impect_match_id,dvms_match_id)
    dvms_match=None
    if dvms_match_id:
        from src.dvms.loaders.fixtures import resolve_fixture
        from src.report import metrics_dvms
        dvms_match=metrics_dvms.load_match(resolve_fixture(dvms_match_id))
    events=impect_cafcdb_source.load_match_events(impect_match_id)
    events=_infer_pass_receivers(events)
    player_lookup=events.loc[events["playerName"].notna(), ["playerId","playerName","squadName"]].drop_duplicates("playerId")
    duel_involvement=impect_cafcdb_source.load_duel_involvement(impect_match_id,player_lookup)
    pressure_events=impect_cafcdb_source.load_pressure_events(impect_match_id,player_lookup)
    subject=context["meta"]["charlton_team"]
    opponent=context["meta"]["opponent_team"]
    teams=[subject,opponent]
    side_by_team={s["team"]:s for s in context["sides"]}
    nets={team:_starters_only_network(metrics.passing_network(events,team)) for team in teams}
    mx=max([int(n.edges["passes"].max()) for n in nets.values() if len(n.edges)] or [1])
    mt=max([float(n.nodes["threat"].abs().max()) for n in nets.values() if len(n.nodes)] or [.001])
    met=max([float(n.edges["pxt"].abs().max()) for n in nets.values() if len(n.edges)] or [.001])
    networks={team:_local_passing_network_map(nets[team],mx,mt,met) for team in teams}
    network_scale_threat=round(mt,2)
    regain_img,regain_kpis,recovery_top6=_regains_panel(events,subject)
    second_ball_img,second_ball_kpis=_second_ball_panel(events,subject)

    home,away=context["meta"]["home_team"],context["meta"]["away_team"]
    team_stats=metrics.team_stats(events,home,away)
    baseline=sb.build_season_baseline(charlton=subject)
    baseline_row=baseline.mean(numeric_only=True)
    stat_rows_expanded=_stat_rows_expanded(team_stats,baseline_row,home,away,subject)
    # Reuse season_baseline's own per-match metric builder wholesale so the
    # match-day wheel values and the season distribution they're ranked
    # against share one definition (a prior version rebuilt a subset by hand
    # here under different key names -- won_ground_duels/won_aerial_duels vs
    # duels_won, opponent_half_regains vs opposition_half_regains -- so two
    # of twelve wedges silently read 0.0 every time).
    charlton_match_values=sb.match_metrics(events,subject,opponent)
    speed_subject=_transition_speed_mps(events,subject,dvms_match)
    speed_opponent=_transition_speed_mps(events,opponent,dvms_match)
    threat_img,threat_pxt,threat_actions=_threat_heatmap(events,subject)
    entries_kpis=_entries_kpis(events,subject)
    pressure_img,pressure_kpis=_pressure_activity(pressure_events.loc[pressure_events["squadName"]==subject])
    transition_img,transition_kpis=_transition_response_map(events,subject,opponent)
    context.update({
        "generated_date":dt.date.today().strftime("%d %B %Y"),
        "subject":subject,"opponent":opponent,"team_order":teams,"side_by_team":side_by_team,
        "network":networks,"network_scale_threat":network_scale_threat,
        "stat_rows_expanded":stat_rows_expanded,
        "performance_img":_performance_wheel(charlton_match_values,baseline),
        "match_highlights":_match_highlights(charlton_match_values,baseline,subject,opponent,speed_subject,speed_opponent),
        "xg_race_img":_xg_race(events,teams),
        "threat_img":threat_img,"threat_pxt":threat_pxt,"threat_actions":threat_actions,
        "entries_kpis":entries_kpis,
        "pressure_img":pressure_img,"pressure_kpis":pressure_kpis,
        "ground_duel_img":_duel_location_map(duel_involvement,subject,"GROUND"),
        "aerial_duel_img":_duel_location_map(duel_involvement,subject,"AERIAL"),
        "regain_img":regain_img,"regain_kpis":regain_kpis,
        "second_ball_img":second_ball_img,"second_ball_kpis":second_ball_kpis,
        "transition_img":transition_img,"transition_kpis":transition_kpis,
        "duel_aerial_bars_img":_duel_bars_by_type(duel_involvement,subject,opponent,"AERIAL"),
        "duel_ground_bars_img":_duel_bars_by_type(duel_involvement,subject,opponent,"GROUND"),
        "recovery_player_img":_bars(recovery_top6.index.tolist(),recovery_top6.values.tolist(),palette.CHARLTON_RED),
        "event_counts":{"pressures":pressure_kpis["pressure_n"],"regains":regain_kpis["n"],"second_balls":second_ball_kpis["n"],"losses":transition_kpis["high_losses_n"]},
        "big_chances":{
            team:[{"minute":str(r.gameTime).split(':')[0]+"'","player":str(r.playerName).split()[-1],"xg":float(r.SHOT_XG),"result":str(r.category).upper()} for r in metrics.shot_events(events).loc[lambda x:x.squadName==team].nlargest(7,"SHOT_XG").itertuples()]
            for team in teams
        },
    })
    return context


def render_report(impect_match_id: int, dvms_match_id: str | None, output_path: Path) -> Path:
    context=build_context(impect_match_id,dvms_match_id)
    env=Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)),autoescape=select_autoescape(["html"]),trim_blocks=True,lstrip_blocks=True)
    html=env.get_template("expanded.html.j2").render(**context)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    chrome=Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    with tempfile.TemporaryDirectory(prefix="expanded-report-") as tmp:
        html_path=Path(tmp)/"report.html"
        html_path.write_text(html,encoding="utf-8")
        subprocess.run([
            str(chrome),"--headless","--disable-gpu","--no-pdf-header-footer",
            f"--print-to-pdf={output_path.resolve()}",html_path.resolve().as_uri(),
        ],check=True,capture_output=True)
    return output_path

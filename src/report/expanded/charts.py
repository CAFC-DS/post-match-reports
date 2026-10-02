"""Chart builders for the expanded analyst report (matplotlib -> base64 PNG data URIs) and the
small metric helpers that sit next to them. Moved out of ``working.py`` unchanged."""
from __future__ import annotations

import base64
import io
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap, PowerNorm
from mplsoccer import Pitch
from scipy.ndimage import gaussian_filter

from src.report import metrics, palette, pitch
from src.report.expanded import overview as overview_mod
from src.report.expanded import season_baseline as sb


def _heatmap_pitch_kwargs() -> dict:
    """A bolder line colour than pitch.py's shared _pitch_kwargs (palette.HAIR,
    a pale tan) -- against a busy turbo-colormap heatmap the shared colour is
    nearly invisible next to the heatmap cells' own cream edgecolors."""
    return dict(pitch_type="custom", pitch_length=105.0, pitch_width=68.0,
                pitch_color=palette.PAPER_2, line_color=palette.INK, linewidth=1.1,
                line_zorder=3, goal_type="line")


# The same smooth-gradient "thermal ramp" technique (fine bins + heavy
# gaussian smoothing + this 8-stop colormap + PowerNorm contrast) that
# full-season-analysis/src/report_engine/chart_builder.py uses for its own
# density heatmaps -- replacing the old cmap="jet" + coarse-bin look, which
# read as blocky and garish next to this report's warmer palette.
_THERMAL_CMAP = LinearSegmentedColormap.from_list(
    "thermal", ["#eff3f0", "#3b6ea5", "#3aa8a0", "#7ec850", "#f5d020", "#f08a24", "#e02418", "#7c0c0e"],
)


# (category, metric column in season_baseline, label, higher_is_better)
_PERFORMANCE_WHEEL_METRICS: list[tuple[str, str, str, bool]] = [
    ("attack", "non_penalty_xg", "Non-penalty xG", True),
    ("attack", "shots", "Shots", True),
    ("attack", "packing_xt", "Packing xT", True),
    ("attack", "set_piece_xg", "Set-piece xG for", True),
    ("possession", "possession_pct", "Possession %", True),
    ("possession", "pass_accuracy_pct", "Pass accuracy %", True),
    ("possession", "progressive_actions", "Progressive actions", True),
    ("possession", "passes_into_final_third", "Passes into final third", True),
    ("defend", "pressing_intensity", "Pressing intensity", True),
    ("defend", "opposition_half_regains", "Opposition-half\nregains", True),
    ("defend", "duels_won_pct", "Duels Won %", True),
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


def _uri_fixed(fig) -> str:
    """Like _uri, but saves the full figure canvas at its exact figsize
    instead of cropping to a tight bbox around the drawn content. Match Flow
    and xG Race (page 3) share one 0-95 minute x-axis and must line up when
    stacked -- tight-bbox cropping trims each figure's margins differently
    depending on that figure's own label/legend/annotation extents, so even
    identical figsize + identical xlim charts land with the x=0 tick at a
    different fraction of image width once saved. A fixed canvas with
    identical subplots_adjust margins on both charts keeps that fraction
    the same on both, so they align."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, facecolor=palette.PAPER)
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
        # Perceptual stretch (sqrt of magnitude, sign preserved), not a
        # linear normalise: on the shared match scale, one team's worst
        # combination is often small next to the OTHER team's best one, so a
        # linear map leaves every edge within a few % of the neutral
        # midpoint -- technically still a gradient, but reads as flat grey.
        # This still respects sign and shared scale, just makes small
        # departures from neutral visible instead of washed out.
        edge_t = np.sign(edge_pxt) * (edge_pxt.abs() / max_abs_edge_pxt).pow(0.55) if max_abs_edge_pxt else edge_pxt * 0
        edge_colors = pitch._threat_colors(edge_t, 1.0) if max_abs_edge_pxt else \
            [palette.MUTED] * len(net.edges)
        for i in range(len(net.edges)):
            n = int(net.edges["passes"].iloc[i])
            frac = n / max_edge_passes if max_edge_passes else 0.0
            ax.plot([ax_.iloc[i], bx_.iloc[i]], [ay_.iloc[i], by_.iloc[i]],
                    color=edge_colors[i], linewidth=1.1 + 6.4 * frac, alpha=0.82 + 0.18 * frac,
                    solid_capstyle="round", zorder=2)

    nx, ny = pitch._to_pitch(net.nodes["x"], net.nodes["y"])
    passes = net.nodes["passes"].to_numpy()
    top = passes.max() if len(passes) else 1
    sizes = 220 + 620 * (passes / top)
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


def _player_threat_ranking(events: pd.DataFrame, charlton: str, opponent: str) -> tuple[str, dict[str, str]]:
    """Open-play creation (pass + carry PXT_ATTACK, goals excluded), top 6 per
    team, as two side-by-side panels.

    Sums *positive* PXT_ATTACK only (clipped at 0), matching the convention
    the rest of this report already uses for 'creation' (the Threat Density
    Map's caption, packing_xt in the stats table) -- summing the raw signed
    value included every backward/lateral pass's small threat *loss* too,
    which pushed both teams' totals net negative match-wide and made the
    ranking read as nonsensical (a team that scored twice showing as
    net-negative 'creators'). Positive-only is what 'creation' means here.

    The per-team name and team-total headers are returned as plain text
    rather than drawn onto the figure: every other panel in this report
    keeps that kind of caption in HTML (e.g. the Threat Density Map's
    "positive PXT Attack · actions" line), which renders in the report's
    real type system instead of a raster matplotlib title competing with
    the panel's own HTML header for visual weight."""
    t = events.loc[events["actionType"].isin(["PASS", "DRIBBLE"]) & (events["action"] != "GOAL")].copy()
    t["pxt_pos"] = t["PXT_ATTACK"].clip(lower=0)
    g = t.groupby(["playerName", "squadName"])["pxt_pos"].sum().reset_index()
    g["surname"] = g["playerName"].apply(lambda n: str(n).split()[-1])
    team_totals = g.groupby("squadName")["pxt_pos"].sum()
    vmax = float(g["pxt_pos"].max()) or 1.0

    # This panel sits in a short, wide card (~5.9:1) -- the previous 19x6.4
    # figure (2.97:1) was much taller than the card needed, so `object-fit:
    # contain` shrank it to fit the height and left most of the card blank.
    fig, axes = plt.subplots(1, 2, figsize=(19.0, 3.4), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.09, right=0.97, top=0.94, bottom=0.18, wspace=0.4)
    totals: dict[str, str] = {}
    for ax, team, color in zip(axes, (charlton, opponent), (palette.CHARLTON_RED, palette.OPPONENT_GREY)):
        top = g.loc[g["squadName"] == team].sort_values("pxt_pos", ascending=False).head(5)
        total = team_totals[team] or 1.0
        y = np.arange(len(top))[::-1] * 1.4
        ax.set_facecolor(palette.PAPER)
        ax.barh(y, top["pxt_pos"], color=color, alpha=0.9, zorder=2, height=0.8)
        for yi, val in zip(y, top["pxt_pos"]):
            ax.text(val + vmax * 0.035, yi, f"{val:.3f}  ({val / total * 100:.0f}%)", va="center",
                    ha="left", fontsize=13, fontweight="bold", color=palette.INK)
        ax.set_yticks(y); ax.set_yticklabels(top["surname"], fontsize=14, fontweight="bold")
        ax.set_xlim(0, vmax * 1.5)
        xticks = np.linspace(0, vmax, 4)
        ax.set_xticks(xticks); ax.set_xticklabels([f"{v:.2f}" for v in xticks], fontsize=10, color=palette.MUTED)
        ax.set_xlabel("Positive PXT Attack (pass + carry)", fontsize=10, color=palette.MUTED)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(palette.HAIR)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", length=3, colors=palette.MUTED)
        ax.grid(axis="x", color=palette.HAIR_SOFT, lw=0.5, zorder=1)
        ax.set_axisbelow(True)
        totals[team] = f"{total:.2f}"
    return _uri_fixed(fig), totals


def _second_ball_kpis(events: pd.DataFrame, team: str, baseline: pd.DataFrame) -> dict[str, Any]:
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
    n = len(pd.concat([started, won]).drop_duplicates("eventId"))
    won_n = won["eventId"].nunique()
    baseline_avg = float(baseline["second_ball_wins"].mean())
    return {
        "n": n, "won_n": won_n, "won_pct": round(won_n / n * 100) if n else 0,
        "baseline_avg": round(baseline_avg, 1), "baseline_delta": f"{won_n - baseline_avg:+.1f}",
        "baseline_n": len(baseline),
    }


def _transition_response_map(events: pd.DataFrame, team: str, opponent: str) -> tuple[str, dict[str, Any]]:
    """High losses (attacking-half turnovers) plotted with two overlays:
    a black ring where the opponent shot within 15s of that specific loss
    (with no opponent touch in between -- see outofpossession.regains for why that
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
        pitch_obj.scatter(sx, sy, ax=ax, s=90, color=palette.INK, marker="x", linewidth=2.2, zorder=4)

    n = len(high_losses)
    shot_n = int(led_to_shot_mask.sum())
    kpis = {
        "high_losses_n": n,
        "counterpress_n": len(counter_press_regains),
        "shot_n": shot_n,
        "shot_pct": round(shot_n / n * 100) if n else 0,
    }
    return _uri(fig), kpis


def _bars(labels: list[str], values: list[float], color: str, total: int | None = None) -> str:
    fig, ax=plt.subplots(figsize=(11.0,4.6),facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.14,right=0.96,top=0.96,bottom=0.1)
    ax.set_facecolor(palette.PAPER)
    order=np.argsort(values)
    lbls, vals = np.array(labels)[order], np.array(values)[order]
    ax.barh(lbls, vals, color=color, alpha=.9, height=0.68, zorder=2)
    vmax = float(vals.max()) or 1.0
    for i, v in enumerate(vals):
        text = f"{int(v)}" if not total else f"{int(v)}  ({v / total * 100:.0f}%)"
        ax.text(v + vmax * 0.02, i, text, va="center", ha="left", fontsize=11, fontweight="bold", color=palette.INK)
    ax.set_xlim(0, vmax * 1.3 if total else vmax * 1.15)
    ax.spines[:].set_visible(False); ax.grid(axis="x",color=palette.HAIR,alpha=.55, zorder=1)
    ax.set_xticks([])
    ax.tick_params(labelsize=11, colors=palette.INK, length=0)
    ax.set_axisbelow(True)
    return _uri_fixed(fig)


# Exact colors sampled from the reference PDF's own vector-drawn bars
# (recovery/reference/verified_original page 10, page.get_drawings() fill
# values) -- Open play and Second ball already match existing palette
# constants exactly; Set piece and Transition are new to this chart.
_CHANCE_SOURCE_COLORS = {
    "Set piece": "#C0892D",
    "Transition": "#6D3F83",
    "Open play": palette.SUCCESS_GREEN,
    "Second ball": palette.OPPONENT_GREY_LIGHT,
}


def _chance_source_stacked(chances: pd.DataFrame, charlton: str, opponent: str) -> tuple[str, dict[str, Any]]:
    """100%-stacked non-penalty-xG-by-source bar per team, matching the
    reference's page 10 panel exactly -- a deliberately different design
    from chart.chance_source_bars' grouped bars, which that function's own
    docstring explains is the right call for the *canonical* one-page
    report but not for this one (see chart.py:149-162)."""
    phases = list(chances.index)  # Set piece, Transition, Open play, Second ball (bottom to top)
    fig, ax = plt.subplots(figsize=(4.4, 5.6), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.98, bottom=0.08)
    ax.set_facecolor(palette.PAPER)
    teams = [charlton, opponent]
    totals = {team: float(chances[team].sum()) for team in teams}
    bottoms = {team: 0.0 for team in teams}
    for phase in phases:
        color = _CHANCE_SOURCE_COLORS[phase]
        for xi, team in enumerate(teams):
            value = float(chances.at[phase, team])
            total = totals[team] or 1.0
            share_pct = value / total * 100
            ax.bar(xi, share_pct, bottom=bottoms[team], color=color, width=0.66, zorder=2)
            if share_pct > 4:
                ax.text(xi, bottoms[team] + share_pct / 2, f"{share_pct:.0f}%\n{value:.2f}",
                        ha="center", va="center", fontsize=9, fontweight="bold", color="white")
            bottoms[team] += share_pct
    ax.set_xticks([0, 1]); ax.set_xticklabels([t.replace(" ", "\n") for t in teams], fontsize=10.5, fontweight="bold")
    ax.set_ylim(0, 100); ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.tick_params(labelsize=9, colors=palette.MUTED)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylabel("Share of non-penalty xG (%)", fontsize=9, color=palette.MUTED)

    top_source = {team: chances[team].idxmax() for team in teams}
    kpis = {
        "charlton_top_source": top_source[charlton],
        "opponent_top_source": top_source[opponent],
        "charlton_total": round(totals[charlton], 2),
        "opponent_total": round(totals[opponent], 2),
    }
    return _uri(fig), kpis


_CONTROL_ACTION_TYPES = {"LOOSE_BALL_REGAIN", "INTERCEPTION", "GK_CATCH", "RECEPTION"}


def _post_duel_control(events: pd.DataFrame, duels: pd.DataFrame, duel_type: str,
                       window_s: float = 5.0) -> pd.DataFrame:
    """Attach the team that establishes control after each duel contest.

    IMPECT records the contest and its headed action as adjacent events.  A
    successful headed pass or an immediate headed shot is already a resolved
    continuation.  Failed/neutral headers are followed for at most
    ``window_s`` seconds, within the same period, until an explicit control
    action appears.  Unresolved contests remain null rather than being
    silently assigned to the official duel winner.
    """
    out = duels.copy()
    out["control_team"] = pd.NA
    out["control_resolved"] = False
    out["team_controlled"] = pd.NA
    contest_ids = out.loc[out["duel_type"] == duel_type, "eventId"].dropna().unique()
    if not len(contest_ids):
        return out

    ordered = (
        events[["eventId", "eventNumber", "periodId", "gameTimeInSec", "squadName",
                "actionType", "action", "result"]]
        .drop_duplicates("eventId")
        .sort_values("eventNumber")
    )
    controls: dict[object, str] = {}
    for event_id in contest_ids:
        contest = ordered.loc[ordered["eventId"] == event_id]
        if contest.empty:
            continue
        row = contest.iloc[0]
        candidates = ordered.loc[
            (ordered["periodId"] == row["periodId"])
            & (ordered["eventNumber"] > row["eventNumber"])
            & (pd.to_numeric(ordered["gameTimeInSec"], errors="coerce")
               <= float(row["gameTimeInSec"]) + window_s)
            & ordered["squadName"].notna()
        ]
        control_team: str | None = None
        for candidate in candidates.itertuples(index=False):
            action_type = str(candidate.actionType)
            action = str(candidate.action)
            result = str(candidate.result)
            is_header = action == "HEADER"
            if action_type == "SHOT" and is_header:
                control_team = str(candidate.squadName)
                break
            if action_type == "PASS" and is_header and result == "SUCCESS":
                control_team = str(candidate.squadName)
                break
            if action_type in _CONTROL_ACTION_TYPES:
                control_team = str(candidate.squadName)
                break
            if action_type == "SHOT" or (
                action_type in {"PASS", "DRIBBLE"} and result == "SUCCESS"
            ):
                control_team = str(candidate.squadName)
                break
        if control_team is not None:
            controls[event_id] = control_team

    mapped = out["eventId"].map(controls)
    resolved = mapped.notna() & out["duel_type"].eq(duel_type)
    out.loc[resolved, "control_team"] = mapped.loc[resolved]
    out.loc[resolved, "control_resolved"] = True
    out.loc[resolved, "team_controlled"] = (
        out.loc[resolved, "squadName"] == mapped.loc[resolved]
    ).astype(bool)
    return out


def _duel_bars_by_type(duels: pd.DataFrame, charlton: str, opponent: str, duel_type: str,
                       events: pd.DataFrame | None = None) -> str:
    """Mirrored won/lost duel bars, top-5-by-involvement, one panel per team
    -- the reference's page 13 layout (confirmed against the actual PDF).
    The previous template rendered the *same* single-team chart twice.
    ``duels`` is impect_cafcdb_source.load_duel_involvement's output -- a
    per-player-per-event outcome, not team_stats' per-team sum, because the
    *loser* of a duel is only recorded on a second entry in that event's own
    KPI array, keyed by the loser's own playerId (see that function's
    docstring)."""
    has_control = events is not None
    if has_control:
        duels = _post_duel_control(events, duels, duel_type)
    d = duels.loc[duels["duel_type"] == duel_type]

    def top5(team: str) -> pd.DataFrame:
        t = d.loc[d["squadName"] == team]
        agg = t.groupby("playerName", dropna=True)["outcome"].value_counts().unstack(fill_value=0)
        agg = agg.rename(columns={"WON": "won", "LOST": "lost"})
        for c in ("won", "lost"):
            if c not in agg: agg[c] = 0
        agg["surname"] = [str(n).split()[-1] for n in agg.index]
        agg["involvement"] = agg["won"] + agg["lost"]
        if has_control:
            for outcome, prefix in (("WON", "won"), ("LOST", "lost")):
                outcome_rows = t.loc[t["outcome"] == outcome]
                controlled = outcome_rows.loc[
                    outcome_rows["team_controlled"].eq(True).fillna(False)  # noqa: E712
                ].groupby("playerName").size()
                not_controlled = outcome_rows.loc[
                    outcome_rows["team_controlled"].eq(False).fillna(False)  # noqa: E712
                ].groupby("playerName").size()
                agg[f"{prefix}_controlled"] = controlled.reindex(agg.index, fill_value=0)
                agg[f"{prefix}_not_controlled"] = not_controlled.reindex(agg.index, fill_value=0)
                agg[f"{prefix}_unknown"] = (
                    agg[prefix] - agg[f"{prefix}_controlled"] - agg[f"{prefix}_not_controlled"]
                )
        return agg.loc[agg["involvement"] > 0].sort_values("involvement", ascending=False).head(5)

    team_label = lambda t: str(t).split()[0]
    c, o = top5(charlton), top5(opponent)
    # Fixed 15-either-side scale, matching the reference's own axis exactly
    # (recovery/reference/verified_original page 13) rather than a
    # data-driven max -- both duel-type panels on that page share one scale.
    x_max = 15.0

    fig, axes = plt.subplots(1, 2, figsize=(18.5, 5.7), facecolor=palette.PAPER)
    fig.subplots_adjust(left=0.08, right=0.93, top=0.80, bottom=0.1, wspace=0.42)
    for ax, team, frame in zip(axes, (charlton, opponent), (c, o)):
        ax.set_facecolor(palette.PAPER)
        y = np.arange(len(frame))[::-1] * 1.3
        if has_control:
            ax.barh(y, frame["won_controlled"], color=palette.SUCCESS_GREEN,
                    alpha=0.95, zorder=2, height=0.9)
            ax.barh(y, frame["won_not_controlled"], left=frame["won_controlled"],
                    color=palette.SUCCESS_GREEN, alpha=0.35, zorder=2, height=0.9)
            ax.barh(y, frame["won_unknown"], left=frame["won_controlled"] + frame["won_not_controlled"],
                    color=palette.MUTED, alpha=0.3, zorder=2, height=0.9)
            ax.barh(y, -frame["lost_unknown"], left=-(frame["lost_not_controlled"] + frame["lost_controlled"]),
                    color=palette.MUTED, alpha=0.3, zorder=2, height=0.9)
            ax.barh(y, -frame["lost_not_controlled"], color=palette.FAIL_REDGREY,
                    alpha=0.95, zorder=2, height=0.9)
            ax.barh(y, -frame["lost_controlled"], left=-frame["lost_not_controlled"],
                    color=palette.FAIL_REDGREY, alpha=0.35, zorder=2, height=0.9)
            for yi, row in zip(y, frame.itertuples()):
                segments = (
                    (row.won_controlled / 2, row.won_controlled, "white"),
                    (row.won_controlled + row.won_not_controlled / 2,
                     row.won_not_controlled, palette.INK),
                    (-row.lost_not_controlled / 2, row.lost_not_controlled, "white"),
                    (-(row.lost_not_controlled + row.lost_controlled / 2),
                     row.lost_controlled, palette.INK),
                    (row.won_controlled + row.won_not_controlled + row.won_unknown / 2,
                     row.won_unknown, palette.INK),
                    (-(row.lost_not_controlled + row.lost_controlled + row.lost_unknown / 2),
                     row.lost_unknown, palette.INK),
                )
                for x, value, color in segments:
                    if value:
                        ax.text(x, yi, str(int(value)), ha="center", va="center",
                                fontsize=10, fontweight="bold", color=color, zorder=4)
        else:
            ax.barh(y, frame["won"], color=palette.SUCCESS_GREEN, alpha=0.9, zorder=2, height=0.9)
            ax.barh(y, -frame["lost"], color=palette.FAIL_REDGREY, alpha=0.9, zorder=2, height=0.9)
        if not has_control:
            for yi, w, l in zip(y, frame["won"], frame["lost"]):
                if l: ax.text(-l - x_max * 0.035, yi, f"{int(l)}", ha="right", va="center", fontsize=11, fontweight="bold", color=palette.FAIL_REDGREY)
                if w: ax.text(w + x_max * 0.035, yi, f"{int(w)}", ha="left", va="center", fontsize=11, fontweight="bold", color=palette.SUCCESS_GREEN)
        for yi, row in zip(y, frame.itertuples()):         # won / involved at the end of each row
            ax.text(x_max * 1.05, yi, f"{int(row.won)}/{int(row.involvement)} · {row.won / row.involvement * 100:.0f}%",
                    ha="left", va="center", fontsize=11, fontweight="bold", color=palette.INK, clip_on=False)
        ax.set_yticks(y); ax.set_yticklabels(frame["surname"], fontsize=12, fontweight="bold")
        ax.set_xlim(-x_max, x_max)
        ticks = [-15, -10, -5, 0, 5, 10, 15]
        ax.set_xticks(ticks); ax.set_xticklabels([str(abs(t)) for t in ticks], fontsize=9, color=palette.MUTED)
        ax.grid(axis="x", color=palette.HAIR_SOFT, lw=0.5, zorder=1)
        ax.axvline(0, color=palette.INK, lw=1, zorder=3)
        team_all = d.loc[d["squadName"] == team]
        n_won, n_all = int((team_all["outcome"] == "WON").sum()), len(team_all)
        title = f"{team}\nDuels won: {n_won}/{n_all} ({n_won / n_all * 100 if n_all else 0:.0f}%)"
        if has_control:
            team_rows = d.loc[d["squadName"] == team]
            kept = int(team_rows["team_controlled"].eq(True).fillna(False).sum())  # noqa: E712
            conceded = int(team_rows["team_controlled"].eq(False).fillna(False).sum())  # noqa: E712
            title += (f"\nBall afterwards: {team_label(team)} {kept} · opponent {conceded} · "
                      f"unclear {len(team_rows) - kept - conceded}")
        ax.set_title(title, fontsize=13, fontweight="bold", pad=10,
                     color=palette.CHARLTON_RED if team == charlton else palette.OPPONENT_GREY)
        ax.spines[:].set_visible(False)
        ax.tick_params(length=0)
    from matplotlib.patches import Patch
    if has_control:
        handles = [
            Patch(color=palette.SUCCESS_GREEN, alpha=0.95, label="Won, control kept"),
            Patch(color=palette.SUCCESS_GREEN, alpha=0.35, label="Won, control lost"),
            Patch(color=palette.FAIL_REDGREY, alpha=0.35, label="Lost, control recovered"),
            Patch(color=palette.FAIL_REDGREY, alpha=0.95, label="Lost, control conceded"),
            Patch(color=palette.MUTED, alpha=0.3, label="Unclear (nothing followed within 5s)"),
        ]
        columns = 5
    else:
        handles = [Patch(color=palette.SUCCESS_GREEN, label="Won"), Patch(color=palette.FAIL_REDGREY, label="Lost")]
        columns = 2
    fig.legend(handles=handles, loc="lower center", ncol=columns, frameon=False, fontsize=10,
               bbox_to_anchor=(0.5, 0.005))
    return _uri_fixed(fig)


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
    width = 2 * np.pi / n * 0.96
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

    inner_radius = 0.6  # near-zero: a full pie from the centre, not a donut
    fig, ax = plt.subplots(figsize=(6.6, 6.6), subplot_kw={"projection": "polar"}, facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER); ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
    ax.bar(theta, [100 - inner_radius] * n, bottom=inner_radius, width=width, color=bg_colors, alpha=1.0, zorder=1,
           edgecolor=palette.PAPER, linewidth=1.2)
    ax.bar(theta, [max(0.0, p - inner_radius) for p in pcts], bottom=inner_radius, width=width, color=colors,
           alpha=1.0, zorder=2, edgecolor=palette.PAPER, linewidth=1.2)
    for t, p in zip(theta, pcts):
        # Small values read better labelled just outside their short wedge,
        # in dark text on the pale background; larger ones sit inside the
        # wedge itself, in white, matching the plain-text (no pill) style.
        if p >= 25:
            label_r, color = p * 0.8, "white"
        else:
            label_r, color = p + 7, palette.INK
        ax.text(t, label_r, f"{p:.0f}", ha="center", va="center", fontsize=7, fontweight="bold",
                 color=color, zorder=3)
    ax.set_ylim(0, 112)
    ax.set_xticks(theta); ax.set_xticklabels(labels, fontsize=8.2, fontweight="bold", color=palette.INK)
    ax.tick_params(axis="x", pad=10)
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


def _xg_race(events: pd.DataFrame, teams: list[str], figsize=(16.0, 3.5), font: float = 10.5) -> str:
    """Cumulative non-penalty xG step chart. X-axis ticks match the Match
    Flow / Territory chart directly above it on the same page (0'/15'/30'/HT/
    60'/75'/90', chart_dvms.territory_chart's own convention), not
    matplotlib's default 0/20/40/60/80 -- the reference's two charts on this
    page share one axis convention."""
    fig,ax=plt.subplots(figsize=figsize,facecolor=palette.PAPER)    # same type scale as the match-flow chart
    fig.subplots_adjust(left=0.07 if figsize[0]>8 else 0.15,right=0.99,top=0.96,bottom=0.15 if figsize[1]>2.5 else 0.17)
    ax.set_facecolor(palette.PAPER)
    cum_by_team = {}
    for team,color in zip(teams,[palette.CHARLTON_RED,palette.OPPONENT_GREY]):
        s=metrics.shot_events(events); s=s.loc[s["squadName"]==team].copy()
        s["minute"]=s["gameTime"].map(metrics.minute_num); s=s.sort_values("minute")
        s["cum"]=s["SHOT_XG"].cumsum()
        cum_by_team[team]=s
        x=[0]+s["minute"].tolist()+[overview_mod.X_AXIS_MAX]; y=[0]+s["cum"].tolist(); y=y+[y[-1]]
        ax.step(x,y,where="post",label=team,color=color,lw=2)
    goals = events.loc[events["action"] == "GOAL"].sort_values("gameTimeInSec")
    last_minute, raised = -99.0, False
    for _, g in goals.iterrows():
        s = cum_by_team.get(str(g["squadName"]))
        if s is None or s.empty:
            continue
        g_minute = metrics.minute_num(str(g["gameTime"]))
        prior = s.loc[s["minute"] <= g_minute]
        y_at = float(prior.iloc[-1]["cum"]) if not prior.empty else 0.0
        ax.scatter([g_minute], [y_at], s=42 * font / 10.5, color=palette.INK, zorder=5,
                   edgecolors=palette.PAPER, linewidth=0.8)
        raised = (not raised) if g_minute - last_minute < 8 else False      # stagger labels of goals close together
        last_minute = g_minute
        ax.annotate(str(g["playerName"]).split()[-1], (g_minute, y_at), xytext=(0, 7 + (8 if raised else 0)), textcoords="offset points",
                    fontsize=font, fontweight="bold", color=palette.INK, ha="center", zorder=5)
    ax.set_xlim(0,overview_mod.X_AXIS_MAX); ax.spines[["top","right"]].set_visible(False); ax.grid(color=palette.HAIR_SOFT,lw=.6)
    ax.set_xticks(overview_mod.X_AXIS_TICKS)
    ax.set_xticklabels(overview_mod.X_AXIS_LABELS)
    ax.set_ylabel("Cumulative\nnon-penalty xG" if figsize[1] > 2.5 else "Cumulative xG", fontsize=font, color=palette.MUTED, linespacing=1.4)
    ax.tick_params(labelsize=font,colors=palette.MUTED); ax.legend(frameon=False,fontsize=font,loc="upper left")
    return _uri_fixed(fig)


def _threat_density_maps(events: pd.DataFrame, teams: list[str]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Smoothed threat-density heatmaps, one per team, on the same horizontal
    pitch and the *same* colour scale so the two can be compared directly.
    Returns ``({team: image}, {team: {"pxt", "actions"}})`` with the summary
    numbers the panel is captioned with ('X positive PXT Attack, Y actions')."""
    pitch_obj = Pitch(pad_top=1, pad_bottom=1, pad_left=1, pad_right=1, **_heatmap_pitch_kwargs())
    stats, kpis = {}, {}
    for team in teams:
        t = events.loc[(events["squadName"] == team) & events["PXT_ATTACK"].notna() & (events["PXT_ATTACK"] > 0)]
        x, y = pitch._to_pitch(t["startAdjCoordinatesX"], t["startAdjCoordinatesY"])
        bin_stat = pitch_obj.bin_statistic(x, y, values=t["PXT_ATTACK"], statistic="sum", bins=(34, 24))
        bin_stat["statistic"] = gaussian_filter(bin_stat["statistic"], 1.8)
        stats[team] = bin_stat
        kpis[team] = {"pxt": f"{float(t['PXT_ATTACK'].sum()):.2f}", "actions": int(len(t))}
    vmax = max([1e-9] + [float(b["statistic"].max()) for b in stats.values()])
    images = {}
    for team, bin_stat in stats.items():
        fig, ax = pitch_obj.draw(figsize=(3.4, 2.27))        # half-page panel size
        fig.set_facecolor(palette.PAPER_2)
        pitch_obj.heatmap(bin_stat, ax=ax, cmap=_THERMAL_CMAP, edgecolors="none", alpha=0.92,
                          norm=PowerNorm(0.6, vmin=0, vmax=vmax), zorder=1)
        images[team] = _uri(fig)
    return images, kpis


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


def _starters_only_network(net: "metrics.PassingNetwork", events: pd.DataFrame, team: str) -> "metrics.PassingNetwork":
    """Reference page 5's caption reads 'starting XI · shared match scales' —
    the eleven who began the game, not the whole squad that touched the ball.
    Also computes a real per-edge 'pxt' column (net PXT_ATTACK summed over
    every completed pass between that pair, either direction) so the local
    passing-network chart's edges actually colour by pair threat instead of
    rendering at the diverging scale's flat neutral midpoint -- the previous
    version left this as a documented placeholder (edges["pxt"] = 0.0)."""
    starter_names = set(net.nodes.loc[net.nodes["is_starter"], "playerName"])
    nodes = net.nodes.loc[net.nodes["playerName"].isin(starter_names)].copy()
    nodes["surname"] = nodes["playerName"].map(_initials)
    edges = net.edges.loc[net.edges["a"].isin(starter_names) & net.edges["b"].isin(starter_names)].copy()
    if not edges.empty:
        passes = events.loc[
            (events["squadName"] == team) & (events["actionType"] == "PASS") & (events["result"] == "SUCCESS")
            & events["playerName"].notna() & (events["playerName"] != "nan")
            & events["passReceiverPlayerName"].notna() & (events["passReceiverPlayerName"] != "nan")
        ]
        pair_key = [tuple(sorted((a, b))) for a, b in zip(passes["playerName"], passes["passReceiverPlayerName"])]
        pxt_by_pair = passes.assign(_pair=pair_key).groupby("_pair")["PXT_ATTACK"].sum()
        edges["pxt"] = [pxt_by_pair.get(tuple(sorted((a, b))), 0.0) for a, b in zip(edges["a"], edges["b"])]
    return metrics.PassingNetwork(nodes, edges, net.first_sub_minute, net.total_passes)


def _flow_timeline(events: pd.DataFrame, dvms_match, subject: str, opponent: str,
                   figsize=(16.0, 3.9), font: float = 10.5) -> str:
    """Territory flow (tracking) or Impect momentum (fallback), for the overview's match-flow panel."""
    wave=None
    if dvms_match is not None:
        from src.report import metrics_dvms
        try:
            wave=metrics_dvms.territory_wave(dvms_match)
            if wave.empty:
                wave=None
        except Exception:
            wave=None
    if wave is not None:
        return overview_mod.flow_timeline_chart(wave["minute"],wave["territory_m"],
                                                y_label="Territory (m from halfway)" if figsize[1] > 2.5 else "Territory (m)",
                                                figsize=figsize, font=font)
    momentum=metrics.momentum(events,subject,opponent)
    return overview_mod.flow_timeline_chart(momentum["minute"],momentum["momentum"],y_label="Net threat (rolling)",
                                            figsize=figsize,font=font)


def _match_timeline(events: pd.DataFrame, timeline_by_team, subject: str, opponent: str) -> str:
    """Goals, cards and substitutions of both teams on one strip."""
    if timeline_by_team is None:      # no DVMS team sheet: use the Impect-inferred goals, cards and subs
        found=metrics.timeline(events,str(events["homeSquadName"].iloc[0]),str(events["awaySquadName"].iloc[0]))
        timeline_by_team=[(team,team==subject,[{"minute":e.minute,"kind":e.kind,"player":e.label}
                                               for e in found if e.team==team]) for team in (subject,opponent)]
    return overview_mod.timeline_chart(timeline_by_team)



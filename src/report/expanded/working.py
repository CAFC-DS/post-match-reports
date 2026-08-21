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

from src.report import impect_cafcdb_source, metrics, palette, pitch
from src.report.render_combined import build_context as build_shared_context
from src.report.expanded import season_baseline as sb

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


def _bars(labels: list[str], values: list[float], color: str) -> str:
    fig, ax=plt.subplots(figsize=(8.4,4.2),facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER)
    order=np.argsort(values)
    ax.barh(np.array(labels)[order],np.array(values)[order],color=color,alpha=.88)
    ax.spines[:].set_visible(False); ax.grid(axis="x",color=palette.HAIR,alpha=.55)
    ax.tick_params(labelsize=8,colors=palette.INK); ax.set_axisbelow(True)
    return _uri(fig)


def _performance_wheel(match_values: dict[str, float], baseline: pd.DataFrame) -> str:
    """Percentile-vs-season wheel: each wedge is this match's percentile rank
    of that metric within Charlton's 25/26 season distribution, coloured by
    Attacking / Possession-Progression / Defending."""
    metrics_list = _PERFORMANCE_WHEEL_METRICS
    n = len(metrics_list)
    theta = np.linspace(0, 2 * np.pi, n, endpoint=False)
    width = 2 * np.pi / n * 0.86
    pcts, colors, labels = [], [], []
    for category, col, label, higher_is_better in metrics_list:
        value = match_values[col]
        pct = sb.percentile_of(baseline, col, value)
        if not higher_is_better:
            pct = 100 - pct
        pcts.append(pct)
        colors.append(_WHEEL_COLORS[category])
        labels.append(label)

    fig, ax = plt.subplots(figsize=(6.6, 6.6), subplot_kw={"projection": "polar"}, facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER); ax.set_theta_offset(np.pi / 2); ax.set_theta_direction(-1)
    ax.bar(theta, [100] * n, width=width, color=palette.OPPONENT_GREY, alpha=0.35, zorder=1)
    bars = ax.bar(theta, pcts, width=width, color=colors, alpha=0.92, zorder=2)
    for t, p, c in zip(theta, pcts, colors):
        ax.text(t, min(p, 100) + 6, f"{p:.0f}", ha="center", va="center", fontsize=6.5, fontweight="bold", color=palette.INK, zorder=3)
    ax.set_ylim(0, 108)
    ax.set_xticks(theta); ax.set_xticklabels(labels, fontsize=6)
    ax.set_yticklabels([]); ax.grid(color=palette.HAIR, lw=0.5)
    ax.spines["polar"].set_color(palette.HAIR)
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
    fig,ax=plt.subplots(figsize=(11.5,3.8),facecolor=palette.PAPER)
    ax.set_facecolor(palette.PAPER)
    for team,color in zip(teams,[palette.CHARLTON_RED,palette.OPPONENT_GREY]):
        s=metrics.shot_events(events); s=s.loc[s["squadName"]==team].copy()
        s["minute"]=s["gameTime"].map(metrics.minute_num); s=s.sort_values("minute")
        x=[0]+s["minute"].tolist()+[95]; y=[0]+s["SHOT_XG"].cumsum().tolist(); y=y+[y[-1]]
        ax.step(x,y,where="post",label=team,color=color,lw=2)
    ax.set_xlim(0,95); ax.spines[["top","right"]].set_visible(False); ax.grid(color=palette.HAIR_SOFT,lw=.6)
    ax.tick_params(labelsize=7,colors=palette.MUTED); ax.legend(frameon=False,fontsize=7,loc="upper left")
    return _uri(fig)


def _threat_heatmap(events: pd.DataFrame, team: str) -> str:
    t=events.loc[(events["squadName"]==team)&(events["PXT_ATTACK"]>0)]
    fig,ax=plt.subplots(figsize=(5.2,6.5),facecolor=palette.PAPER)
    ax.hist2d(t["startAdjCoordinatesY"],t["startAdjCoordinatesX"],bins=(10,14),weights=t["PXT_ATTACK"],cmap="Spectral_r")
    ax.set_xlim(-34,34); ax.set_ylim(-52.5,52.5); ax.set_aspect("equal"); ax.axis("off")
    return _uri(fig)


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
    the eleven who began the game, not the whole squad that touched the ball."""
    starter_names = set(net.nodes.loc[net.nodes["is_starter"], "playerName"])
    nodes = net.nodes.loc[net.nodes["playerName"].isin(starter_names)].copy()
    nodes["surname"] = nodes["playerName"].map(_initials)
    edges = net.edges.loc[net.edges["a"].isin(starter_names) & net.edges["b"].isin(starter_names)].copy()
    return metrics.PassingNetwork(nodes, edges, net.first_sub_minute, net.total_passes)


def _transition_speed_mps(events: pd.DataFrame, team: str) -> float:
    """Mean forward ground gained per second of elapsed time across the
    team's ATTACKING_TRANSITION-phase passes/dribbles -- 'how fast the team
    moved the ball upfield in transition', the reconstructed reading of the
    reference's 'm/s of ball progress' footer stat (no surviving formula, so
    this is a documented best-effort definition, not a recovered original)."""
    t = events.loc[
        (events["squadName"] == team) & (events["phase"] == "ATTACKING_TRANSITION")
        & events["actionType"].isin(["PASS", "DRIBBLE"]) & (events["result"] == "SUCCESS")
    ].sort_values("gameTimeInSec")
    if t.empty:
        return 0.0
    gained = (pd.to_numeric(t["endAdjCoordinatesX"], errors="coerce")
              - pd.to_numeric(t["startAdjCoordinatesX"], errors="coerce")).clip(lower=0)
    dt_s = t["gameTimeInSec"].diff().clip(upper=15).fillna(1.0).clip(lower=0.5)
    return float((gained / dt_s).mean())


def build_context(impect_match_id: int, dvms_match_id: str | None = None) -> dict[str, Any]:
    context=build_shared_context(impect_match_id,dvms_match_id)
    events=impect_cafcdb_source.load_match_events(impect_match_id)
    events=_infer_pass_receivers(events)
    subject=context["meta"]["charlton_team"]
    opponent=context["meta"]["opponent_team"]
    teams=[subject,opponent]
    side_by_team={s["team"]:s for s in context["sides"]}
    colors={subject:palette.CHARLTON_RED,opponent:palette.OPPONENT_GREY}
    nets={team:_starters_only_network(metrics.passing_network(events,team)) for team in teams}
    mx=max([int(n.edges["passes"].max()) for n in nets.values() if len(n.edges)] or [1])
    mt=max([float(n.nodes["threat"].abs().max()) for n in nets.values() if len(n.nodes)] or [.001])
    networks={team:pitch.passing_network_map(nets[team],palette.MUTED,mx,mt) for team in teams}
    flag=lambda name: pd.to_numeric(events[name],errors="coerce").fillna(0) if name in events else pd.Series(0,index=events.index)
    defensive_actions=events["action"].isin(["DUEL","INTERCEPTION","BLOCK","FOUL","CLEARANCE"])
    pressures=events.loc[(events["squadName"]==subject) & defensive_actions]
    ground=events.loc[(events["squadName"]==subject) & ((flag("WON_GROUND_DUELS")==1)|(events["action"]=="DUEL"))]
    aerial=events.loc[(events["squadName"]==subject) & ((flag("WON_AERIAL_DUELS")==1)|(events["action"]=="HEADER"))]
    regains=events.loc[(events["squadName"]==subject) & (flag("BALL_WIN_NUMBER")==1)]
    second=events.loc[(events["squadName"]==subject) & ((flag("SECOND_BALL_WIN")==1)|(flag("SECOND_BALL_LOSS")==1))]
    losses=events.loc[(events["squadName"]==subject) & (events["result"]!="SUCCESS") & events["actionType"].isin(["PASS","DRIBBLE"])]
    players=events.loc[events["squadName"]==subject].groupby("playerName",dropna=True).agg(
        ground=("WON_GROUND_DUELS","sum"),aerial=("WON_AERIAL_DUELS","sum"),wins=("BALL_WIN_NUMBER","sum")
    ).sort_values(["ground","aerial"],ascending=False).head(12)

    home,away=context["meta"]["home_team"],context["meta"]["away_team"]
    team_stats=metrics.team_stats(events,home,away)
    baseline=sb.build_season_baseline(charlton=subject)
    baseline_row=baseline.mean(numeric_only=True)
    stat_rows_expanded=_stat_rows_expanded(team_stats,baseline_row,home,away,subject)
    charlton_match_values={col:float(team_stats.loc[subject,col]) if col in team_stats.columns else
                            (float(events.loc[events["squadName"]==subject,"PXT_ATTACK"].sum()) if col=="packing_xt" else 0.0)
                            for _,col,_,_ in _PERFORMANCE_WHEEL_METRICS}
    # progressive_actions/passes_into_final_third/pressing_intensity/counter_press_regains
    # aren't team_stats columns -- reuse season_baseline's own per-match metric
    # builder so match-day and season-distribution values share one definition.
    charlton_match_values.update(
        {k: v for k, v in sb._match_metrics(events, subject, opponent).items()
         if k in {"progressive_actions", "passes_into_final_third", "pressing_intensity", "counter_press_regains", "packing_xt"}}
    )
    speed_subject=_transition_speed_mps(events,subject)
    speed_opponent=_transition_speed_mps(events,opponent)
    context.update({
        "generated_date":dt.date.today().strftime("%d %B %Y"),
        "subject":subject,"opponent":opponent,"team_order":teams,"side_by_team":side_by_team,
        "network":networks,
        "stat_rows_expanded":stat_rows_expanded,
        "performance_img":_performance_wheel(charlton_match_values,baseline),
        "match_highlights":_match_highlights(charlton_match_values,baseline,subject,opponent,speed_subject,speed_opponent),
        "xg_race_img":_xg_race(events,teams),
        "threat_img":_threat_heatmap(events,subject),
        "pressure_img":_event_map(pressures,colors[subject]),
        "ground_duel_img":_event_map(ground,colors[subject]),
        "aerial_duel_img":_event_map(aerial,colors[subject]),
        "regain_img":_event_map(regains,colors[subject]),
        "second_ball_img":_event_map(second,palette.SUCCESS_GREEN),
        "transition_img":_event_map(losses,colors[subject]),
        "duel_player_img":_bars([str(x).split()[-1] for x in players.index],(players.ground+players.aerial).tolist(),colors[subject]),
        "recovery_player_img":_bars([str(x).split()[-1] for x in players.index],players.wins.tolist(),palette.SUCCESS_GREEN),
        "event_counts":{"pressures":len(pressures),"regains":len(regains),"second_balls":len(second),"losses":len(losses)},
        "big_chances":{
            team:[{"minute":str(r.gameTime).split(':')[0]+"'","player":str(r.playerName).split()[-1],"xg":float(r.SHOT_XG),"result":str(r.result)} for r in metrics.shot_events(events).loc[lambda x:x.squadName==team].nlargest(5,"SHOT_XG").itertuples()]
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

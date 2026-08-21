"""Assemble the expanded Charlton analyst post-match report (HTML + PDF).

Same data sourcing as render_combined.py (Impect for match stats/shots/
threat/pressure/duels/conceded, DVMS tracking for momentum/average
positions/transition shape) -- see that module's docstring for the
per-panel rationale, which is unchanged here.

What's different: a section title/divider sheet precedes each of the four
sections, and the two sections that were visibly cramped onto one sheet
(In Possession, Out of Possession) are split across two sheets each so
their panels can run at a larger size. Overview and Transition weren't
cramped, so they keep their original single-sheet layout untouched.

Reuses render_combined.py's fixture-matching, headline callouts, and
Transition-section builder unchanged (nothing about that content changes),
and render.py's Impect-only helpers via render_combined re-exports. Only
the In Possession and Out of Possession builders are forked, so the panels
that move to their own sheet can be regenerated at a size that uses the
freed space instead of being stuck at the old shared-sheet figsize.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.db.query_runner import QueryRunner
from src.dvms.loaders.fixtures import resolve_fixture
from src.report import chart, chart_dvms, metrics_dvms, palette, pitch
from src.report import render as r
from src.report import render_combined as rc
from src.report.metrics import baseline as bl
from src.report.metrics import in_possession as ip
from src.report.metrics import out_of_possession as oop
from src.report.metrics import overview as ov
from src.report.metrics import player_data as pdm
from src.report.metrics import shared
from src.report.metrics import transition as tr
from src.report.render import DATA_DIR, DEFAULT_OUTPUT_DIR, _render_pdf_via_chrome
from src.visualisation.badges import badge_data_uri

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _build_page2a_network(events: pd.DataFrame, charlton: str, opponent: str) -> dict[str, Any]:
    """Separate starting-XI networks rendered with genuinely shared scales."""
    nets = {
        charlton: rc._starters_only_network(ip.passing_network(events, charlton)),
        opponent: rc._starters_only_network(ip.passing_network(events, opponent)),
    }
    max_edge = max([int(n.edges["passes"].max()) for n in nets.values() if len(n.edges)] or [1])
    max_node_passes = max([int(n.nodes["passes"].max()) for n in nets.values() if len(n.nodes)] or [1])
    max_abs_threat = max([float(n.nodes["threat"].abs().max()) for n in nets.values() if len(n.nodes)] or [0.0])
    max_abs_edge_pxt = max([float(n.edges["pxt"].abs().max()) for n in nets.values() if len(n.edges)] or [0.0])

    def draw(team: str, colour: str) -> str:
        return pitch.passing_network_map(
            nets[team], colour, max_edge, max_abs_threat,
            vertical=False, figsize=pitch._pitch_figsize(14.5, vertical=False),
            max_abs_edge_pxt=max_abs_edge_pxt, max_node_passes=max_node_passes,
        )

    return {
        "network_charlton_img": draw(charlton, palette.CHARLTON_RED),
        "network_opponent_img": draw(opponent, palette.OPPONENT_GREY),
        "network_scale_passes": max_edge,
        "network_scale_pxt": round(max_abs_edge_pxt, 2),
        "network_scale_threat": round(max_abs_threat, 2),
    }


def _build_page2b_avg_position(match, charlton: str, opponent: str,
                                team_to_side: dict[str, str]) -> dict[str, Any]:
    """Four isolated, like-for-like starting-XI phase maps."""
    side = team_to_side[charlton]
    opponent_side = "away" if side == "home" else "home"

    avg_in = metrics_dvms.avg_position_frame(match, side, "in_possession")
    avg_out = metrics_dvms.avg_position_frame(match, side, "out_of_possession")
    opp_in = metrics_dvms.avg_position_frame(match, opponent_side, "in_possession")
    opp_out = metrics_dvms.avg_position_frame(match, opponent_side, "out_of_possession")
    avg_in = avg_in.loc[avg_in["is_starter"]]
    avg_out = avg_out.loc[avg_out["is_starter"]]
    opp_in = opp_in.loc[opp_in["is_starter"]]
    opp_out = opp_out.loc[opp_out["is_starter"]]
    line_heights = {
        "charlton_in": metrics_dvms.line_height_m(match, side, "in_possession"),
        "charlton_out": metrics_dvms.line_height_m(match, side, "out_of_possession"),
        "opponent_in": metrics_dvms.line_height_m(match, opponent_side, "in_possession"),
        "opponent_out": metrics_dvms.line_height_m(match, opponent_side, "out_of_possession"),
    }
    return {
        "avg_charlton_in_img": pitch.average_position_map(
            avg_in, palette.CHARLTON_RED, figsize=pitch._pitch_figsize(9.3),
            line_height=line_heights["charlton_in"], vertical=True),
        "avg_opponent_in_img": pitch.average_position_map(
            opp_in, palette.OPPONENT_GREY, figsize=pitch._pitch_figsize(9.3),
            line_height=line_heights["opponent_in"], vertical=True),
        "avg_charlton_out_img": pitch.average_position_map(
            avg_out, palette.CHARLTON_RED, figsize=pitch._pitch_figsize(9.3),
            line_height=line_heights["charlton_out"], vertical=True),
        "avg_opponent_out_img": pitch.average_position_map(
            opp_out, palette.OPPONENT_GREY, figsize=pitch._pitch_figsize(9.3),
            line_height=line_heights["opponent_out"], vertical=True),
        "avg_line_heights": line_heights,
    }


def _build_page2c_detail(events: pd.DataFrame, charlton: str, opponent: str) -> dict[str, Any]:
    """Spatial threat → entry routes → player attribution page."""
    entries_c = shared.hierarchical_zone_entries(events, charlton)
    charlton_events = events.loc[events["squadName"] == charlton]
    threat_density_img = pitch.xt_heatmap(charlton_events, figsize=pitch._pitch_figsize(8.6), vertical=True)
    threat_density_positive = charlton_events.loc[
        charlton_events["PXT_ATTACK"].notna() & (charlton_events["PXT_ATTACK"] > 0)
    ]
    max_entry_threat = float(entries_c["threat"].max()) if len(entries_c) else 1.0
    entries_img = pitch.entry_map(entries_c, max_entry_threat, figsize=pitch._pitch_figsize(11.0, vertical=False), vertical=False)
    player_threat = ip.player_pxt_attack(events, charlton)
    # Player Threat Ranking chart uses open-play creation (PXT_PASS +
    # PXT_DRIBBLE), not raw PXT_ATTACK -- excludes goals along with every
    # other shot outcome (2026-08 feedback), per the "Open-play creation"
    # definition already documented in DATA_MODEL.md. The JSON export above
    # (`player_pxt_attack`) is unaffected and still reports true PXT_ATTACK.
    charlton_creation = ip.player_open_play_creation(events, charlton)
    opponent_creation = ip.player_open_play_creation(events, opponent)
    charlton_creation["squadName"] = charlton
    opponent_creation["squadName"] = opponent
    both_teams_creation = pd.concat([charlton_creation, opponent_creation], ignore_index=True)
    creator_pxt_img = chart.pxt_attack_bars(both_teams_creation, charlton, top_n=10, figsize=(16.0, 3.4))
    threat_summary = ip.threat_creation_breakdown(events, charlton)

    shots = shared.shot_events(events)
    non_penalty = shots.loc[shots["action"] != "PENALTY_KICK"]
    team_shots = {team: non_penalty.loc[non_penalty["squadName"] == team]
                  for team in (charlton, opponent)}

    def summary(team: str) -> dict[str, Any]:
        s = shared.shot_summary(non_penalty, team)
        return {
            "team": team,
            **s,
            "avg_xg": float(s["xg"] / s["shots"]) if s["shots"] else 0.0,
        }

    def biggest_chances(team: str, n: int = 7) -> list[dict[str, Any]]:
        """Top-n individual shots by SHOT_XG for one team -- fills the space
        left below the Shot Map / Chance Quality row (2026-08 feedback: that
        row can't grow taller without the half-pitch Shot Maps also growing
        wider than the page, so the leftover space needed real content, not
        just padding). Reuses the same shot event data already powering the
        Shot Maps, no new metric.
        """
        d = team_shots[team].sort_values("SHOT_XG", ascending=False).head(n)
        return [
            {
                "minute": round(shared.minute_num(row["gameTime"])),
                "surname": str(row["playerName"]).split()[-1],
                "xg": round(float(row["SHOT_XG"]), 2),
                # "Other" folded into "Off target", matching shot_map's own
                # legend (Goal/On target/Blocked/Off target only).
                "category": "Off target" if row["category"] == "Other" else row["category"],
            }
            for _, row in d.iterrows()
        ]

    sources = shared.chance_sources(events, charlton, opponent)
    # KPI strip under Chance Quality by Source (2026-08 fix, makes the tile a
    # true peer of the two Shot Map cards above it, which already have a KPI
    # row) -- no new metric computation, just extracting values already in
    # `sources`.
    chance_source_kpis = {
        "charlton_top_phase": str(sources[charlton].idxmax()),
        "charlton_top_value": round(float(sources[charlton].max()), 2),
        "charlton_total": round(float(sources[charlton].sum()), 2),
        "opponent_top_phase": str(sources[opponent].idxmax()),
        "opponent_top_value": round(float(sources[opponent].max()), 2),
        "opponent_total": round(float(sources[opponent].sum()), 2),
    }

    return {
        "threat_density_img": threat_density_img,
        "entries_img": entries_img,
        "creator_pxt_img": creator_pxt_img,
        "player_pxt_attack": player_threat.to_dict("records"),
        "threat_summary": {k: round(float(v), 2) if isinstance(v, float) else v
                           for k, v in threat_summary.items()},
        "entries_n": len(entries_c),
        "entries_success": int(entries_c["success"].sum()) if len(entries_c) else 0,
        "entries_final_third": int((entries_c["entry_type"] == "final_third").sum()) if len(entries_c) else 0,
        "entries_box": int((entries_c["entry_type"] == "box").sum()) if len(entries_c) else 0,
        "threat_density_pxt": round(float(threat_density_positive["PXT_ATTACK"].sum()), 2),
        "threat_density_actions": len(threat_density_positive),
        "shot_charlton_img": pitch.shot_map(team_shots[charlton], palette.CHARLTON_RED,
                                             figsize=pitch._pitch_figsize(5.7, half=True)),
        "shot_opponent_img": pitch.shot_map(team_shots[opponent], palette.OPPONENT_GREY,
                                             figsize=pitch._pitch_figsize(5.7, half=True)),
        "chance_summaries": [summary(charlton), summary(opponent)],
        "chance_source_img": chart.chance_source_comparison(
            sources, charlton, opponent, figsize=(2.3, 3.4)),
        **chance_source_kpis,
        "biggest_chances_charlton": biggest_chances(charlton),
        "biggest_chances_opponent": biggest_chances(opponent),
    }


def _duel_chart_frame(events: pd.DataFrame, team: str) -> pd.DataFrame:
    d = oop.duel_performance(events, team)
    if d.empty:
        return pd.DataFrame(columns=["playerName", "surname", "won_AERIAL_DUEL", "lost_AERIAL_DUEL",
                                     "won_GROUND_DUEL", "lost_GROUND_DUEL"])
    out = d.pivot_table(index="playerName", columns="duel_type", values=["won", "lost"], fill_value=0)
    out.columns = [f"{a}_{b}" for a, b in out.columns]
    out = out.reset_index()
    for c in ("won_AERIAL_DUEL", "lost_AERIAL_DUEL", "won_GROUND_DUEL", "lost_GROUND_DUEL"):
        if c not in out: out[c] = 0
    out["surname"] = out["playerName"].map(lambda n: str(n).split()[-1])
    return out


def _build_page3c_player_duels(events: pd.DataFrame, charlton: str, opponent: str) -> dict[str, Any]:
    c, o = _duel_chart_frame(events, charlton), _duel_chart_frame(events, opponent)
    vals = pd.concat([c.filter(regex="^(won|lost)_"), o.filter(regex="^(won|lost)_")], ignore_index=True)
    x_max = max(float(vals.max().max()) if len(vals) else 1.0, 1.0)
    # Two full-width charts (one per duel type), not one 2x2 grid (2026-08
    # feedback: squashed player names/bars) -- shared x_max keeps both on
    # the same scale.
    return {
        "duel_aerial_bars_img": chart.duel_bars_by_type(
            c, o, charlton, opponent, "AERIAL DUELS", "won_AERIAL_DUEL", "lost_AERIAL_DUEL",
            x_max=x_max, top_n=5, figsize=(14.0, 4.4)),
        "duel_ground_bars_img": chart.duel_bars_by_type(
            c, o, charlton, opponent, "GROUND DUELS", "won_GROUND_DUEL", "lost_GROUND_DUEL",
            x_max=x_max, top_n=5, figsize=(14.0, 4.4)),
    }


def _section3_match_summary(events: pd.DataFrame, team: str, opponent: str) -> dict[str, float]:
    """One authoritative match row for all selected Section 3 baselines."""
    pressures = oop.pressures_in_team_frame(oop.pressure_zones(events, team))
    duels = oop.duel_performance(events, team)
    regains = oop.opp_half_regains_detail(events, team)
    regain_seqs = tr.regain_sequences(events, team)
    opp_half_seqs = regain_seqs.loc[regain_seqs["startAdjCoordinatesX"] > 0] if len(regain_seqs) else regain_seqs
    second = oop.second_ball_wins_detail(events, team)
    shots = shared.shot_events(events)
    opp_shots = shots.loc[(shots["squadName"] == opponent) & (shots["action"] != "PENALTY_KICK")]

    def duel_rate(kind: str) -> float:
        d = duels.loc[duels["duel_type"] == kind]
        total = float(d["total"].sum())
        return float(d["won"].sum() / total * 100) if total else 0.0

    intensity = pd.to_numeric(pressures.get("pressure", pd.Series(dtype=float)), errors="coerce")
    won_second = int(second["won"].sum()) if len(second) else 0
    sources = shared.chance_sources(events, team, opponent)[opponent]
    return {
        "pressure_n": float(len(pressures)),
        "pressure_opp_half_pct": float((pressures["startAdjCoordinatesX"] > 0).mean() * 100) if len(pressures) else 0.0,
        "pressure_opp_third_n": float((pressures["startAdjCoordinatesX"] > 17.5).sum()),
        "pressure_median_intensity": float(intensity.median()) if intensity.notna().any() else 0.0,
        "aerial_win_pct": duel_rate("AERIAL_DUEL"),
        "ground_win_pct": duel_rate("GROUND_DUEL"),
        "regains_n": float(len(regains)),
        "regain_shot_pct": float(opp_half_seqs["led_to_shot"].sum() / len(regains) * 100) if len(regains) else 0.0,
        "second_ball_win_pct": float(won_second / len(second) * 100) if len(second) else 0.0,
        "second_ball_wins": float(won_second),
        "shots_faced": float(len(opp_shots)),
        "xg_faced": float(opp_shots["SHOT_XG"].sum()),
        **{f"source_{str(name).lower().replace(' ', '_')}": float(value) for name, value in sources.items()},
    }


def _section3_baseline(season_events: pd.DataFrame, charlton: str, match_id: int,
                       n: int | None = None) -> tuple[dict[str, float], int]:
    """Prior-match Section 3 averages; the reported fixture never self-compares."""
    rows = []
    for historical_id, ev in season_events.groupby("matchId"):
        if int(historical_id) == int(match_id):
            continue
        home, away = str(ev["homeSquadName"].iloc[0]), str(ev["awaySquadName"].iloc[0])
        if charlton not in (home, away):
            continue
        opponent = away if home == charlton else home
        try:
            rows.append(_section3_match_summary(ev, charlton, opponent))
        except Exception:
            continue
    frame = pd.DataFrame(rows)
    if n:
        frame = frame.tail(n)
    return (frame.mean(numeric_only=True).to_dict() if len(frame) else {}, len(frame))


def _build_page3a_press_duels(events: pd.DataFrame, charlton: str, opponent: str,
                              section3_baseline: dict[str, float], baseline_n: int) -> dict[str, Any]:
    """Pressure Activity + Duel Performance, alone on their own sheet."""
    pressure_df = oop.pressures_in_team_frame(oop.pressure_zones(events, charlton))
    # Pressure rows belong to the opponent's on-ball action, so their adjusted
    # coordinates point in the opponent's attacking direction. Rotate them
    # into Charlton's attacking frame before plotting or deriving territory.
    pressure_img = pitch.pressure_heatmap(pressure_df, figsize=(7.0, 10.2), vertical=True)

    duel_locations = oop.duel_locations(events, charlton)
    intensity = pd.to_numeric(pressure_df["pressure"], errors="coerce")
    top_presser = pressure_df["pressingPlayerName"].value_counts()

    match_summary = _section3_match_summary(events, charlton, opponent)
    top_duels = (duel_locations.groupby("team_player").size().sort_values(ascending=False)
                 if len(duel_locations) else pd.Series(dtype=int))

    return {
        "pressure_img": pressure_img,
        "pressure_n": len(pressure_df),
        "pressure_opp_half_pct": round(float((pressure_df["startAdjCoordinatesX"] > 0).mean() * 100)) if len(pressure_df) else 0,
        "pressure_opp_third_n": int((pressure_df["startAdjCoordinatesX"] > 17.5).sum()),
        "pressure_median_intensity": round(float(intensity.median())) if intensity.notna().any() else 0,
        "pressure_top_name": top_presser.index[0].split()[-1] if len(top_presser) else "—",
        "pressure_top_n": int(top_presser.iloc[0]) if len(top_presser) else 0,
        "duel_aerial_img": pitch.duel_location_map(
            duel_locations, "AERIAL_DUEL", figsize=(5.0, 7.5)),
        "duel_ground_img": pitch.duel_location_map(
            duel_locations, "GROUND_DUEL", figsize=(5.0, 7.5)),
        "duel_top": [{"name": str(name).split()[-1], "n": int(value)}
                     for name, value in top_duels.head(3).items()],
        "duel_aerial_win_pct": round(match_summary["aerial_win_pct"]),
        "duel_ground_win_pct": round(match_summary["ground_win_pct"]),
        "duel_aerial_baseline": round(section3_baseline.get("aerial_win_pct", 0.0)),
        "duel_ground_baseline": round(section3_baseline.get("ground_win_pct", 0.0)),
        "section3_baseline_n": baseline_n,
        "pressure_baseline_n": round(section3_baseline.get("pressure_n", 0.0)),
        "pressure_baseline_half": round(section3_baseline.get("pressure_opp_half_pct", 0.0)),
        "pressure_baseline_third": round(section3_baseline.get("pressure_opp_third_n", 0.0)),
        "pressure_delta": round(len(pressure_df) - section3_baseline.get("pressure_n", 0.0)),
        "duel_aerial_delta": round(match_summary["aerial_win_pct"] - section3_baseline.get("aerial_win_pct", 0.0)),
        "duel_ground_delta": round(match_summary["ground_win_pct"] - section3_baseline.get("ground_win_pct", 0.0)),
    }


def _build_page3b_regains_conceded(events: pd.DataFrame, charlton: str, opponent: str,
                                    section3_baseline: dict[str, float],
                                    baseline_n: int) -> dict[str, Any]:
    """Large opposition-half regain and second-ball pitches."""
    regains = oop.opp_half_regains_detail(events, charlton)
    regain_seqs = tr.regain_sequences(events, charlton)
    opp_half_seqs = (regain_seqs.loc[regain_seqs["startAdjCoordinatesX"] > 0]
                     if len(regain_seqs) else regain_seqs)
    regains_led_to_shot = int(opp_half_seqs["led_to_shot"].sum()) if len(opp_half_seqs) else 0
    regains_shot_pct = round(regains_led_to_shot / len(regains) * 100) if len(regains) else 0
    shot_regain_ids = set(opp_half_seqs.loc[opp_half_seqs["led_to_shot"], "eventId"]) if len(opp_half_seqs) else set()
    regains_img = pitch.located_points_map(regains, win_col="", win_color="", lose_color="",
                                           single_color=palette.CHARLTON_RED, figsize=(8.2, 6.3), half=True,
                                           highlight_ids=shot_regain_ids, highlight_label="led to a shot within 15s")

    second_balls = oop.second_ball_wins_detail(events, charlton)
    second_ball_img = pitch.located_points_map(second_balls, win_col="won", win_color=palette.SUCCESS_GREEN,
                                               lose_color=palette.FAIL_REDGREY, figsize=(9.6, 5.8), vertical=False)
    second_ball_wins_only = second_balls.loc[second_balls["won"]] if len(second_balls) else second_balls
    second_ball_won = int(len(second_ball_wins_only))
    second_ball_win_pct = round(second_ball_won / len(second_balls) * 100) if len(second_balls) else 0

    return {
        "regains_img": regains_img,
        "regains_n": len(regains),
        "regains_baseline": round(section3_baseline.get("regains_n", 0.0), 1),
        "regains_delta": round(len(regains) - section3_baseline.get("regains_n", 0.0), 1),
        "regains_top": rc._top_n_counts(regains, "playerName"),
        "regains_led_to_shot": regains_led_to_shot,
        "regains_shot_pct": regains_shot_pct,
        "regains_shot_pct_baseline": round(section3_baseline.get("regain_shot_pct", 0.0)),
        "second_ball_img": second_ball_img,
        "second_ball_n": len(second_balls),
        "second_ball_won": second_ball_won,
        "second_ball_win_pct": second_ball_win_pct,
        "second_ball_win_pct_baseline": round(section3_baseline.get("second_ball_win_pct", 0.0)),
        "second_ball_baseline": round(section3_baseline.get("second_ball_wins", 0.0), 1),
        "second_ball_delta": round(second_ball_won - section3_baseline.get("second_ball_wins", 0.0), 1),
        "second_ball_top": rc._top_n_counts(second_ball_wins_only, "playerName"),
        "section3_baseline_n": baseline_n,
    }


def _defensive_transition_baseline(season_events: pd.DataFrame, charlton: str) -> dict[str, float]:
    rows = []
    for _, ev in season_events.groupby("matchId"):
        home, away = str(ev["homeSquadName"].iloc[0]), str(ev["awaySquadName"].iloc[0])
        if charlton not in (home, away):
            continue
        opponent = away if home == charlton else home
        try:
            losses = tr.high_turnovers_conceded(ev, charlton, opponent, window_s=15.0)
            exposed = int(losses["opponent_shot_followed"].sum()) if len(losses) else 0
            rows.append({
                "high_losses_n": len(losses),
                "counterpress_n": len(tr.counter_press_regains(ev, charlton, opponent)),
                "high_losses_led_to_shot": exposed,
                "exposure_pct": exposed / len(losses) * 100 if len(losses) else 0.0,
            })
        except Exception:
            continue
    if not rows:
        return {"high_losses_n": 0.0, "counterpress_n": 0.0,
                "high_losses_led_to_shot": 0.0, "exposure_pct": 0.0, "n": 0}
    result = pd.DataFrame(rows).mean(numeric_only=True).to_dict()
    result["n"] = len(rows)
    return result


def _build_page5a_transition_maps(events: pd.DataFrame, charlton: str, opponent: str,
                                   transition_baseline: dict[str, float]) -> dict[str, Any]:
    """One defensive-transition page answering whether Charlton controlled loss."""
    high_turnovers = tr.high_turnovers_conceded(events, charlton, opponent, window_s=15.0)
    high_turnovers_led_to_shot = int(high_turnovers["opponent_shot_followed"].sum()) if len(high_turnovers) else 0
    counterpress = tr.counter_press_regains(events, charlton, opponent)
    exposure_pct = high_turnovers_led_to_shot / len(high_turnovers) * 100 if len(high_turnovers) else 0.0

    return {
        "defensive_response_img": pitch.defensive_transition_response_map(high_turnovers, counterpress, figsize=(11.5, 7.4)),
        "high_losses_n": len(high_turnovers),
        "counterpress_n": len(counterpress),
        "high_losses_led_to_shot": high_turnovers_led_to_shot,
        "transition_exposure_pct": round(exposure_pct),
        "transition_baseline_n": int(transition_baseline.get("n", 0)),
        "high_losses_baseline": round(transition_baseline.get("high_losses_n", 0.0), 1),
        "counterpress_baseline": round(transition_baseline.get("counterpress_n", 0.0), 1),
        "high_losses_shot_baseline": round(transition_baseline.get("high_losses_led_to_shot", 0.0), 1),
        "transition_exposure_baseline": round(transition_baseline.get("exposure_pct", 0.0)),
        "high_losses_delta": round(len(high_turnovers) - transition_baseline.get("high_losses_n", 0.0), 1),
        "counterpress_delta": round(len(counterpress) - transition_baseline.get("counterpress_n", 0.0), 1),
        "high_losses_shot_delta": round(high_turnovers_led_to_shot - transition_baseline.get("high_losses_led_to_shot", 0.0), 1),
        "transition_exposure_delta": round(exposure_pct - transition_baseline.get("exposure_pct", 0.0)),
    }


def _build_page5b_transition_outcomes(events: pd.DataFrame, match, charlton: str, opponent: str,
                                       team_to_side: dict[str, str], season_events: pd.DataFrame,
                                       match_id: int) -> dict[str, Any]:
    """Transition Outcomes reworked as a Charlton-vs-opponent comparison
    (2026-08 feedback) rather than Charlton-vs-own-season-baseline only --
    every underlying tr.*/transition_progress function already takes a
    team/side parameter, so the opponent's equivalent numbers are the same
    functions called with the sides swapped. Season baseline is kept as a
    secondary reference on Charlton's own figure, where it still adds
    context a same-match opponent comparison can't.
    """
    def _team_transition_numbers(team: str, other: str) -> dict[str, float]:
        regains = tr.regain_sequences(events, team)
        cp = tr.counter_press_regains(events, team, other)
        high_losses = tr.high_turnovers_conceded(events, team, other, window_s=15.0)
        shots = shared.shot_events(events)
        t_xg = float(shots.loc[
            (shots["squadName"] == team) & (shots["phase"] == "ATTACKING_TRANSITION")
            & (shots["action"] != "PENALTY_KICK"), "SHOT_XG"
        ].sum())
        return {
            "regain_to_shot_count": int(regains["led_to_shot"].sum()) if len(regains) else 0,
            "transition_xg": t_xg,
            "counter_press_regains": len(cp),
            "high_losses_to_shot": int(high_losses["opponent_shot_followed"].sum()) if len(high_losses) else 0,
        }

    charlton_num = _team_transition_numbers(charlton, opponent)
    opponent_num = _team_transition_numbers(opponent, charlton)
    tbase = r._transition_baseline(season_events, charlton, match_id)

    labels = [
        ("regain_to_shot_count", "Regains leading to a shot (≤15s)", "{:.0f}"),
        ("transition_xg", "Transition xG", "{:.2f}"),
        ("counter_press_regains", "Counter-press regains (≤5s)", "{:.0f}"),
        ("high_losses_to_shot", "High losses → opposition shot", "{:.0f}"),
    ]

    def _share(a: float, b: float) -> tuple[float, float]:
        total = a + b
        return (50.0, 50.0) if total <= 0 else (a / total * 100, b / total * 100)

    transition_outcomes = []
    for key, label, fmt in labels:
        c_val, o_val = charlton_num[key], opponent_num[key]
        c_share, o_share = _share(c_val, o_val)
        transition_outcomes.append({
            "label": label,
            "charlton": fmt.format(c_val),
            "opponent": fmt.format(o_val),
            "charlton_share": round(c_share, 1),
            "opponent_share": round(o_share, 1),
            "baseline": fmt.format(tbase[key]),
            "shade": pdm.shade(c_val, tbase[key]),
        })

    speeds = {team: metrics_dvms.transition_progress(match, team_to_side[team])["speed_mps"]
              for team in (charlton, opponent)}

    return {
        "transition_outcomes": transition_outcomes,
        "transition_baseline_n": tbase["n"],
        "transition_speed_charlton": round(speeds[charlton], 2),
        "transition_speed_opponent": round(speeds[opponent], 2),
    }


def build_context(impect_match_id: int, dvms_opta_match_id: str, baseline_mode: str = "season_to_date",
                   baseline_n: int | None = None, refresh: bool = False, env_path: str = ".env") -> dict[str, Any]:
    events = QueryRunner().load_match_events(impect_match_id, refresh=refresh)
    meta = shared.match_meta(events)
    charlton, opponent = meta.charlton_team, meta.opponent_team
    home, away = meta.home_team, meta.away_team
    home_is_charlton = home == charlton

    dvms_fixture = resolve_fixture(dvms_opta_match_id, env_path=env_path)
    rc._assert_same_fixture(meta, dvms_fixture)
    match = metrics_dvms.load_match(dvms_fixture, env_path=env_path)

    team_to_side = {home: "home", away: "away"}
    side_to_team = {"home": home, "away": away}

    season_events = pd.read_parquet(DATA_DIR / "charlton_events.parquet")
    # One report-wide historical population.  Excluding before slicing keeps
    # last-N mode at N genuine prior matches instead of N-1 after the fact.
    baseline_events = season_events.loc[
        pd.to_numeric(season_events["matchId"], errors="coerce") != int(impect_match_id)
    ].copy()
    baseline_desc, baseline_series = bl.compute_baseline(
        baseline_events, charlton, meta.kickoff, mode=baseline_mode, n=baseline_n
    )
    eligible_ids = set(pd.to_numeric(baseline_series.get("matchId", pd.Series(dtype=float)),
                                     errors="coerce").dropna().astype(int))
    baseline_events = baseline_events.loc[
        pd.to_numeric(baseline_events["matchId"], errors="coerce").isin(eligible_ids)
    ].copy()
    historical_seasons = set(baseline_events.get("season", pd.Series(dtype=str)).dropna().astype(str))
    baseline_season = meta.season
    if meta.season not in historical_seasons and baseline_mode == "season_to_date":
        prior = "/".join(sorted(historical_seasons)) if historical_seasons else "prior season"
        baseline_desc = replace(baseline_desc, label=f"{prior} comparator (n={baseline_desc.n})")
        baseline_season = prior
    baseline_row = baseline_series.mean(numeric_only=True).to_dict()
    section3_baseline, section3_baseline_n = _section3_baseline(
        baseline_events, charlton, impect_match_id
    )
    transition_baseline = _defensive_transition_baseline(baseline_events, charlton)

    stats = ov.analyst_team_stats(events, home, away)
    goals = shared.goal_events(events)
    npxg = {
        charlton: stats.loc[charlton, "non_penalty_xg"],
        opponent: stats.loc[opponent, "non_penalty_xg"],
    }

    # ------------------------------------------------------------ page 1
    ppda_val = oop.ppda(events, charlton, opponent)
    duels_for_radar = oop.duel_performance(events, charlton)
    cp = tr.counter_press_regains(events, charlton, opponent)
    match_row = ov.radar_match_row(events, charlton, opponent, ppda_value=ppda_val,
                                    duels_won=int(duels_for_radar["won"].sum()), counter_press_regains=len(cp))
    component_series = r._season_component_series(baseline_events, charlton)
    pizza_pct = ov.pizza_percentiles(match_row, component_series)
    pizza_img = chart.pizza_chart(pizza_pct, charlton, n=len(component_series))
    headline_callouts = rc._headline_callouts(pizza_pct, charlton, opponent, match, team_to_side)

    race = ov.xg_race(events, home, away)
    xg_race_img = chart.xg_race_chart(
        race, pd.DataFrame(), goals, charlton, opponent, figsize=(11.0, 3.65), show_game_state=False
    )

    wave = metrics_dvms.territory_wave(match)
    dvms_goal_markers = metrics_dvms.goal_markers(match)
    dvms_name_to_side = {match.team_name_of(s): s for s in ("home", "away")}
    for marker in dvms_goal_markers:
        marker["team"] = side_to_team[dvms_name_to_side[marker["team"]]]
    territory_img = chart_dvms.territory_chart(wave, dvms_goal_markers, charlton, opponent,
                                                figsize=(11.0, 4.1))

    context: dict[str, Any] = {
        "generated_date": dt.date.today().strftime("%d %B %Y"),
        "meta": {
            "charlton_team": charlton,
            "opponent_team": opponent,
            "opponent_short": opponent,
            "charlton_goals": meta.charlton_goals,
            "opponent_goals": meta.opponent_goals,
            "charlton_xg": f"{npxg[charlton]:.2f}",
            "opponent_xg": f"{npxg[opponent]:.2f}",
            "charlton_badge": badge_data_uri(charlton),
            "opponent_badge": badge_data_uri(opponent),
            "home_team": home,
            "away_team": away,
            "home_short": home,
            "away_short": away,
            "home_goals": meta.home_goals,
            "away_goals": meta.away_goals,
            "home_xg": f"{npxg[home]:.2f}",
            "away_xg": f"{npxg[away]:.2f}",
            "home_badge": badge_data_uri(home),
            "away_badge": badge_data_uri(away),
            "home_is_charlton": home_is_charlton,
            "venue": "Away" if charlton == away else "Home",
            "venue_name": f"at {opponent}" if charlton == away else f"at {charlton}",
            "competition": meta.competition,
            "season": meta.season,
            "date": meta.kickoff.strftime("%d/%m/%Y"),
            "result": meta.result,
        },
        "baseline": {"label": baseline_desc.label, "n": baseline_desc.n, "mode": baseline_desc.mode,
                     "season": baseline_season},
        "stat_rows": r._stat_rows(stats, charlton, opponent, home_is_charlton, baseline_row),
        "pizza_img": pizza_img,
        "headline_callouts": headline_callouts,
        "xg_race_img": xg_race_img,
        "territory_img": territory_img,
        "match_id": impect_match_id,
        "dvms_match_id": dvms_opta_match_id,
    }
    context.update(_build_page2a_network(events, charlton, opponent))
    context.update(_build_page2b_avg_position(match, charlton, opponent, team_to_side))
    context.update(_build_page2c_detail(events, charlton, opponent))
    context.update(_build_page3a_press_duels(
        events, charlton, opponent, section3_baseline, section3_baseline_n))
    context.update(_build_page3b_regains_conceded(
        events, charlton, opponent, section3_baseline, section3_baseline_n))
    context.update(_build_page5a_transition_maps(
        events, charlton, opponent, transition_baseline))
    return context


def render_report(impect_match_id: int, dvms_opta_match_id: str, output_dir: Path | str = DEFAULT_OUTPUT_DIR,
                   formats: tuple[str, ...] = ("html", "pdf"), baseline_mode: str = "season_to_date",
                   baseline_n: int | None = None, refresh: bool = False, env_path: str = ".env") -> dict[str, Path]:
    context = build_context(impect_match_id, dvms_opta_match_id, baseline_mode=baseline_mode,
                             baseline_n=baseline_n, refresh=refresh, env_path=env_path)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("post_match_analyst_report_expanded.html.j2").render(**context)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = (f"expanded_analyst_report_{context['meta']['charlton_team']}"
            f"_v_{context['meta']['opponent_team']}_{context['meta']['date'].replace('/', '-')}").replace(" ", "_")

    outputs: dict[str, Path] = {}
    if "html" in formats:
        html_path = output_dir / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")
        outputs["html"] = html_path
    if "pdf" in formats:
        pdf_path = output_dir / f"{slug}.pdf"
        _render_pdf_via_chrome(html, outputs.get("html"), pdf_path)
        outputs["pdf"] = pdf_path
    return outputs

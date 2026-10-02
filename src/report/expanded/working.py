from __future__ import annotations

import datetime as dt
import gc
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.report import impect_cafcdb_source, metrics, palette
from src.report.render_combined import build_context as build_shared_context
from src.report.expanded import _fonts, transition as transition_mod
from src.report.expanded import season_baseline as sb
from src.report.expanded import inpossession as inpossession_mod
from src.report.expanded import bookmarks, layout_check
from src.report.expanded.browser import chrome_version, resolve_chrome
from src.report.expanded.charts import (
    _PERFORMANCE_WHEEL_METRICS, _chance_source_stacked, _duel_bars_by_type, _entries_kpis, _flow_timeline,
    _infer_pass_receivers, _local_passing_network_map, _match_timeline, _performance_wheel, _player_threat_ranking,
    _second_ball_kpis, _starters_only_network, _threat_density_maps, _xg_race,
)
from src.report.expanded import gamestate as gamestate_mod
from src.report.expanded import summary as summary_mod
from src.report.expanded import outofpossession as outofpossession_mod
from src.report.expanded import player_baseline
from src.report.expanded import shooting as shooting_mod
from src.report.expanded import overview as overview_mod
from src.report.expanded.pages import build_contents, build_page_plan, build_toc, section_info


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
        home_wins = (h > a) if higher_is_better else (h < a)
        away_wins = (a > h) if higher_is_better else (a < h)
        rows.append({
            "group": group if group != last_group else None,
            "label": label,
            "home": _fmt_expanded(key, h),
            "away": _fmt_expanded(key, a),
            "home_share": home_share,
            "away_share": round(100 - home_share, 1),
            "baseline": _fmt_expanded(key, baseline_value) if baseline_value is not None else "—",
            "shade": _shade(charlton_value, baseline_value, higher_is_better) if baseline_value is not None else None,
            # Identity-based, not home/away-based: Charlton is always red / the
            # opponent always grey in this table regardless of which side of
            # the fixture Charlton happened to be on (a fixed home_wins/red
            # mapping showed West Ham in red when West Ham were the home side).
            "home_is_charlton": home == charlton,
            "home_wins": home_wins if h != a else False,
            "away_wins": away_wins if h != a else False,
        })
        last_group = group
    return rows


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
    nets={team:_starters_only_network(metrics.passing_network(events,team),events,team) for team in teams}
    mx=max([int(n.edges["passes"].max()) for n in nets.values() if len(n.edges)] or [1])
    mt=max([float(n.nodes["threat"].abs().max()) for n in nets.values() if len(n.nodes)] or [.001])
    met=max([float(n.edges["pxt"].abs().max()) for n in nets.values() if len(n.edges)] or [.001])
    networks={team:_local_passing_network_map(nets[team],mx,mt,met) for team in teams}
    network_scale_threat=round(mt,2)
    baseline=sb.build_season_baseline(charlton=subject)
    second_balls={team:_second_ball_kpis(events,team,baseline) for team in teams}

    home,away=context["meta"]["home_team"],context["meta"]["away_team"]
    team_stats=metrics.team_stats(events,home,away)
    chances=metrics.chance_sources(events,home,away)
    chance_source_img,chance_source_kpis=_chance_source_stacked(chances,subject,opponent)
    player_threat_ranking_img,player_threat_ranking_totals=_player_threat_ranking(events,subject,opponent)
    baseline_row=baseline.mean(numeric_only=True)
    stat_rows_expanded=_stat_rows_expanded(team_stats,baseline_row,home,away,subject)
    # Reuse season_baseline's own per-match metric builder wholesale so the
    # match-day wheel values and the season distribution they're ranked
    # against share one definition (a prior version rebuilt a subset by hand
    # here under different key names -- won_ground_duels/won_aerial_duels vs
    # duels_won, opponent_half_regains vs opposition_half_regains -- so two
    # of twelve wedges silently read 0.0 every time).
    charlton_match_values=sb.match_metrics(events,subject,opponent)
    threat_density_img,threat_density_kpis=_threat_density_maps(events,teams)
    entries_kpis=_entries_kpis(events,subject)
    ooc_ctx=outofpossession_mod.outofpossession_context(events,duel_involvement,pressure_events,subject,opponent)
    transition_ctx=transition_mod.transition_context(events,subject,opponent)
    tracked=bool(context["tracked_shapes"])
    overview_ctx: dict[str, Any]={}
    if dvms_match is not None:
        from src.report import metrics_dvms
        overview_ctx=overview_mod.overview_context(
            dvms_match.f7,dvms_match.f24.events,dvms_match.avg_positions,
            lambda x,y:metrics_dvms._metres_to_adj(x,y,dvms_match.meta),events,subject)
    has_sheet=bool(overview_ctx)
    first_sub=min([e["minute"] for _,_,evs in overview_ctx.get("timeline_by_team",[]) for e in evs if e["kind"]=="sub"],
                  default=None)
    gamestate_ctx=gamestate_mod.gamestate_context(events,pressure_events,subject,opponent,first_sub)
    flow_timeline_img=_flow_timeline(events,dvms_match,subject,opponent,figsize=(5.4,1.3),font=6.6)
    timeline_img=_match_timeline(events,overview_ctx.get("timeline_by_team"),subject,opponent)
    players_ctx: dict[str, Any]={}
    try:
        kickoff=pd.Timestamp(events["dateTime"].iloc[0]).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        players_ctx=player_baseline.players_context(
            player_baseline.season_to_date(impect_match_id,int(events["iterationId"].iloc[0]),kickoff),
            events,subject,impect_match_id,
            physical=player_baseline.physical_by_shirt(dvms_match,subject) if dvms_match is not None else None)
    except Exception as error:   # the tables are an extra: say why they are missing rather than fail the report
        print(f"warning: player tables skipped ({type(error).__name__}: {error})")
    has_players=bool(players_ctx.get("player_pages"))
    summary_ctx=summary_mod.summary_context(events,team_stats,charlton_match_values,baseline,_PERFORMANCE_WHEEL_METRICS,
                                            gamestate_ctx["gamestate_data"],players_ctx.get("player_pages"),subject,opponent)
    page_plan=build_page_plan(tracked,has_sheet,has_players)
    context.update({
        "generated_date":dt.date.today().strftime("%d %B %Y"),
        "page_plan":page_plan,"report_page_count":page_plan["total"],
        "section_info":section_info(subject,tracked,has_sheet,has_players),
        "contents":build_contents(page_plan,subject,tracked,has_sheet,has_players),
        **players_ctx,
        **overview_ctx,
        **inpossession_mod.inpossession_context(events,subject,opponent),
        **shooting_mod.shooting_context(events,subject,opponent,{subject:palette.CHARLTON_RED,opponent:palette.OPPONENT_GREY}),
        "subject":subject,"opponent":opponent,"team_order":teams,"side_by_team":side_by_team,
        "network":networks,"network_scale_threat":network_scale_threat,
        "stat_rows_expanded":stat_rows_expanded,
        "performance_img":_performance_wheel(charlton_match_values,baseline),
        "xg_race_img":_xg_race(events,teams,figsize=(5.4,1.3),font=6.6),
        "threat_density_img":threat_density_img,"threat_density_kpis":threat_density_kpis,
        "flow_timeline_img":flow_timeline_img,"timeline_img":timeline_img,
        "entries_kpis":entries_kpis,
        "chance_source_img":chance_source_img,"chance_source_kpis":chance_source_kpis,
        "player_threat_ranking_img":player_threat_ranking_img,
        "player_threat_ranking_totals":player_threat_ranking_totals,
        **ooc_ctx,
        **gamestate_ctx,
        **summary_ctx,
        "baseline_matches":len(baseline),
        "second_ball_kpis":second_balls,
        **transition_ctx,
        "subject_colour":palette.CHARLTON_RED,"opponent_colour":palette.OPPONENT_GREY,
        "duel_aerial_bars_img":_duel_bars_by_type(
            duel_involvement,subject,opponent,"AERIAL",events=events),
        "duel_ground_bars_img":_duel_bars_by_type(
            duel_involvement,subject,opponent,"GROUND",events=events),
        "big_chances":{team:_big_chances(metrics.shot_events(events),team) for team in teams},
        "font_faces_css": _fonts.embedded_css(),
    })
    return context


def _big_chances(shots: pd.DataFrame, team: str, limit: int = 6) -> list[dict[str, Any]]:
    """Every goal the team scored, then the largest remaining chances, in match order."""
    own=shots.loc[shots.squadName==team]
    goals=own.loc[own.category.astype(str)=="Goal"]
    rest=own.drop(goals.index).nlargest(max(limit-len(goals),0),"SHOT_XG")
    chosen=pd.concat([goals,rest]).sort_values("gameTimeInSec") if "gameTimeInSec" in own else pd.concat([goals,rest])
    return [{"minute":str(r.gameTime).split(':')[0]+"'","player":str(r.playerName).split()[-1],"xg":float(r.SHOT_XG),
             "xgot":(float(r.POSTSHOT_XG) if str(r.category) in ("Goal","On target") else None),
             "result":("OFF TARGET" if str(r.category) == "Other" else str(r.category).upper())}
            for r in chosen.itertuples()]


def render_report(impect_match_id: int, dvms_match_id: str | None, output_path: Path,
                  chrome_bin: str | Path | None = None) -> Path:
    context=build_context(impect_match_id,dvms_match_id)
    env=Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)),autoescape=select_autoescape(["html"]),trim_blocks=True,lstrip_blocks=True)
    html=env.get_template("expanded.html.j2").render(**context)
    toc=build_toc(context["page_plan"],context["section_info"])
    contents=[{"title":row["title"],"first":row["first"]} for row in context["contents"]]
    # The context contains many large base64 chart images. Release it before
    # Chromium starts so private GitHub runners do not have to hold both the
    # plotting data and the browser in memory at the same time.
    del context
    gc.collect()
    output_path.parent.mkdir(parents=True,exist_ok=True)
    chrome = resolve_chrome(chrome_bin)
    print(f"Rendering with {chrome_version(chrome)} ({chrome})")
    problems=layout_check.find_overflow(html,chrome)
    if problems:
        message=f"Layout overflow: {layout_check.describe(problems)}"
        if os.environ.get("REPORT_ALLOW_LAYOUT_OVERFLOW")=="1":
            print(f"warning: {message}")
        else:
            raise layout_check.LayoutOverflowError(message+" (set REPORT_ALLOW_LAYOUT_OVERFLOW=1 to render anyway)")
    with tempfile.TemporaryDirectory(prefix="expanded-report-") as tmp:
        html_path=Path(tmp)/"report.html"
        html_path.write_text(html,encoding="utf-8")
        subprocess.run([
            str(chrome),"--headless","--disable-gpu","--no-pdf-header-footer",
            f"--print-to-pdf={output_path.resolve()}",html_path.resolve().as_uri(),
        ],check=True,capture_output=True)
    bookmarks.add_navigation(output_path,toc,contents)
    return output_path

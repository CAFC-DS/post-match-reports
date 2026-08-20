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

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = Path(__file__).with_name("templates")


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


def build_context(impect_match_id: int, dvms_match_id: str | None = None) -> dict[str, Any]:
    context=build_shared_context(impect_match_id,dvms_match_id)
    events=impect_cafcdb_source.load_match_events(impect_match_id)
    subject=context["meta"]["charlton_team"]
    opponent=context["meta"]["opponent_team"]
    teams=[subject,opponent]
    side_by_team={s["team"]:s for s in context["sides"]}
    colors={subject:palette.CHARLTON_RED,opponent:palette.OPPONENT_GREY}
    networks={}
    for team in teams:
        if "passReceiverPlayerName" in events.columns:
            net=metrics.passing_network(events,team)
        else:
            passes=events.loc[(events["squadName"]==team)&(events["actionType"]=="PASS")].copy()
            threat_col="PXT_PASS" if "PXT_PASS" in passes else "PXT_ATTACK"
            nodes=passes.groupby("playerName",dropna=True).agg(
                x=("startAdjCoordinatesX","mean"),y=("startAdjCoordinatesY","mean"),
                passes=("playerName","size"),threat=(threat_col,"sum"),
            ).reset_index()
            nodes["surname"]=nodes["playerName"].astype(str).str.split().str[-1]
            nodes["is_starter"]=True
            net=metrics.PassingNetwork(nodes,pd.DataFrame(columns=["a","b","ax","ay","bx","by","passes"]),float("inf"),len(passes))
        mx=max(1,int(net.edges["passes"].max())) if not net.edges.empty else 1
        mt=max(.001,float(net.nodes["threat"].abs().max())) if not net.nodes.empty else .001
        networks[team]=pitch.passing_network_map(net,colors[team],mx,mt)
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
    context.update({
        "generated_date":dt.date.today().strftime("%d %B %Y"),
        "subject":subject,"opponent":opponent,"team_order":teams,"side_by_team":side_by_team,
        "network":networks,
        "pressure_img":_event_map(pressures,colors[subject]),
        "ground_duel_img":_event_map(ground,colors[subject]),
        "aerial_duel_img":_event_map(aerial,colors[subject]),
        "regain_img":_event_map(regains,colors[subject]),
        "second_ball_img":_event_map(second,palette.SUCCESS_GREEN),
        "transition_img":_event_map(losses,colors[subject]),
        "duel_player_img":_bars([str(x).split()[-1] for x in players.index],(players.ground+players.aerial).tolist(),colors[subject]),
        "recovery_player_img":_bars([str(x).split()[-1] for x in players.index],players.wins.tolist(),palette.SUCCESS_GREEN),
        "event_counts":{"pressures":len(pressures),"regains":len(regains),"second_balls":len(second),"losses":len(losses)},
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

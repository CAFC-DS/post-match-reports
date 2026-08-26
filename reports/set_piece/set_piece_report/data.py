"""Event loading and fixture selection for the single-match set-piece report.

Reuses the *same connection layer* as ``full-season-analysis``
(:class:`src.db.query_runner.QueryRunner`): it reads the cached parquet extract
when present and otherwise pulls from Snowflake using the project ``.env`` and
``config/tables.yml``. Raw IMPECT columns are kept (no remapping) because the
set-piece sub-phase fields we need are not part of the season project's column
map.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# --- make the parent full-season-analysis project importable ------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.query_runner import QueryRunner  # noqa: E402  (after sys.path tweak)

from set_piece_report.config import REGULAR_SEASON_CUTOFF  # noqa: E402


@dataclass(frozen=True)
class MatchContext:
    """Everything downstream code needs about the selected fixture."""

    match_id: int
    date: pd.Timestamp
    competition: str
    season: str
    matchday: int | None            # this fixture's league round (e.g. 46)
    matchday_total: int | None      # regular-season rounds in the competition
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    match_events: pd.DataFrame          # all events for this fixture
    home_season_events: pd.DataFrame    # home team's regular-season events
    away_season_events: pd.DataFrame    # away team's regular-season events
    player_team: dict[str, str]         # player name -> squad name (this match)
    # Whether the /90 and % change columns are meaningful enough to show.
    # False at matchday 1 of a season sourced from itself (no season history
    # yet to compare against) -- see impect_cafcdb_source.load_match_context
    # for the other case this covers (a new-season fixture whose baseline is
    # borrowed from last season entirely, not "this season so far").
    show_comparisons: bool

    @property
    def score_line(self) -> str:
        return f"{self.home_goals} - {self.away_goals}"


def _load_league_events(refresh: bool = False) -> pd.DataFrame:
    """Load the full league event table through the shared QueryRunner."""
    runner = QueryRunner()
    df = runner.load_league_events(refresh=refresh)
    # ``dateTime`` arrives as an ISO string; parse once for all downstream use.
    df = df.copy()
    df["_dt"] = pd.to_datetime(df["dateTime"], utc=True, errors="coerce")
    return df


def _team_regular_season(df: pd.DataFrame, team: str) -> pd.DataFrame:
    """All of a team's events before the playoff cut-off (per-90 baseline)."""
    cutoff = pd.Timestamp(REGULAR_SEASON_CUTOFF, tz="UTC")
    mask = (
        (df["homeSquadName"] == team) | (df["awaySquadName"] == team)
    ) & (df["_dt"] < cutoff)
    return df.loc[mask].copy()


_MATCHDAY_RE = re.compile(r"(\d+)\.\s*Spieltag")


def _matchday_number(name: object) -> int | None:
    m = _MATCHDAY_RE.search(str(name))
    return int(m.group(1)) if m else None


def _matchday_info(league: pd.DataFrame, competition: str, match_name: object) -> tuple[int | None, int | None]:
    """This fixture's round number and the competition's regular-season total."""
    current = _matchday_number(match_name)
    comp = league.loc[league["competitionName"] == competition, "matchDayName"]
    nums = [n for n in (_matchday_number(v) for v in comp.dropna().unique()) if n]
    total = max(nums) if nums else None
    return current, total


def _count_goals(match: pd.DataFrame, team: str) -> int:
    return int(
        ((match["actionType"] == "GOAL") & (match["squadName"] == team)).sum()
        + ((match["actionType"] == "OWN_GOAL") & (match["squadName"] != team)).sum()
    )


def load_match_context(match_id: int, refresh: bool = False) -> MatchContext:
    """Build the :class:`MatchContext` for ``match_id``."""
    league = _load_league_events(refresh=refresh)
    match = league.loc[league["matchId"] == match_id].copy()
    if match.empty:
        raise ValueError(
            f"No events found for matchId={match_id}. "
            "Check the id or run with refresh=True to repull from Snowflake."
        )

    home = str(match["homeSquadName"].iloc[0])
    away = str(match["awaySquadName"].iloc[0])
    competition = str(match["competitionName"].iloc[0])
    matchday, matchday_total = _matchday_info(league, competition, match["matchDayName"].iloc[0])

    player_team = (
        match.dropna(subset=["playerName", "squadName"])
        .groupby("playerName")["squadName"]
        .agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )

    return MatchContext(
        match_id=int(match_id),
        date=match["_dt"].iloc[0],
        competition=competition,
        season=str(match["season"].iloc[0]),
        matchday=matchday,
        matchday_total=matchday_total,
        home_team=home,
        away_team=away,
        home_goals=_count_goals(match, home),
        away_goals=_count_goals(match, away),
        match_events=match,
        home_season_events=_team_regular_season(league, home),
        away_season_events=_team_regular_season(league, away),
        player_team=player_team,
        show_comparisons=(matchday or 1) != 1,
    )

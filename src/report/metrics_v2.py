"""Derived match metrics for the v2 report.

Average positions only cover the build-up (in-possession) phase. This is
event data, not tracking data: a player's coordinates are only recorded when
they touch the ball or otherwise act, so an "average position" is really an
average of their on-ball moments. That's a defensible, standard read for
build-up, where most of the team touches the ball repeatedly over the match.
It stops being a fair read for transition or out-of-possession play, where
a player's positioning matters most in exactly the moments they *aren't*
touching the ball — the average there is only ever built from a handful of
defensive actions (tackles, interceptions, blocks) by whichever players
happened to make one, silently drops teammates who made none, and says
nothing about where the other ~7 players were standing. Getting that right
needs tracking data, not event data, so those maps were removed rather than
shipped looking authoritative while being systematically biased.

The build-up split uses the vendor's own event tagging (``phase`` ==
IN_POSSESSION while ``attackingSquadName`` is this team) rather than
reconstructing it from heuristics like successful-pass streaks.
"""

from __future__ import annotations

import pandas as pd


def _get_starters(events: pd.DataFrame, team: str) -> list[str]:
    """Get the 11 players with the earliest first event for a team."""
    team_events = events[events["squadName"] == team].copy()
    first_event = team_events.groupby('playerName')['gameTimeInSec'].min()
    starters = first_event.sort_values().head(11).index.tolist()
    return starters


def average_positions_in_possession(events: pd.DataFrame, team: str) -> pd.DataFrame:
    """Average position of each starter during settled build-up: their own
    events tagged IN_POSSESSION while their team has the ball."""
    starters = _get_starters(events, team)
    mask = (
        (events["squadName"] == team)
        & (events["phase"] == "IN_POSSESSION")
        & (events["playerName"].isin(starters))
    )
    # The governed CAFC_DB adapter emits only the acting squad. Older staging
    # extracts also carried attackingSquadName; when present, retain the extra
    # guard without making the fallback depend on a legacy-only column.
    if "attackingSquadName" in events:
        mask &= events["attackingSquadName"] == team
    team_events = events[mask]
    return team_events.groupby('playerName').agg(
        x=('startAdjCoordinatesX', 'mean'),
        y=('startAdjCoordinatesY', 'mean'),
    ).reset_index()


def _get_defenders(avg_pos: pd.DataFrame) -> list[str]:
    """Get the 4 players sitting deepest in their own half.

    ``x`` is the pitch-length axis, own goal at -52.5 / attacking goal at
    +52.5 (see pitch.py); ``y`` is side-to-side width and says nothing about
    how far up the pitch a player sits.
    """
    own_half_players = avg_pos[avg_pos['x'] < 0]
    defenders = own_half_players.sort_values('x').head(4)
    return defenders['playerName'].tolist()


def average_line_height(avg_pos: pd.DataFrame) -> float:
    """Average defensive line height, in metres from the team's own goal
    line (0-105m pitch), from the 4 deepest starters' average x position."""
    defenders = _get_defenders(avg_pos)
    if not defenders:
        return 0.0

    defender_positions = avg_pos[avg_pos['playerName'].isin(defenders)]
    return defender_positions['x'].mean() + 52.5

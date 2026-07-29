"""Reader for the Second Spectrum positional tracking (DVMS ASSET_SUBTYPE=38).

JSONL, one JSON object per frame at 25fps. A full match is ~1.5-2M frames, far
too big to hold in memory as one table, so the primary entry point streams:
:func:`iter_frames` yields one parsed dict per line. :func:`frames_to_long_df`
then downsamples (default: every 5th frame ≈ 5Hz) into a tidy long DataFrame
suitable for heatmaps / average positions / line height.

Unlike the parsers in this package, this module *does* read from disk — tracking
files are streamed, not passed as text — but it stays pure otherwise. It sniffs
``.gz`` by suffix and also accepts an already-open file/iterable of lines, so it
works against the local ``.jsonl`` peek and the gzipped Snowflake stage file
alike.

Frame structure (verified): ``{period, frameIdx, gameClock, wallClock,
homePlayers:[{playerId, number, xyz:[x,y,z], speed, optaId}], awayPlayers, ball:
{xyz, speed}, live, lastTouch}``. ``xyz`` is pitch-centred metres (0,0 = centre).
"""

from __future__ import annotations

from typing import Iterable, Iterator, Union
import gzip
import io
import json

import pandas as pd


def iter_frames(path_or_file: Union[str, "io.IOBase", Iterable[str]]) -> Iterator[dict]:
    """Stream frames from a JSONL tracking source.

    ``path_or_file`` may be a path string (``.gz`` is transparently
    decompressed by suffix), an already-open text file, or any iterable of JSON
    lines. Blank lines are skipped. Yields one dict per frame — the caller
    controls memory by consuming lazily.
    """
    if isinstance(path_or_file, str):
        opener = gzip.open if path_or_file.endswith(".gz") else open
        with opener(path_or_file, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
        return

    # Already-open file or iterable of lines.
    for line in path_or_file:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if line:
            yield json.loads(line)


def _player_rows(frame: dict, team: str, players_key: str):
    period = frame.get("period")
    frame_idx = frame.get("frameIdx")
    game_clock = frame.get("gameClock")
    live = frame.get("live")
    last_touch = frame.get("lastTouch")
    for p in frame.get(players_key, []):
        xyz = p.get("xyz") or [None, None, None]
        yield {
            "period": period,
            "frame_idx": frame_idx,
            "game_clock": game_clock,
            "live": live,
            "last_touch": last_touch,
            "team": team,
            "opta_id": str(p["optaId"]) if p.get("optaId") is not None else None,
            "number": p.get("number"),
            "x": xyz[0],
            "y": xyz[1],
            "z": xyz[2] if len(xyz) > 2 else None,
            "speed": p.get("speed"),
        }


def frames_to_long_df(frames: Iterable[dict], every_n: int = 5) -> pd.DataFrame:
    """Downsample a frame stream to a tidy long DataFrame.

    One row per tracked entity per kept frame. Every ``every_n``-th frame is
    kept (``every_n=5`` on 25fps data ≈ 5Hz, plenty for spatial aggregates).
    Columns: ``period, frame_idx, game_clock, live, last_touch, team
    ('home'/'away'/'ball'), opta_id (None for the ball), number, x, y, z,
    speed``. Coordinates are the raw pitch-centred metres from the feed.
    """
    rows = []
    for i, frame in enumerate(frames):
        if every_n > 1 and i % every_n != 0:
            continue
        rows.extend(_player_rows(frame, "home", "homePlayers"))
        rows.extend(_player_rows(frame, "away", "awayPlayers"))
        ball = frame.get("ball")
        if ball:
            xyz = ball.get("xyz") or [None, None, None]
            rows.append(
                {
                    "period": frame.get("period"),
                    "frame_idx": frame.get("frameIdx"),
                    "game_clock": frame.get("gameClock"),
                    "live": frame.get("live"),
                    "last_touch": frame.get("lastTouch"),
                    "team": "ball",
                    "opta_id": None,
                    "number": None,
                    "x": xyz[0],
                    "y": xyz[1],
                    "z": xyz[2] if len(xyz) > 2 else None,
                    "speed": ball.get("speed"),
                }
            )

    df = pd.DataFrame(
        rows,
        columns=[
            "period", "frame_idx", "game_clock", "live", "last_touch",
            "team", "opta_id", "number", "x", "y", "z", "speed",
        ],
    )
    if not df.empty:
        df["opta_id"] = df["opta_id"].astype("string")
    return df

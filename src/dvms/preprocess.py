"""Per-fixture preprocessing: raw tracking → cached parquet artifacts.

A raw tracking file is ~1.5-2M frames of JSON; nothing downstream should
ever parse it twice. This pipeline streams it once and writes the derived
artifacts next to it in the shared cache:

    frames_5hz.parquet      downsampled long frame table (players + ball)
    phases_home.parquet     phase per live frame, home perspective
    phases_away.parquet     …away perspective
    shape_home.parquet      per-frame line heights / block shape, home
    shape_away.parquet      …away
    avg_positions_home.parquet   per-player per-phase averages, home
    avg_positions_away.parquet   …away

Every metrics call in the reports reads these (milliseconds) instead of the
raw feed (minutes).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .loaders import assets, cache, positional
from .metrics.avg_positions import average_positions
from .metrics.lines import team_shape_timeseries, unit_map
from .metrics.phases import classify_phases
from .parsers.f7 import parse_f7
from .parsers.ss_meta import parse_ss_metadata
from .parsers.tracking import frames_to_long_df, iter_frames

ARTIFACTS = (
    "frames_5hz.parquet",
    "phases_home.parquet", "phases_away.parquet",
    "shape_home.parquet", "shape_away.parquet",
    "avg_positions_home.parquet", "avg_positions_away.parquet",
)


def is_preprocessed(opta_match_id: str) -> bool:
    d = cache.match_dir(opta_match_id, create=False)
    return d.is_dir() and all((d / name).is_file() for name in ARTIFACTS)


def preprocess_fixture(fixture_id: str, opta_match_id: str,
                       every_n: int = 5, refresh: bool = False,
                       env_path: str = ".env") -> Path:
    """Fetch (if needed) and preprocess one fixture. Returns the cache dir."""
    d = cache.match_dir(opta_match_id)
    if is_preprocessed(opta_match_id) and not refresh:
        return d

    meta = parse_ss_metadata(
        assets.fetch_asset_text(fixture_id, opta_match_id, 40, env_path=env_path))
    f7 = parse_f7(
        assets.fetch_asset_text(fixture_id, opta_match_id, 21, env_path=env_path))
    tracking_file = positional.fetch_tracking(fixture_id, opta_match_id,
                                              env_path=env_path)

    frames = frames_to_long_df(iter_frames(str(tracking_file)), every_n=every_n)
    frames.to_parquet(d / "frames_5hz.parquet", index=False)

    for side in ("home", "away"):
        phases = classify_phases(frames, meta, side)
        phases.to_parquet(d / f"phases_{side}.parquet", index=False)

        team_meta = f7.home if side == "home" else f7.away
        team_lineups = f7.lineups[f7.lineups["team_id"] == team_meta.team_id]
        units = unit_map(team_lineups)

        shape = team_shape_timeseries(frames, meta, side, units)
        shape.to_parquet(d / f"shape_{side}.parquet", index=False)

        avg = average_positions(frames, phases, meta, side)
        avg.to_parquet(d / f"avg_positions_{side}.parquet", index=False)

    return d


def load_artifact(opta_match_id: str, name: str) -> pd.DataFrame:
    path = cache.match_dir(opta_match_id, create=False) / name
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} missing — run: python -m src.dvms.cli preprocess "
            f"--match-id {opta_match_id}")
    return pd.read_parquet(path)

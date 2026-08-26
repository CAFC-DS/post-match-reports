"""Parsers for the Second Spectrum physical CSVs (DVMS ASSET_SUBTYPE 42/43).

Two files, two shapes:

* **Summary (43)** — per-player totals for the match: distance, speed-zone
  breakdown, sprints, top/average speed, and the TIP/OTIP/BOP splits (Team In
  Possession / Opponent Team In Possession / Ball Out of Play) already broken
  out per metric. The real header row is preceded by a title/game-time preamble,
  and the file carries *two* player blocks (home team first, then away), each
  re-emitting the header — so a plain ``read_csv`` misreads it.

* **Splits (42)** — team- and player-level minute-by-minute distances/counts.
  This one is genuinely multi-section (see ``parse_physical_splits``).

Both take only CSV text — no file or network I/O.
"""

from __future__ import annotations

import csv
import io
import re
from typing import List, Optional

import numpy as np
import pandas as pd

# Ordered map from the summary's raw header labels to snake_case column names.
# Only the columns the reports use are renamed explicitly; the TIP/OTIP/BOP
# split columns are normalised programmatically (see ``_snake``).
_SUMMARY_RENAME = {
    "ID": "opta_player_id",
    "Player": "name",
    "Minutes": "minutes",
    "Distance": "distance",
    "Walking": "walking",
    "Jogging": "jogging",
    "Running": "running",
    "High Speed Running": "hsr",
    "Sprinting": "sprinting",
    "No. of High Intensity Runs": "n_high_intensity_runs",
    "Top Speed": "top_speed",
    "Average Speed": "avg_speed",
}


def _snake(label: str) -> str:
    """Normalise a summary split-column label to snake_case.

    ``"HSR Distance TIP"`` -> ``"hsr_distance_tip"``,
    ``"No. of High Intensity Runs OTIP"`` -> ``"n_high_intensity_runs_otip"``.
    """
    label = label.replace("No. of High Intensity Runs", "n_high_intensity_runs")
    label = label.replace("High Speed Running", "hsr").replace("HSR", "hsr")
    label = label.replace(".", " ")
    label = re.sub(r"[^0-9A-Za-z]+", "_", label.strip())
    return label.lower().strip("_")


def _minutes_to_float(value: Optional[str]) -> float:
    """``"100:44"`` (MM:SS) -> ``100.733`` minutes; passes through plain floats."""
    if value is None or value == "":
        return np.nan
    value = value.strip()
    if ":" in value:
        mins, secs = value.split(":", 1)
        try:
            return int(mins) + int(secs) / 60.0
        except ValueError:
            return np.nan
    try:
        return float(value)
    except ValueError:
        return np.nan


def parse_physical_summary(csv_text: str) -> pd.DataFrame:
    """Parse the per-player physical summary CSV (subtype 43).

    Returns one row per player across both team blocks. ``opta_player_id`` is a
    string, ``minutes`` a float (MM:SS converted), and every distance/speed/
    count/split column is numeric with a snake_case name (``distance``,
    ``hsr``, ``distance_tip``, ``hsr_distance_otip``, ...). A ``team_block``
    column (0 = first block / home, 1 = second block / away) preserves which
    section a player came from without needing the metadata roster.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    header: Optional[List[str]] = None
    columns: List[str] = []
    out_rows = []
    team_block = -1

    for r in rows:
        if not r:
            continue
        if r[0] == "ID":
            # Start of a player block; each block re-emits the same header.
            header = r
            columns = [
                _SUMMARY_RENAME.get(label, _snake(label)) for label in header
            ]
            team_block += 1
            continue
        if header is None:
            continue  # still in the title/game-time preamble
        if len(r) < len(header) or not r[0].strip().isdigit():
            continue  # not a player data row

        record = {"team_block": team_block}
        for col, raw in zip(columns, r):
            if col == "opta_player_id":
                record[col] = raw.strip()
            elif col == "name":
                record[col] = raw.strip()
            elif col == "minutes":
                record[col] = _minutes_to_float(raw)
            else:
                record[col] = float(raw) if raw not in ("", None) else np.nan
        out_rows.append(record)

    df = pd.DataFrame(out_rows)
    if not df.empty:
        df["opta_player_id"] = df["opta_player_id"].astype("string")
    return df


# Section labels look like ``"Todd Cantwell (193111)"`` / ``"Middlesbrough FC (5)"``.
_SECTION_RE = re.compile(r"^(?P<name>.+?)\s*\((?P<id>\d+)\)\s*$")


def parse_physical_splits(csv_text: str) -> pd.DataFrame:
    """Parse the messy team/player minute-split CSV (subtype 42) to long format.

    File structure found in the sample (documented so the shape is on record):

    * A title/game-id preamble, then a "Threshold key" block listing the km/h
      speed-zone thresholds.
    * One ``"Minute Splits",5,10,...,45,50,<blank>,50,55,...,95`` header **per
      team**. The minute columns are cumulative 5-minute-bin ends; the two
      halves are separated by a **blank column**, and the value ``50`` appears
      twice (end of first-half stoppage, then the second-half restart), so
      minute labels are *not* unique — a ``half`` column disambiguates them.
    * After each header: first a **team-total** section (``"<Team> (<team_id>)"``),
      then one section per player (``"<Player> (<player_id>)"``). Each section is
      a run of metric rows (Total Distance, Walking Distance, ... , Sprinting
      Count).

    Returned long DataFrame columns: ``section`` (name as found), ``section_id``
    (the parenthesised id — team id for the total row, player id otherwise),
    ``is_team_total`` (bool, the first section under each header), ``metric``
    (snake_case), ``minute`` (int, cumulative bin end), ``half`` (1/2) and
    ``value`` (float). Written defensively: unknown rows are skipped rather than
    raising, so a slightly different header layout degrades gracefully.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    out_rows = []
    minute_cols: List[tuple] = []  # (col_index, minute:int, half:int)
    section_name: Optional[str] = None
    section_id: Optional[str] = None
    is_team_total = False
    seen_section_in_block = False

    for r in rows:
        if not r:
            continue
        first = r[0].strip()

        if first == "Minute Splits":
            # Build the (column-index -> minute, half) map for this block.
            minute_cols = []
            half = 1
            for idx in range(1, len(r)):
                cell = r[idx].strip()
                if cell == "":
                    half = 2  # the blank separator column between halves
                    continue
                try:
                    minute_cols.append((idx, int(cell), half))
                except ValueError:
                    continue
            seen_section_in_block = False
            section_name = None
            continue

        m = _SECTION_RE.match(first) if first else None
        if m and minute_cols:
            section_name = m.group("name").strip()
            section_id = m.group("id")
            is_team_total = not seen_section_in_block  # first section under header
            seen_section_in_block = True
            continue

        if section_name is None or not minute_cols:
            continue  # preamble / threshold key / between blocks

        # A metric row inside the current section.
        metric = _snake(first)
        if not metric:
            continue
        for idx, minute, half in minute_cols:
            if idx >= len(r):
                continue
            raw = r[idx].strip()
            if raw == "":
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            out_rows.append(
                {
                    "section": section_name,
                    "section_id": section_id,
                    "is_team_total": is_team_total,
                    "metric": metric,
                    "minute": minute,
                    "half": half,
                    "value": value,
                }
            )

    df = pd.DataFrame(out_rows)
    if not df.empty:
        df["section_id"] = df["section_id"].astype("string")
    return df

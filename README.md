# Set-Piece Report

A one-page, **landscape** "Set Play Analysis" report for a single fixture, built
from IMPECT event data. Both teams' attacking corner overviews, both teams'
free-kick overviews, and a central stack of split stat bars — rendered in a clean
cream / editorial style.

Worked example (default): **Swansea City 3–1 Charlton Athletic, 2 May 2026
(Championship 2025/26)**.

## What's on the page

| Region | Content |
| --- | --- |
| Masthead | Crests, single-line scoreline, competition / season / date |
| Left & right panels | Each team's **attacking corners** and **free kicks** (delivery maps over a threat heatmap). Left = home, right = away. Corner graphic has two styles (see `--corner-style`): *hybrid* (delivery arrows coloured by IMPECT corner type over a danger-zone heatmap) or *zones* (a 6-cell target-zone grid shaded/labelled by deliveries landed). |
| Centre | Split **stat bars** — corners, throw-ins and indirect free-kicks (total + shots / goals / xG created). Each row shows the match value for both teams plus their **season /90** rate and the **% change** vs that rate |
| Lower band | **Corner** and **free-kick first-contact** tables — attacking & defending, taken/faced, won / lost / win% — for both teams |

## Connections

Uses the same Snowflake connection layer as the season project
(`src.db.query_runner.QueryRunner`, vendored into this repo). It reads the cached
parquet extract (`data/processed/league_events.parquet`) when present, and
otherwise pulls from Snowflake using `.env` + `config/tables.yml`.

Set-piece attribution reads raw IMPECT fields directly — shots, goals and xG
carry a `setPieceCategory`, corner type comes from `setPieceSubPhaseCornerType`,
and first contacts from the `setPieceSubPhase*` sub-phase columns.

## Setup

```bash
pip install -r requirements.txt          # needs weasyprint, mplsoccer, snowflake-connector
cp .env.example .env                      # fill in Snowflake creds (only needed for --refresh)
```

The repo ships with `data/processed/league_events.parquet` so it runs offline out
of the box. A fresh clone without that file will pull from Snowflake on first run
(needs `.env`).

## Run

```bash
# default fixture (Swansea v Charlton, 2 May 2026) → HTML + PDF
python set_piece_report/run.py

# any fixture by IMPECT matchId
python set_piece_report/run.py --match-id 206675

# HTML only / PDF only / force a Snowflake repull
python set_piece_report/run.py --html-only
python set_piece_report/run.py --pdf-only
python set_piece_report/run.py --refresh

# corner graphic style: hybrid (default), zones, or both files for comparison
python set_piece_report/run.py --corner-style zones
python set_piece_report/run.py --corner-style both
```

Output lands in `outputs/set_piece_report/`. The script pins its own working
directory, so it runs from anywhere.

> Use an interpreter that has the deps. If you use Anaconda, that is typically
> `/opt/anaconda3/bin/python set_piece_report/run.py`.

## Finding a matchId

```python
import pandas as pd
df = pd.read_parquet("data/processed/league_events.parquet",
                     columns=["matchId", "dateTime", "homeSquadName", "awaySquadName"])
print(df.drop_duplicates("matchId")
        .query("homeSquadName.str.contains('Charlton') or awaySquadName.str.contains('Charlton')"))
```

## Layout

```
set-piece-report/
├── set_piece_report/            # the report package
│   ├── data.py                  # load events via QueryRunner → MatchContext
│   ├── metrics.py               # stat bars, per-90 / % change, first contacts, corner type
│   ├── pitch.py                 # corner & free-kick delivery maps → base64 PNG
│   ├── render.py                # Jinja2 context → HTML → PDF (WeasyPrint)
│   ├── config.py                # palette + IMPECT taxonomy
│   ├── run.py                   # CLI entry point
│   └── templates/set_piece_report.html.j2
├── src/                         # vendored connection layer (Snowflake + cache) + badges
├── config/tables.yml            # project + table config
├── sql/extracts/impect_events.sql
├── assets/badges_small/         # club crests
└── data/processed/              # parquet cache (git-ignored)
```

## Methodology notes

- **/90 baseline** = each team's own 2025/26 regular-season total ÷ matches
  played (playoff fixtures from 4 May 2026 excluded). **% change** = the single
  match vs that baseline (display capped at +999% / −100%).
- **Corner type** is the IMPECT delivery zone (`setPieceSubPhaseCornerType`):
  near post / central / far post / short (worked / open-play). The shading under
  the arrows is a kernel-density heatmap of where deliveries land.
- **Indirect free-kicks** = free-kicks played into the game, not shot directly.
- **Shots from set-pieces** includes every shot from a corner, free-kick or
  throw-in (direct free-kick shots included); goals flagged from shot `result`.
- **First contact** uses `setPieceSubPhaseFirstTouchWon` (attacking-team view);
  the defending team's wins are the attack's losses. Uncontested / short
  deliveries are excluded from Win%.

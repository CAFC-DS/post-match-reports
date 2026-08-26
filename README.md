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
| Masthead | Crests, single-line scoreline, **matchday** (e.g. 46 / 46), competition, date |
| Left & right panels | Each team's **attacking corners** (top) and, below, **free kicks** + **throw-ins** side by side, each with its own **key underneath**, then that team's **first-contact table** (pinned to the base of the column). Left = home, right = away. Corner graphic has two styles (see `--corner-style`): *hybrid* (arrows coloured by IMPECT corner type over a danger-zone heatmap) or *zones* (a 6-cell target-zone grid). |
| Centre | A **stat table** — corners, throw-ins, indirect free-kicks and **direct free-kicks** (total + shots / goals / xG created), grouped into labelled sections with row gridlines. Bars use each side's **real club colour**. Each row shows the match value for both teams plus their **season /90** rate and the **% change** vs that rate. |

**Pitch markers.** Every end marker is a circle: **fill = the delivery category, outline ring = the outcome**, and a **gold ★** replaces it when the delivery led to a goal. Fill colours are a colourblind-safe categorical set (Paul Tol "vibrant"), deliberately avoiding red/green so they never clash with the outcome ring.

- **Corners** — fill = where it landed (near / central / far post / short); ring = first contact (green won · red lost · grey uncontested).
- **Free-kicks** — fill = type, in four buckets: **Cross** (driven), **High ball** (lofted from deep), **Short** (recycled / kept), **Shot** (direct, drawn as a dashed arrow); ring = first contact as above.
- **Throw-ins** — fill = length (purple long · grey short); ring = possession (green retained · red lost, where *retained* = the throwing team had the next touch).

Every map carries an **"attacking" direction arrow** drawn alongside it, spanning the pitch length (so backward throw-ins are obvious). The corner map has its own two-line key beneath (landed, then first contact); the free-kick and throw-in keys are consolidated in one tidy block under their two maps.

Two colour themes (`--theme`): the cream **light** editorial theme and a charcoal **dark** theme (pitch artwork is redrawn to match, and dark club crests such as Swansea are lifted so they stay legible). The bottom tables have two styles (`--tables`): **team** (aggregate first-contact by team) or **players** (each side's top first-contact winners, by player).

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

# colour theme: light (default), dark, or both files
python set_piece_report/run.py --theme dark
python set_piece_report/run.py --theme both

# bottom tables: team (default), players (top first-contact winners), or both
python set_piece_report/run.py --tables players
python set_piece_report/run.py --tables both
```

Filenames carry a suffix per variant: `_corner_zones` (zones), `_players`
(player tables), `_dark` (dark theme) — so combining `both` options writes every
permutation as its own file.

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
- **Direct free-kicks** = attempts straight at goal (`setPieceSubPhaseFreeKickType
  == FREE_KICK_SHOT`); the attempt is itself the shot, so goals come off the shot
  `result`. These are kept out of the indirect-free-kick counts.
- **Throw-ins** are split *long* (into the final third, fairly central) vs *short*
  from the delivery end coordinate. Their marker ring shows **possession
  retained** (green) vs lost (red) — whether the throwing team still had the ball
  on the next touch — which is the point of the short throw-and-keep routine.
- **Matchday** is parsed from `matchDayName` ("46. Spieltag"); the total is the
  competition's highest regular-season round.
- **Led to goal** (the ★ marker) links a delivery to a goal by shared `setPieceId`
  (direct free-kicks use the shot `result`).
- **Club colours** — the bars use each side's brand colour (`config.TEAM_COLORS`),
  with a contrast guard: if two clubs' colours clash the theme's neutral
  home/away pair is used instead.
- **First contact** uses `setPieceSubPhaseFirstTouchWon` (attacking-team view);
  the defending team's wins are the attack's losses. Uncontested / short
  deliveries are excluded from Win%.
- **First-contact winners** (players view) take the attacking winner from
  `setPieceSubPhaseFirstTouchPlayerName` (only recorded when the attack wins) and
  recover the defending winner from the next aerial event after the delivery —
  which matches the feed's named winner exactly on the cases it does record.

# Combined Board Post-Match Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone project, `combined-post-match-report`, that renders a single-page board post-match report combining Impect and Opta/Second Spectrum (DVMS) data, using the exact layout/styling of `board-post-match-report`'s v2 report but sourcing each panel from whichever provider is best for that metric.

**Architecture:** Vendor the reusable pieces of `/Users/hashim.umarji/Projects/board-post-match-report/` (Snowflake plumbing, the DVMS package, the pitch/chart drawing functions, the two metrics modules) unmodified. Add one new module, `metrics_combined.py`, that combines the two sources for the three panels that need blending (match stats, entries' through/over/around split, player contribution). Copy the v2 Jinja2 template byte-for-byte and apply only the minimal per-panel edits the source swap requires.

**Tech Stack:** Python 3.11+, pandas, Snowflake connector, Jinja2, WeasyPrint, matplotlib + mplsoccer, pytest.

## Global Constraints

- Template CSS block must diff to zero against `board-post-match-report/src/report/templates/post_match_report_v2.html.j2` — no panel resizing, no new panels.
- Match stats table stays at exactly 13 rows (`metrics.STAT_ROWS`), unmodified — only the `possession_pct` column's *values* are replaced with DVMS-tracked numbers.
- Average positions panel stays one image per side (in-possession only) — do not adopt DVMS's 4-pitch in/out-of-possession layout.
- Shot map / xG stays plain "xG" everywhere (no `xg_lite`/`XG_MODEL_LABEL` wording) — Impect's real provider model feeds this panel.
- Impect data comes from `CAFC_TEST_ANALYSIS.PUBLIC.IMPECT_EVENTS_STAGING` (via `config/tables.yml` + `QueryRunner`), not `CAFC_DB.IMPECT_RAW.EVENTS`.
- DVMS data comes from `CAFC_DB.DVMS_RAW.*` via the vendored `src/dvms/` package; its tracking cache is shared machine-wide at `~/.cache/cafc-dvms/<opta_match_id>/` (env override `CAFC_DVMS_CACHE`) — vendoring `src/dvms/loaders/cache.py` unmodified means this project automatically reuses any match already preprocessed by `board-post-match-report`, no extra plumbing needed.
- CLI takes both `--impect-match-id` (int) and `--dvms-match-id` (Opta match id string) — no auto-matching between providers.
- Before rendering, assert Impect's and DVMS's team names (case-insensitive) and match dates agree; abort with a clear error otherwise.
- Scope is the board-post-match report only — no set-piece, no pre-match, no passing-network panel (already dropped in v2).

---

## File Structure

```
combined-post-match-report/
  .env.example
  .gitignore
  requirements.txt
  config/
    tables.yml                          # vendored, unmodified
  sql/extracts/
    match_events.sql                    # vendored, unmodified
    season_results.sql                  # vendored, unmodified
  assets/badges/
    Charlton Logo.png                   # vendored
    Swansea_City_A.F.C._logo.png        # vendored
  src/
    db/
      snowflake_connection.py           # vendored, unmodified
      table_config.py                   # vendored, unmodified
      query_runner.py                   # vendored, unmodified
    dvms/                                # vendored, byte-identical copy (per its own VENDOR.md convention)
      ... (full package, unmodified)
    report/
      palette.py                        # vendored, unmodified
      pitch.py                          # vendored, unmodified
      chart.py                          # vendored, unmodified
      chart_dvms.py                     # vendored, unmodified
      metrics.py                        # vendored, unmodified (Impect)
      metrics_dvms.py                   # vendored, unmodified (DVMS)
      metrics_combined.py               # NEW — combined stats, blended contribution, line-break split
      render_combined.py                # NEW — build_context + render_report + fixture-linking assertion
      templates/
        post_match_report_combined.html.j2   # copied from v2, then minimally edited
    visualisation/
      badges.py                         # vendored, unmodified
  tests/
    dvms/                                # vendored test suite, unmodified
    test_metrics_combined.py             # NEW
    test_render_combined.py              # NEW (fixture-linking assertion)
  generate_report_combined.py            # NEW — CLI entry point
  data/processed/                        # gitignored, created at runtime
  outputs/                               # gitignored, created at runtime
```

---

### Task 1: Scaffold the project and vendor the Snowflake/config plumbing

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`
- Create (vendored copies): `config/tables.yml`, `sql/extracts/match_events.sql`, `sql/extracts/season_results.sql`, `src/db/snowflake_connection.py`, `src/db/table_config.py`, `src/db/query_runner.py`, `src/db/__init__.py`

**Interfaces:**
- Produces: `src.db.query_runner.QueryRunner` — `QueryRunner().load_match_events(match_id: int, refresh: bool = False) -> pd.DataFrame`, `.load_season_results(refresh: bool = False) -> pd.DataFrame`, used by Task 10.

- [ ] **Step 1: Create the directory skeleton**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
mkdir -p config sql/extracts src/db src/report/templates src/visualisation src/dvms assets/badges tests data/processed outputs
touch src/__init__.py src/db/__init__.py src/report/__init__.py src/visualisation/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
pandas>=2.2
numpy>=1.26
snowflake-connector-python>=3.10
cryptography>=42.0
python-dotenv>=1.0
PyYAML>=6.0
jinja2>=3.1
weasyprint>=62.0
matplotlib>=3.8
mplsoccer>=1.2.4
pytest>=8.0
```

- [ ] **Step 3: Write `.gitignore`**

```
.venv/
__pycache__/
*.pyc
.env
data/processed/
outputs/
.pytest_cache/
```

- [ ] **Step 4: Write `.env.example`** (identical to `board-post-match-report`'s, plus the DVMS vars it omits there — fix that gap here)

```
SNOWFLAKE_ACCOUNT=
SNOWFLAKE_USER=
SNOWFLAKE_PASSWORD=
SNOWFLAKE_ROLE=
SNOWFLAKE_WAREHOUSE=
SNOWFLAKE_DATABASE=
SNOWFLAKE_SCHEMA=

# Optional authentication settings
SNOWFLAKE_AUTHENTICATOR=
SNOWFLAKE_PRIVATE_KEY_PATH=
SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=

# DVMS (Opta + Second Spectrum) connection — separate role/warehouse/database
DVMS_DATABASE=CAFC_DB
DVMS_ROLE=DEV_ROLE
DVMS_WAREHOUSE=DEVELOPMENT_WH

# Optional project settings
LOCAL_CACHE_ENABLED=true
LOCAL_CACHE_FORMAT=parquet

# Optional: override the shared DVMS tracking cache location (default ~/.cache/cafc-dvms)
CAFC_DVMS_CACHE=
```

- [ ] **Step 5: Vendor the Snowflake/config files byte-identical**

```bash
cp /Users/hashim.umarji/Projects/board-post-match-report/config/tables.yml \
   /Users/hashim.umarji/Projects/combined-post-match-report/config/tables.yml
cp /Users/hashim.umarji/Projects/board-post-match-report/sql/extracts/match_events.sql \
   /Users/hashim.umarji/Projects/board-post-match-report/sql/extracts/season_results.sql \
   /Users/hashim.umarji/Projects/combined-post-match-report/sql/extracts/
cp /Users/hashim.umarji/Projects/board-post-match-report/src/db/snowflake_connection.py \
   /Users/hashim.umarji/Projects/board-post-match-report/src/db/table_config.py \
   /Users/hashim.umarji/Projects/board-post-match-report/src/db/query_runner.py \
   /Users/hashim.umarji/Projects/combined-post-match-report/src/db/
```

- [ ] **Step 6: Verify the vendored files are byte-identical and importable**

```bash
diff /Users/hashim.umarji/Projects/board-post-match-report/src/db/query_runner.py \
     /Users/hashim.umarji/Projects/combined-post-match-report/src/db/query_runner.py
# Expected: no output (identical)

cd /Users/hashim.umarji/Projects/combined-post-match-report
python -c "from src.db.query_runner import QueryRunner; from src.db.table_config import TableConfig; print('ok')"
```
Expected: `ok` (a `ModuleNotFoundError` for `yaml`/`dotenv`/`pandas` means `pip install -r requirements.txt` into your interpreter first).

- [ ] **Step 7: Commit**

```bash
git add requirements.txt .gitignore .env.example config sql src/__init__.py src/db
git commit -m "Scaffold project and vendor Snowflake/config plumbing from board-post-match-report"
```

---

### Task 2: Vendor the DVMS package and its tests

**Files:**
- Create (vendored copy): `src/dvms/` (entire package tree)
- Create (vendored copy): `tests/dvms/` (entire test tree)
- Create: `src/dvms/VENDOR.md` (updated for this project)

**Interfaces:**
- Produces: `src.dvms.loaders.fixtures.resolve_fixture(opta_match_id: str, env_path: str = ".env") -> FixtureRef`, `src.dvms.preprocess.is_preprocessed(opta_match_id: str) -> bool`, `src.dvms.preprocess.preprocess_fixture(fixture_id: str, opta_match_id: str, every_n: int = 5, refresh: bool = False, env_path: str = ".env") -> Path` — used by Task 10/11's CLI.

- [ ] **Step 1: Copy the whole `src/dvms/` package byte-for-byte**

```bash
cp -R /Users/hashim.umarji/Projects/board-post-match-report/src/dvms/. \
      /Users/hashim.umarji/Projects/combined-post-match-report/src/dvms/
```

- [ ] **Step 2: Copy its test suite byte-for-byte**

```bash
cp -R /Users/hashim.umarji/Projects/board-post-match-report/tests/dvms/. \
      /Users/hashim.umarji/Projects/combined-post-match-report/tests/dvms/
```

- [ ] **Step 3: Update `src/dvms/VENDOR.md`'s canonical-copy line for this repo**

Open `src/dvms/VENDOR.md` and change only the first paragraph to read:

```markdown
# src/dvms — vendored DVMS (Opta + Second Spectrum) data package

Canonical copy: `board-post-match-report/src/dvms/`. This is a byte-identical
downstream copy (per that package's own convention — see its VENDOR.md).
Never edit this copy directly: make changes in the canonical repo, run
`pytest tests/dvms/` there, then re-copy here.

Last synced: 2026-07-29.
```

- [ ] **Step 4: Run the vendored DVMS test suite**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
pytest tests/dvms/ -v
```
Expected: either all tests pass, or the whole suite is skipped with a message pointing at `~/Desktop/dvms_samples` (the suite's `conftest.py` skips at module level when that machine-local sample directory is absent — this matches `board-post-match-report`'s own behavior and is not a regression to fix here).

- [ ] **Step 5: Commit**

```bash
git add src/dvms tests/dvms
git commit -m "Vendor DVMS (Opta + Second Spectrum) package and its test suite"
```

---

### Task 3: Vendor the visualisation and Impect/DVMS metrics modules

**Files:**
- Create (vendored copy): `src/report/palette.py`, `src/report/pitch.py`, `src/report/chart.py`, `src/report/chart_dvms.py`, `src/report/metrics.py`, `src/report/metrics_dvms.py`, `src/visualisation/badges.py`
- Create (vendored copy): `assets/badges/Charlton Logo.png`, `assets/badges/Swansea_City_A.F.C._logo.png`

**Interfaces:**
- Consumes: nothing new (these are self-contained, only depending on `src.dvms.*` from Task 2 and each other).
- Produces (all used by Task 4-6 and Task 10):
  - `src.report.metrics.match_meta(events) -> MatchMeta`, `.goal_events`, `.shot_events`, `.chance_sources`, `.zone_entries`, `.player_contributions`, `.team_stats`, `.season_context`, `.shot_summary`, `STAT_ROWS`, `STAT_GLOSS`
  - `src.report.metrics_dvms.load_match(fixture, env_path=".env") -> DvmsMatch`, `.team_stat_values`, `.territory_wave`, `.chance_sources_dvms`, `.avg_position_frame`, `.line_height_m`, `.zone_entries_dvms`, `.player_contributions_dvms`, `.goal_markers`, `.shot_events_dvms`, `.shot_summary_dvms`
  - `src.report.pitch.shot_map`, `.entry_map`, `.average_position_map`
  - `src.report.chart.momentum_chart`, `.chance_source_bars`
  - `src.report.chart_dvms.territory_chart`
  - `src.visualisation.badges.badge_data_uri(team_name: str) -> str | None`

- [ ] **Step 1: Copy the visualisation/metrics files byte-for-byte**

```bash
cd /Users/hashim.umarji/Projects
cp board-post-match-report/src/report/palette.py \
   board-post-match-report/src/report/pitch.py \
   board-post-match-report/src/report/chart.py \
   board-post-match-report/src/report/chart_dvms.py \
   board-post-match-report/src/report/metrics.py \
   board-post-match-report/src/report/metrics_dvms.py \
   combined-post-match-report/src/report/

cp board-post-match-report/src/visualisation/badges.py \
   combined-post-match-report/src/visualisation/badges.py

cp board-post-match-report/assets/badges/*.png \
   combined-post-match-report/assets/badges/
```

- [ ] **Step 2: Verify byte-identical and importable**

```bash
for f in palette.py pitch.py chart.py chart_dvms.py metrics.py metrics_dvms.py; do
  diff /Users/hashim.umarji/Projects/board-post-match-report/src/report/$f \
       /Users/hashim.umarji/Projects/combined-post-match-report/src/report/$f
done
# Expected: no output from any diff

cd /Users/hashim.umarji/Projects/combined-post-match-report
python -c "
from src.report import metrics, metrics_dvms, pitch, chart, chart_dvms, palette
from src.visualisation.badges import badge_data_uri
print('ok')
"
```
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/report/palette.py src/report/pitch.py src/report/chart.py src/report/chart_dvms.py \
        src/report/metrics.py src/report/metrics_dvms.py src/visualisation/badges.py assets/badges
git commit -m "Vendor visualisation, Impect metrics and DVMS metrics modules"
```

---

### Task 4: `metrics_combined.py` — combined match stats table

**Files:**
- Create: `src/report/metrics_combined.py`
- Test: `tests/test_metrics_combined.py`

**Interfaces:**
- Consumes: `src.report.metrics.team_stats(events, home, away) -> pd.DataFrame` (Task 3), `src.report.metrics_dvms.team_stat_values(match, side) -> dict` (Task 3), a `DvmsMatch`-like object exposing `.team_name_of(side: str) -> str`.
- Produces: `combined_team_stats(impect_events: pd.DataFrame, dvms_match) -> pd.DataFrame` — same shape as `metrics.team_stats`'s return (indexed by team name, one column per `STAT_ROWS` key), consumed by Task 10's `_stat_rows`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_metrics_combined.py`:

```python
from unittest.mock import patch

import pandas as pd

from src.report import metrics_combined


class _FakeDvmsMatch:
    """Stands in for metrics_dvms.DvmsMatch: combined_team_stats only calls
    team_name_of() on it directly, and metrics_dvms.team_stat_values() is
    monkeypatched below, so nothing else needs to be real."""

    def team_name_of(self, side: str) -> str:
        return {"home": "Charlton Athletic", "away": "Swansea City"}[side]


def _minimal_impect_events() -> pd.DataFrame:
    """One row per team with the exact columns metrics.team_stats reads."""
    return pd.DataFrame([
        {
            "squadName": "Charlton Athletic", "SUCCESSFUL_PASSES": 40, "UNSUCCESSFUL_PASSES": 10,
            "endAdjCoordinatesX": 5.0, "startAdjCoordinatesX": 0.0, "BALL_WIN_NUMBER": 3,
            "action": "PASS", "SHOT_XG": 0.3, "phase": "IN_POSSESSION",
            "startPitchPosition": "MIDFIELD", "OFFENSIVE_TOUCHES": 2,
            "WON_GROUND_DUELS": 4, "WON_AERIAL_DUELS": 2, "SECOND_BALL_WIN": 1,
            "SHOT_AT_GOAL_NUMBER": 1, "SHOT_AT_GOAL_NUMBER_ON_TARGET": 1,
            "PACKING_XG": 0.1, "POSTSHOT_XG": 0.25,
        },
        {
            "squadName": "Swansea City", "SUCCESSFUL_PASSES": 30, "UNSUCCESSFUL_PASSES": 15,
            "endAdjCoordinatesX": 3.0, "startAdjCoordinatesX": 0.0, "BALL_WIN_NUMBER": 5,
            "action": "PASS", "SHOT_XG": 0.5, "phase": "SET_PIECE",
            "startPitchPosition": "OPPONENT_BOX", "OFFENSIVE_TOUCHES": 1,
            "WON_GROUND_DUELS": 6, "WON_AERIAL_DUELS": 3, "SECOND_BALL_WIN": 2,
            "SHOT_AT_GOAL_NUMBER": 2, "SHOT_AT_GOAL_NUMBER_ON_TARGET": 1,
            "PACKING_XG": 0.2, "POSTSHOT_XG": 0.45,
        },
    ])


def test_combined_team_stats_overrides_possession_with_dvms_tracked_value():
    events = _minimal_impect_events()
    dvms_match = _FakeDvmsMatch()

    with patch.object(metrics_combined.metrics_dvms, "team_stat_values") as mocked:
        mocked.side_effect = lambda match, side: {
            "home": {"possession_pct": 61.5},
            "away": {"possession_pct": 38.5},
        }[side]
        combined = metrics_combined.combined_team_stats(events, dvms_match)

    assert combined.loc["Charlton Athletic", "possession_pct"] == 61.5
    assert combined.loc["Swansea City", "possession_pct"] == 38.5
    # Every other Impect-sourced column is untouched.
    assert combined.loc["Charlton Athletic", "successful_passes"] == 40
    assert combined.loc["Swansea City", "won_aerial_duels"] == 3
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
pytest tests/test_metrics_combined.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.report.metrics_combined'`.

- [ ] **Step 3: Write `src/report/metrics_combined.py`**

```python
"""Combines Impect and DVMS metrics into single, best-source-per-metric
panels for the combined board post-match report. Reuses metrics.py
(Impect) and metrics_dvms.py (DVMS) unmodified — this module only decides,
per panel, which source's number to show and merges/reranks where a panel
genuinely needs both.
"""

from __future__ import annotations

import pandas as pd

from src.report import metrics as impect_metrics
from src.report import metrics_dvms


def combined_team_stats(impect_events: pd.DataFrame, dvms_match) -> pd.DataFrame:
    """The 13-row match-stats table (metrics.STAT_ROWS / STAT_GLOSS,
    unmodified), with every value from Impect except ``possession_pct``,
    which comes from DVMS's tracked ball-touch share — the one row where
    tracking beats a pass-count proxy (see the design spec).

    Returns the same shape as metrics.team_stats: a DataFrame indexed by
    team name, one column per STAT_ROWS key.
    """
    meta = impect_metrics.match_meta(impect_events)
    home, away = meta.home_team, meta.away_team
    stats = impect_metrics.team_stats(impect_events, home, away).copy()

    for side in ("home", "away"):
        team = dvms_match.team_name_of(side)
        stats.loc[team, "possession_pct"] = metrics_dvms.team_stat_values(dvms_match, side)["possession_pct"]
    return stats
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
pytest tests/test_metrics_combined.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/report/metrics_combined.py tests/test_metrics_combined.py
git commit -m "Add combined_team_stats: Impect stats table with DVMS-tracked possession"
```

---

### Task 5: `metrics_combined.py` — % through / over / around split

**Files:**
- Modify: `src/report/metrics_combined.py`
- Test: `tests/test_metrics_combined.py`

**Interfaces:**
- Consumes: `src.dvms.metrics.line_breaks.line_breaking_passes(events, tracking, pitch_meta, lineups, team_id, opponent_team_id, opponent_is_home) -> pd.DataFrame` with a `style` column of `"through"`/`"over"`/`"around"` and an `event_id` column (Task 2). A `DvmsMatch`-like object exposing `.events`, `.frames`, `.meta`, `.f7.lineups`, `.team_id_of(side) -> str`.
- Produces: `line_break_style_split(match, side: str) -> dict[str, float]` with keys `"through"`, `"over"`, `"around"` (percentages summing to ~100 when `n > 0`) and `"n"` (int count), consumed by Task 10's `side()` closure and Task 9's template caption.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics_combined.py`:

```python
class _FakeDvmsMatchForBreaks:
    def __init__(self):
        self.events = pd.DataFrame()   # unused: line_breaking_passes is mocked below
        self.frames = pd.DataFrame()
        self.meta = object()

    def team_id_of(self, side: str) -> str:
        return {"home": "H1", "away": "A1"}[side]

    class _F7:
        lineups = pd.DataFrame()

    f7 = _F7()


def test_line_break_style_split_percentages():
    match = _FakeDvmsMatchForBreaks()
    breaks = pd.DataFrame([
        {"event_id": 1, "style": "through"},
        {"event_id": 1, "style": "over"},   # same pass breaking a 2nd line — dedup keeps first row
        {"event_id": 2, "style": "over"},
        {"event_id": 3, "style": "around"},
        {"event_id": 4, "style": "through"},
    ])

    with patch.object(metrics_combined, "line_breaking_passes", return_value=breaks) as mocked:
        result = metrics_combined.line_break_style_split(match, "home")

    mocked.assert_called_once_with(
        events=match.events, tracking=match.frames, pitch_meta=match.meta,
        lineups=match.f7.lineups, team_id="H1", opponent_team_id="A1",
        opponent_is_home=False,
    )
    assert result["n"] == 3  # 4 event_ids, deduped to 3 unique
    assert result["through"] == pytest.approx(2 / 3 * 100)
    assert result["over"] == pytest.approx(1 / 3 * 100)
    assert result["around"] == pytest.approx(0.0)


def test_line_break_style_split_handles_no_breaks():
    match = _FakeDvmsMatchForBreaks()
    with patch.object(metrics_combined, "line_breaking_passes", return_value=pd.DataFrame()):
        result = metrics_combined.line_break_style_split(match, "away")
    assert result == {"through": 0.0, "over": 0.0, "around": 0.0, "n": 0}
```

Add `import pytest` at the top of the test file.

- [ ] **Step 2: Run it to verify it fails**

```bash
pytest tests/test_metrics_combined.py -v
```
Expected: FAIL — `AttributeError: module 'src.report.metrics_combined' has no attribute 'line_break_style_split'`.

- [ ] **Step 3: Add to `src/report/metrics_combined.py`**

```python
from src.dvms.metrics.line_breaks import line_breaking_passes


def line_break_style_split(match, side: str) -> dict[str, float]:
    """Of this team's completed passes that broke an opposition tactical
    line (defence, midfield or attack — see line_breaks.py), the % that did
    so through, over, or around that line: DVMS tracking's answer to "how
    did they get in", shown as a caption under the (Impect-sourced) final
    third & box entries map.

    No ready-made %-split aggregator exists in line_breaks.py — only a
    passer x receiver combination_matrix — so this is new. A pass that
    breaks two lines appears twice in line_breaking_passes' output; dedup on
    event_id (keeping its first-encountered style, matching how
    combination_matrix already dedupes) before taking the split.
    """
    opponent_side = "away" if side == "home" else "home"
    breaks = line_breaking_passes(
        events=match.events,
        tracking=match.frames,
        pitch_meta=match.meta,
        lineups=match.f7.lineups,
        team_id=match.team_id_of(side),
        opponent_team_id=match.team_id_of(opponent_side),
        opponent_is_home=(opponent_side == "home"),
    )
    if breaks.empty:
        return {"through": 0.0, "over": 0.0, "around": 0.0, "n": 0}

    uniq = breaks.drop_duplicates(subset="event_id")
    counts = uniq["style"].value_counts()
    n = int(len(uniq))
    return {
        "through": float(counts.get("through", 0)) / n * 100,
        "over": float(counts.get("over", 0)) / n * 100,
        "around": float(counts.get("around", 0)) / n * 100,
        "n": n,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_metrics_combined.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/report/metrics_combined.py tests/test_metrics_combined.py
git commit -m "Add line_break_style_split: DVMS through/over/around breakdown"
```

---

### Task 6: `metrics_combined.py` — blended player contribution score

**Files:**
- Modify: `src/report/metrics_combined.py`
- Test: `tests/test_metrics_combined.py`

**Interfaces:**
- Consumes: `src.report.metrics.player_contributions(events, top_n) -> pd.DataFrame` (columns `playerName, squadName, passes, ground, aerial, ball_wins, shots, xg, xt, surname`), `src.report.metrics_dvms.player_contributions_dvms(match, top_n) -> pd.DataFrame` (columns incl. `name, distance, top_speed`) — both from Task 3.
- Produces: `blended_player_contributions(impect_events, dvms_match, top_n=10) -> pd.DataFrame` — same columns as `metrics.player_contributions`'s output (`playerName, squadName, passes, ground, aerial, ball_wins, shots, xg, xt, surname`) plus `composite`, sorted by `composite` descending, consumed by Task 10 (fed straight into `render_v2`-style `_contribution_rows`, which only reads the original Impect columns — the blended ranking changes *which* players appear and in what order, not what's displayed about them).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics_combined.py`:

```python
def test_blended_player_contributions_ranks_by_composite_and_keeps_impect_columns():
    impect_df = pd.DataFrame([
        {"playerName": "Alfie May", "squadName": "Charlton Athletic", "surname": "May",
         "passes": 20, "ground": 2, "aerial": 5, "ball_wins": 1, "shots": 3, "xg": 0.9, "xt": 0.30},
        {"playerName": "Terrell Egbri", "squadName": "Charlton Athletic", "surname": "Egbri",
         "passes": 60, "ground": 4, "aerial": 0, "ball_wins": 3, "shots": 0, "xg": 0.0, "xt": 0.05},
    ])
    dvms_df = pd.DataFrame([
        {"name": "May", "distance": 9500.0, "top_speed": 31.2},
        {"name": "Egbri", "distance": 11200.0, "top_speed": 28.4},
    ])

    with patch.object(metrics_combined.impect_metrics, "player_contributions", return_value=impect_df), \
         patch.object(metrics_combined.metrics_dvms, "player_contributions_dvms", return_value=dvms_df):
        result = metrics_combined.blended_player_contributions(pd.DataFrame(), object(), top_n=10)

    assert list(result.columns[:9]) == [
        "playerName", "squadName", "surname", "passes", "ground", "aerial", "ball_wins", "shots", "xg",
    ] or set(["playerName", "squadName", "surname", "passes", "ground", "aerial", "ball_wins", "shots", "xg", "xt", "composite"]) <= set(result.columns)
    assert "composite" in result.columns
    assert len(result) == 2
    # composite is descending
    assert result.iloc[0]["composite"] >= result.iloc[1]["composite"]


def test_blended_player_contributions_handles_unmatched_dvms_player():
    impect_df = pd.DataFrame([
        {"playerName": "Alfie May", "squadName": "Charlton Athletic", "surname": "May",
         "passes": 20, "ground": 2, "aerial": 5, "ball_wins": 1, "shots": 3, "xg": 0.9, "xt": 0.30},
    ])
    dvms_df = pd.DataFrame(columns=["name", "distance", "top_speed"])  # no physical match at all

    with patch.object(metrics_combined.impect_metrics, "player_contributions", return_value=impect_df), \
         patch.object(metrics_combined.metrics_dvms, "player_contributions_dvms", return_value=dvms_df):
        result = metrics_combined.blended_player_contributions(pd.DataFrame(), object(), top_n=10)

    assert len(result) == 1
    assert result.iloc[0]["composite"] == 0.0  # only component with any signal (xt) has zero std across n=1
```

- [ ] **Step 2: Run it to verify it fails**

```bash
pytest tests/test_metrics_combined.py -v
```
Expected: FAIL — `AttributeError: module 'src.report.metrics_combined' has no attribute 'blended_player_contributions'`.

- [ ] **Step 3: Add to `src/report/metrics_combined.py`**

```python
def blended_player_contributions(impect_events: pd.DataFrame, dvms_match, top_n: int = 10) -> pd.DataFrame:
    """Composite contribution ranking blending Impect on-ball value with
    DVMS physical output.

    Player identity is joined on lower-cased surname — there is no shared
    player id between Impect and Opta in this codebase (unlike the
    CAFC_PLAYER_ID cross-provider resolution DATA_MODEL.md documents for
    Impect-to-canonical joins; no Impect-to-Opta equivalent exists). A
    duplicate surname within one team's squad would collide silently; this
    is a known limitation, not yet hit in practice.

    Both source functions are called with a large top_n so the join has
    the full squads to work with, not just each source's own top-10 cut —
    re-ranking happens here, after blending, then the result is cut to
    ``top_n``.

    Composite = weighted sum of z-scored components: 40% Impect xT
    (attacking value added, the same metric both existing reports already
    rank by), 15% successful passes, 15% ground+aerial duels won, 10% xG,
    10% distance covered, 10% top speed (the last two from DVMS Second
    Spectrum physical data — the only components tracking-derived).
    Weights are a starting point, expected to need visual tuning against
    known matches; not treated as fixed science.
    """
    impect_all = impect_metrics.player_contributions(impect_events, top_n=1000)
    dvms_all = metrics_dvms.player_contributions_dvms(dvms_match, top_n=1000)

    impect_all = impect_all.assign(_key=impect_all["surname"].str.lower())
    dvms_physical = dvms_all.assign(_key=dvms_all["name"].str.lower())[["_key", "distance", "top_speed"]]

    merged = impect_all.merge(dvms_physical, on="_key", how="left").drop(columns="_key")

    def _z(s: pd.Series) -> pd.Series:
        std = s.std(ddof=0)
        return (s - s.mean()) / std if std else pd.Series(0.0, index=s.index)

    dist = merged["distance"].fillna(merged["distance"].mean())
    speed = merged["top_speed"].fillna(merged["top_speed"].mean())

    merged["composite"] = (
        0.40 * _z(merged["xt"])
        + 0.15 * _z(merged["passes"])
        + 0.15 * _z(merged["ground"] + merged["aerial"])
        + 0.10 * _z(merged["xg"])
        + 0.10 * _z(dist)
        + 0.10 * _z(speed)
    )
    return merged.sort_values("composite", ascending=False).head(top_n).reset_index(drop=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_metrics_combined.py -v
```
Expected: all PASS. If the column-list assertion in the first test is awkward to satisfy exactly, simplify it to the `set(...) <= set(result.columns)` branch only — the point is confirming the original Impect columns survive untouched, not enforcing a column order.

- [ ] **Step 5: Commit**

```bash
git add src/report/metrics_combined.py tests/test_metrics_combined.py
git commit -m "Add blended_player_contributions: composite Impect+DVMS ranking"
```

---

### Task 7: Fixture-linking validation

**Files:**
- Create: `src/report/render_combined.py` (this task only adds the validation piece; Task 10 fills in the rest)
- Test: `tests/test_render_combined.py`

**Interfaces:**
- Produces: `FixtureMismatchError(ValueError)`, `_assert_same_fixture(impect_meta, dvms_fixture) -> None` (raises on mismatch, returns `None` on agreement) — called from `build_context` in Task 10, before any Snowflake/DVMS data is used for rendering.

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_combined.py`:

```python
from types import SimpleNamespace

import pandas as pd
import pytest

from src.report.render_combined import FixtureMismatchError, _assert_same_fixture


def _impect_meta(home="Charlton Athletic", away="Swansea City", kickoff="2026-01-10"):
    return SimpleNamespace(home_team=home, away_team=away, kickoff=pd.Timestamp(kickoff, tz="UTC"))


def _dvms_fixture(home="Charlton Athletic", away="Swansea City", match_date="2026-01-10"):
    return SimpleNamespace(home_team=home, away_team=away, match_date=pd.Timestamp(match_date))


def test_matching_fixture_passes_silently():
    _assert_same_fixture(_impect_meta(), _dvms_fixture())  # no exception


def test_matching_fixture_is_case_insensitive():
    _assert_same_fixture(_impect_meta(home="CHARLTON ATHLETIC"), _dvms_fixture(home="charlton athletic"))


def test_mismatched_teams_raises():
    with pytest.raises(FixtureMismatchError):
        _assert_same_fixture(_impect_meta(away="Swansea City"), _dvms_fixture(away="Millwall"))


def test_mismatched_date_raises():
    with pytest.raises(FixtureMismatchError):
        _assert_same_fixture(_impect_meta(kickoff="2026-01-10"), _dvms_fixture(match_date="2026-01-11"))
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
pytest tests/test_render_combined.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'src.report.render_combined'`.

- [ ] **Step 3: Create `src/report/render_combined.py` with just the validation piece**

```python
"""Assemble the combined Impect + DVMS single-page board report (HTML + PDF).

Sources each panel from whichever provider is authoritative for that metric
(see docs/superpowers/specs/2026-07-29-combined-board-post-match-report-design.md).
Template, CSS and panel layout are copied byte-for-byte from
board-post-match-report's post_match_report_v2.html.j2 — only the data
feeding each panel differs.
"""

from __future__ import annotations


class FixtureMismatchError(ValueError):
    """Raised when the given Impect match and DVMS fixture don't look like
    the same real-world game — team names or kickoff date disagree."""


def _normalize(name: str) -> str:
    return name.strip().lower()


def _assert_same_fixture(impect_meta, dvms_fixture) -> None:
    impect_teams = {_normalize(impect_meta.home_team), _normalize(impect_meta.away_team)}
    dvms_teams = {_normalize(dvms_fixture.home_team), _normalize(dvms_fixture.away_team)}
    if impect_teams != dvms_teams:
        raise FixtureMismatchError(
            f"Impect match {impect_meta.home_team} v {impect_meta.away_team} does not match "
            f"DVMS fixture {dvms_fixture.home_team} v {dvms_fixture.away_team}."
        )
    impect_date = impect_meta.kickoff.date()
    dvms_date = dvms_fixture.match_date.date()
    if impect_date != dvms_date:
        raise FixtureMismatchError(
            f"Impect match date {impect_date} does not match DVMS fixture date {dvms_date} "
            f"({impect_meta.home_team} v {impect_meta.away_team})."
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_render_combined.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/report/render_combined.py tests/test_render_combined.py
git commit -m "Add fixture-linking validation for the combined report"
```

---

### Task 8: Copy the v2 template verbatim

**Files:**
- Create: `src/report/templates/post_match_report_combined.html.j2` (exact copy, no edits yet)

**Interfaces:**
- Produces: a Jinja2 template file, to be edited in Task 9.

- [ ] **Step 1: Copy the template**

```bash
cp /Users/hashim.umarji/Projects/board-post-match-report/src/report/templates/post_match_report_v2.html.j2 \
   /Users/hashim.umarji/Projects/combined-post-match-report/src/report/templates/post_match_report_combined.html.j2
```

- [ ] **Step 2: Verify it's byte-identical right now**

```bash
diff /Users/hashim.umarji/Projects/board-post-match-report/src/report/templates/post_match_report_v2.html.j2 \
     /Users/hashim.umarji/Projects/combined-post-match-report/src/report/templates/post_match_report_combined.html.j2
```
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add src/report/templates/post_match_report_combined.html.j2
git commit -m "Copy v2 template as the starting point for the combined report"
```

---

### Task 9: Edit the template for the combined panels only

**Files:**
- Modify: `src/report/templates/post_match_report_combined.html.j2`

**Interfaces:**
- Consumes: new context keys this task's edits introduce — `territory_img` (already the DVMS-report convention, just needs wiring into this template), and `entries_style_split` on each `side` dict (new, `{"through": float, "over": float, "around": float, "n": int}` from Task 5). Both are produced by Task 10's `build_context`.

- [ ] **Step 1: Swap the momentum panel for territory**

In `<title>` area this doesn't apply, but in the "MOMENTUM + WHERE CHANCES CAME FROM" row, replace:

```html
    <div class="panel">
      <div class="panel-label"><span class="mark"></span>Momentum</div>
      <div class="chartbox"><img src="{{ momentum_img }}" alt=""></div>
      <div class="note">Above the line = {{ meta.charlton_team }}, below = {{ meta.opponent_team }} &middot; circles = goals, triangles = subs, dotted lead = wave value &middot; square-root scale keeps quiet spells visible</div>
    </div>
```

with:

```html
    <div class="panel">
      <div class="panel-label"><span class="mark"></span>Territory (tracked)</div>
      <div class="chartbox"><img src="{{ territory_img }}" alt=""></div>
      <div class="note">Above the line = {{ meta.charlton_team }}, below = {{ meta.opponent_team }} &middot; rolling mean tracked ball position, in metres &middot; circles = goals &middot; from Second Spectrum tracking (via DVMS)</div>
    </div>
```

- [ ] **Step 2: Update the average positions panel's caption**

Replace:

```html
      <div class="key">
        <span>Both attacking upfield &middot; dashed line marks average defensive line height &middot; based on each player's own touches during settled possession, not tracking data</span>
      </div>
```

with:

```html
      <div class="key">
        <span>Both attacking upfield &middot; dashed line marks average defensive line height &middot; from Second Spectrum tracking (in possession), via DVMS</span>
      </div>
```

- [ ] **Step 3: Add the through/over/around split under the entries panel's key**

In the "ENTRIES + CONTRIBUTIONS" row, inside the entries `.panel`, after the existing `<div class="key">...</div>` block, add one more caption line reusing the existing `.note` class (already styled, no CSS change needed):

```html
      <div class="key">
        <span>{{ sw_arrow('#5c7a4a') }}Pass</span>
        <span>{{ sw_arrow('#c0892d') }}Carry</span>
        <span>{{ sw_arrow('#a8685f') }}Lost</span>
        <span class="sep">|</span>
        <span>{{ sw_lines() }}Thickness = <b>threat gained</b></span>
        <span class="sep">|</span>
        <span>Attacking left to right</span>
      </div>
      <div class="note">
        {% for s in sides %}
        {{ s.team }} line-breaking passes (Opta/Second Spectrum tracking): <b>{{ '%.0f'|format(s.entries_style_split.through) }}%</b> through &middot; <b>{{ '%.0f'|format(s.entries_style_split.over) }}%</b> over &middot; <b>{{ '%.0f'|format(s.entries_style_split.around) }}%</b> around ({{ s.entries_style_split.n }} passes){% if not loop.last %} &middot; {% endif %}
        {% endfor %}
      </div>
```

- [ ] **Step 4: Update the footer credits**

Replace:

```html
    <span>Data: IMPECT (via CAFC_TEST_ANALYSIS), single-match sample</span>
```

with:

```html
    <span>Data: IMPECT (via CAFC_TEST_ANALYSIS) + Opta/Second Spectrum (via DVMS)</span>
```

- [ ] **Step 5: Diff the CSS block against v2 to confirm it's untouched**

```bash
diff <(sed -n '9,152p' /Users/hashim.umarji/Projects/board-post-match-report/src/report/templates/post_match_report_v2.html.j2) \
     <(sed -n '9,152p' /Users/hashim.umarji/Projects/combined-post-match-report/src/report/templates/post_match_report_combined.html.j2)
```
Expected: no output — the `<style>` block (lines 9-152 in the original) must be byte-identical; only panel markup below it changed. If line numbers shifted from earlier edits, adjust the range to match the `<style>...</style>` boundaries in your copy and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/report/templates/post_match_report_combined.html.j2
git commit -m "Wire combined-report panels into the template: territory, tracked avg positions, line-break split, footer credits"
```

---

### Task 10: `render_combined.py` — build_context, render_report, and CLI

**Files:**
- Modify: `src/report/render_combined.py` (add everything beyond the Task 7 validation)
- Create: `generate_report_combined.py`

**Interfaces:**
- Consumes: everything produced by Tasks 1-9.
- Produces: `build_context(impect_match_id: int, dvms_opta_match_id: str, refresh: bool = False) -> dict`, `render_report(impect_match_id: int, dvms_opta_match_id: str, output_dir=DEFAULT_OUTPUT_DIR, formats=("html","pdf"), refresh=False) -> dict[str, Path]` — the CLI's entry point.

- [ ] **Step 1: Extend `src/report/render_combined.py`**

Add these imports at the top (after the existing `from __future__ import annotations`):

```python
import datetime as dt
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.db.query_runner import QueryRunner
from src.dvms.loaders.fixtures import resolve_fixture
from src.report import chart, chart_dvms, metrics, metrics_combined, metrics_dvms, palette, pitch
from src.report.metrics import STAT_GLOSS, STAT_ROWS
from src.visualisation.badges import badge_data_uri

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"
```

Then append the rest of the file, after the `FixtureMismatchError` / `_normalize` / `_assert_same_fixture` block already there from Task 7:

```python
def _fmt_stat(key: str, value: float) -> str:
    if key.endswith("_pct"):
        return f"{value:.0f}%"
    if "xg" in key:
        return f"{value:.2f}"
    return f"{int(round(value))}"


def _stat_rows(stats: Any, home: str, away: str, charlton: str) -> list[dict[str, Any]]:
    rows = []
    last_group = None
    for group, key, label in STAT_ROWS:
        h = float(stats.loc[home, key])
        a = float(stats.loc[away, key])
        total = h + a
        h_share = (h / total * 100) if total else 50.0
        rows.append({
            "group": group if group != last_group else None,
            "label": label,
            "home": _fmt_stat(key, h),
            "away": _fmt_stat(key, a),
            "home_share": round(h_share, 1),
            "away_share": round(100 - h_share, 1),
            "home_wins": h > a,
            "away_wins": a > h,
            "home_is_charlton": home == charlton,
            "gloss": STAT_GLOSS.get(key),
        })
        last_group = group
    return rows


def _contribution_rows(df: Any, charlton: str) -> list[dict[str, Any]]:
    return [
        {
            "name": r["surname"],
            "is_charlton": r["squadName"] == charlton,
            "passes": int(r["passes"]),
            "ground": int(r["ground"]),
            "aerial": int(r["aerial"]),
            "ball_wins": int(r["ball_wins"]),
            "shots": int(r["shots"]),
            "xg": f"{r['xg']:.2f}",
            "xt": f"{r['xt']:.2f}",
        }
        for _, r in df.iterrows()
    ]


def build_context(impect_match_id: int, dvms_opta_match_id: str, refresh: bool = False) -> dict[str, Any]:
    runner = QueryRunner()
    events = runner.load_match_events(impect_match_id, refresh=refresh)
    impect_meta = metrics.match_meta(events)

    dvms_fixture = resolve_fixture(dvms_opta_match_id)
    _assert_same_fixture(impect_meta, dvms_fixture)
    dvms_match = metrics_dvms.load_match(dvms_fixture)

    charlton, opponent = impect_meta.charlton_team, impect_meta.opponent_team

    stats = metrics_combined.combined_team_stats(events, dvms_match)
    goals = metrics.goal_events(events)
    shots = metrics.shot_events(events)
    entries = {team: metrics.zone_entries(events, team) for team in (charlton, opponent)}
    entries_style_split = {
        dvms_match.team_name_of(side): metrics_combined.line_break_style_split(dvms_match, side)
        for side in ("home", "away")
    }
    wave = metrics_dvms.territory_wave(dvms_match)
    dvms_goal_markers = metrics_dvms.goal_markers(dvms_match)
    season = metrics.season_context(runner.load_season_results(refresh=refresh), charlton, impect_meta.kickoff)
    contributions = metrics_combined.blended_player_contributions(events, dvms_match, top_n=10)
    chances = metrics.chance_sources(events, impect_meta.home_team, impect_meta.away_team)

    def _dvms_side_for(team: str) -> str:
        return "home" if team == dvms_match.team_name_of("home") else "away"

    avg_pos_in_possession = {
        team: metrics_dvms.avg_position_frame(dvms_match, _dvms_side_for(team), "in_possession")
        for team in (charlton, opponent)
    }
    line_height_in_possession = {
        team: metrics_dvms.line_height_m(dvms_match, _dvms_side_for(team), "in_possession")
        for team in (charlton, opponent)
    }

    max_threat = max((float(e["threat"].max()) if not e.empty else 0.0) for e in entries.values())

    def side(team: str) -> dict[str, Any]:
        is_charlton = team == charlton
        color = palette.CHARLTON_RED if is_charlton else palette.OPPONENT_GREY
        return {
            "team": team,
            "is_charlton": is_charlton,
            "badge": badge_data_uri(team),
            "goals": impect_meta.charlton_goals if is_charlton else impect_meta.opponent_goals,
            "scorers": [{"player": g.player, "minute": g.minute_label} for g in goals if g.team == team],
            "shot_map": pitch.shot_map(shots.loc[shots["squadName"] == team], color),
            "shot_summary": metrics.shot_summary(shots, team),
            "entries": pitch.entry_map(entries[team], max_threat),
            "entries_style_split": entries_style_split[team],
            "avg_pos_map": pitch.average_position_map(
                avg_pos_in_possession[team], color, line_height_in_possession[team], vertical=True),
        }

    context: dict[str, Any] = {
        "generated_date": dt.date.today().strftime("%d %B %Y"),
        "sides": [side(impect_meta.home_team), side(impect_meta.away_team)],
        "meta": {
            "charlton_team": charlton,
            "opponent_team": opponent,
            "home_team": impect_meta.home_team,
            "away_team": impect_meta.away_team,
            "venue": "Away" if charlton == impect_meta.away_team else "Home",
            "competition": impect_meta.competition,
            "season": impect_meta.season,
            "date": impect_meta.kickoff.strftime("%d/%m/%Y"),
            "result": impect_meta.result,
        },
        "form": [
            {"result": r, "opponent": o, "is_last": i == len(season.form) - 1}
            for i, (r, o) in enumerate(zip(season.form, season.form_opponents))
        ],
        "stat_rows": _stat_rows(stats, impect_meta.home_team, impect_meta.away_team, charlton),
        "territory_img": chart_dvms.territory_chart(wave, dvms_goal_markers, charlton, opponent),
        "chance_source_img": chart.chance_source_bars(chances, charlton, opponent),
        "contributions": _contribution_rows(contributions, charlton),
        "match_id": impect_match_id,
    }
    return context


def render_report(impect_match_id: int, dvms_opta_match_id: str,
                   output_dir: Path | str = DEFAULT_OUTPUT_DIR,
                   formats: tuple[str, ...] = ("html", "pdf"), refresh: bool = False) -> dict[str, Path]:
    context = build_context(impect_match_id, dvms_opta_match_id, refresh=refresh)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    html = env.get_template("post_match_report_combined.html.j2").render(**context)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = (f"post_match_report_combined_{context['meta']['charlton_team']}"
            f"_v_{context['meta']['opponent_team']}"
            f"_{context['meta']['date'].replace('/', '-')}").replace(" ", "_")

    outputs: dict[str, Path] = {}
    if "html" in formats:
        html_path = output_dir / f"{slug}.html"
        html_path.write_text(html, encoding="utf-8")
        outputs["html"] = html_path
    if "pdf" in formats:
        from weasyprint import HTML

        pdf_path = output_dir / f"{slug}.pdf"
        HTML(string=html, base_url=str(PROJECT_ROOT)).write_pdf(str(pdf_path))
        outputs["pdf"] = pdf_path
    return outputs
```

- [ ] **Step 2: Write `generate_report_combined.py`**

```python
#!/usr/bin/env python3
"""Entry point: generate the combined Impect + DVMS board post-match report.

    python generate_report_combined.py --impect-match-id 207019 --dvms-match-id 2566913
    python generate_report_combined.py --impect-match-id 207019 --dvms-match-id 2566913 --html-only

Both ids must refer to the same real-world fixture — the tool aborts with a
clear error if the team names or kickoff date disagree between the two
sources (see src.report.render_combined._assert_same_fixture).
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--impect-match-id", type=int, required=True,
                        help="IMPECT_EVENTS_STAGING matchId")
    parser.add_argument("--dvms-match-id", required=True,
                        help="DVMS/Opta match id (see: python -m src.dvms.cli list-fixtures)")
    parser.add_argument("--refresh", action="store_true",
                        help="Bypass the local parquet cache and repull Impect events from Snowflake.")
    parser.add_argument("--html-only", action="store_true")
    parser.add_argument("--pdf-only", action="store_true")
    args = parser.parse_args()

    from src.dvms.loaders.fixtures import resolve_fixture
    from src.dvms.preprocess import is_preprocessed, preprocess_fixture

    fixture = resolve_fixture(args.dvms_match_id)
    if not is_preprocessed(fixture.opta_match_id):
        print(f"cache not ready for {fixture.opta_match_id}; preprocessing "
              "(first run downloads ~28MB of tracking) ...")
        preprocess_fixture(fixture.fixture_id, fixture.opta_match_id)

    from src.report.render_combined import render_report

    formats = ("html",) if args.html_only else (("pdf",) if args.pdf_only else ("html", "pdf"))
    outputs = render_report(args.impect_match_id, fixture.opta_match_id, formats=formats, refresh=args.refresh)
    for fmt, path in outputs.items():
        print(f"Wrote {fmt.upper()}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
pytest tests/ -v --ignore=tests/dvms
```
Expected: all PASS (the Task 4-7 unit tests, which don't touch Snowflake/DVMS live data).

- [ ] **Step 4: Smoke-test that the module imports and the CLI's `--help` works (no live Snowflake needed)**

```bash
python -c "from src.report.render_combined import build_context, render_report; print('ok')"
python generate_report_combined.py --help
```
Expected: `ok`, then the argparse help text with both required `--impect-match-id` / `--dvms-match-id` flags listed.

- [ ] **Step 5: Commit**

```bash
git add src/report/render_combined.py generate_report_combined.py
git commit -m "Wire up combined report build_context, render_report and CLI entry point"
```

---

### Task 11: End-to-end run against a real fixture and layout verification

**Files:** none (verification task).

**Interfaces:** none — this exercises Tasks 1-10 together against live Snowflake/DVMS data.

- [ ] **Step 1: Find a matching Impect match id and DVMS Opta match id for the same real fixture**

```bash
cd /Users/hashim.umarji/Projects/combined-post-match-report
python -c "
from src.db.query_runner import QueryRunner
print(QueryRunner().list_team_fixtures().head(10))
" 2>&1 | head -20 || echo "list_team_fixtures needs sql/extracts/charlton_fixtures.sql — copy it too if this fails: cp /Users/hashim.umarji/Projects/board-post-match-report/sql/extracts/charlton_fixtures.sql sql/extracts/"
python -m src.dvms.cli list-fixtures
```
Cross-reference the two outputs by team names and date to find one fixture with data on both sides (e.g. Charlton v Swansea City, the fixture used throughout `board-post-match-report`'s own docs — check its Impect `matchId` via the first command's output and DVMS `OPTA_MATCH_ID` via the second).

- [ ] **Step 2: Render the report**

```bash
python generate_report_combined.py --impect-match-id <impect_id> --dvms-match-id <opta_id>
```
Expected: two `Wrote HTML: ...` / `Wrote PDF: ...` lines, no `FixtureMismatchError`. If preprocessing runs (first time for that DVMS match), it may take several minutes.

- [ ] **Step 3: Verify the page renders on one A4 sheet with no overflow**

```bash
python -c "
from pypdf import PdfReader
import glob
path = sorted(glob.glob('outputs/*.pdf'))[-1]
r = PdfReader(path)
print('pages:', len(r.pages))
"
```
Expected: `pages: 1`. If it's more than 1, the entries panel's new caption line (Task 9, Step 3) pushed the page over — shorten that caption (e.g. drop the raw pass count `({{ s.entries_style_split.n }} passes)`) and re-render.

(If `pypdf` isn't installed: `pip install pypdf` first, or just open the PDF and check visually.)

- [ ] **Step 4: Open the HTML output and visually confirm every panel's data source matches the design**

Open `outputs/post_match_report_combined_*.html` in a browser and check:
- Match stats table shows 13 rows, unchanged labels/groups.
- Shot map circles are sized by Impect xG (compare a shot's xG against the equivalent `board-post-match-report` v2 report for the same fixture, if available — should match exactly).
- "Territory (tracked)" panel shows a metres-based y-axis (`+20m` style ticks), not a pxT-based one.
- "Where the chances came from" panel is unchanged from v2 (Impect phase tags).
- Average positions panel shows one pitch per side, dashed line height, caption says "Second Spectrum tracking".
- Final third & box entries panel shows both pass and carry arrows (olive vs amber), plus the new through/over/around caption line.
- Player contribution table lists 10 players with the same 8 columns as v2 (Player/Passes/Ground/Aerial/Wins/Shots/xG/xT) — the *ranking*, not the columns, is where the DVMS blend shows up.
- Footer credits both providers.

- [ ] **Step 5: Confirm the CSS is unchanged from v2 in the final artifact too**

```bash
diff <(python3 -c "
import re
html = open('$(ls -t outputs/*.html | head -1)').read()
print(re.search(r'<style>.*?</style>', html, re.S).group())
") <(python3 -c "
import re
html = open('/Users/hashim.umarji/Projects/board-post-match-report/src/report/templates/post_match_report_v2.html.j2').read()
print(re.search(r'<style>.*?</style>', html, re.S).group())
")
```
Expected: no output.

- [ ] **Step 6: No commit needed** — this task is verification only. If Step 3 required a caption edit, that edit belongs to a fresh commit on top of Task 9's:

```bash
git add src/report/templates/post_match_report_combined.html.j2
git commit -m "Trim entries caption to keep the combined report on one A4 page"
```
(only if Step 3 actually required a change).

---

## Self-Review Notes

- **Spec coverage**: every panel-sourcing decision in the design spec has a task (Task 4: possession/stats; Task 5: through/over/around; Task 6: player contribution; shot map/chance sources/entries/average-positions are direct reuse via Task 3 vendoring + Task 10 wiring, no new logic needed since those panels use one source unchanged). Fixture-linking assertion: Task 7. Layout discipline: Tasks 8-9 (copy-then-minimal-edit) + Task 11 Step 3/5 (verification). Vendoring convention: Tasks 1-3.
- **No placeholders**: every step has real code, real file paths (verified to exist via direct `Read`/`ls` during planning), and real commands.
- **Type/column consistency checked**: `combined_team_stats` returns the same DataFrame shape `metrics.team_stats` does (verified against its actual implementation), so `_stat_rows` in Task 10 (copied from `render_v2.py`'s real implementation) needs no changes. `blended_player_contributions` preserves the exact column names `_contribution_rows` (also copied verbatim from `render_v2.py`) already expects, so no template or row-builder changes were needed for the contribution table.

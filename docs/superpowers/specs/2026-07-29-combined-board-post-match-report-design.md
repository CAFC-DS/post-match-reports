# Combined board post-match report — design

Status: approved. Date: 2026-07-29.

## Purpose

A new standalone project, `combined-post-match-report`, that produces a
single-page board post-match report combining Impect and Opta/Second
Spectrum (DVMS) data — one metric per panel taken from whichever source is
actually best for that metric, laid out identically to the existing
Impect-only report (`board-post-match-report/src/report/templates/post_match_report_v2.html.j2`).

Scope: **board-post-match report only.** Not set-piece-report, not
pre-match, not any other sibling report.

## Prior art this builds on

`/Users/hashim.umarji/Projects/board-post-match-report/` already has three
report variants (`generate_report.py` v1, `generate_report_v2.py` — the
canonical Impect report, `generate_report_dvms.py` — the Opta/Second
Spectrum report). All three share one pipeline shape: Snowflake fetch →
parquet cache → `metrics*.py` derives DataFrames → `pitch.py`/`chart*.py`
render matplotlib panels to base64 PNGs → Jinja2 fills a `.html.j2`
template → WeasyPrint renders to PDF. The DVMS variant is proof the pattern
generalizes: its template differs from v2's only in per-panel data, the CSS
block is ~99% identical.

Impect data comes from `CAFC_TEST_ANALYSIS.PUBLIC.IMPECT_EVENTS_STAGING`
(not `CAFC_DB.IMPECT_RAW.EVENTS` — confirmed the governed table is
VARIANT-nested and doesn't expose the flattened columns `metrics.py` depends
on, e.g. `startLane`, `PXT_ATTACK`, `SHOT_AT_GOAL_NUMBER`; migrating is out
of scope). DVMS data comes from `CAFC_DB.DVMS_RAW.*` via the vendored
`src/dvms/` package, per `docs/raw-event-data-usage-guide.md` in
`cafc-data-platform`.

## Panel-by-panel data sourcing

| Panel | Source | Reasoning |
|---|---|---|
| Match stats table (13 rows, same 3 groups as v2) | Impect for all rows **except** Possession %, which comes from DVMS tracked ball-touch share | Impect's typed events/xG are richer for everything else; tracked possession beats a pass-count proxy |
| Shot map (xG) | Impect | Real provider xG model, vs DVMS's in-house `xg_lite` fallback (`XG_MODEL_LABEL`) |
| Territory / momentum | DVMS — `metrics_dvms.territory_wave()` (rolling mean tracked ball x-position) | User preference; ground truth over event-density proxy |
| Where the chances came from | Impect — `metrics.chance_sources()` (`phase` tag) | User preference |
| Average positions in build-up | DVMS tracking, **in-possession only**, one panel per side (matches v2's existing single-slot layout — do NOT import DVMS's 4-pitch in/out-of-possession layout) | True 25fps tracked positions vs Impect's event-touch proxy (`metrics_v2.py`'s own docstring flags this as biased) |
| Final third & box entries | Impect — `metrics.zone_entries()` (passes **and** carries via `DRIBBLE`, xT-weighted via `PXT_ATTACK`) | Opta has no carry events; Impect is the only source that can show carries at all |
| % through / % over / % around | DVMS — `src/dvms/metrics/line_breaks.py`, applied to the pass subset of entries only (not carries) | Needs tracked defensive-line height at the moment of the pass plus Opta long-ball/chip qualifiers to detect a lofted ball — Impect's `startLane`/`packingZone` fields can't discriminate "over", so this is the only defensible source. Label explicitly as "of passes" in the UI since carries aren't classified this way. |
| Player contribution | New blended score (see below) | No existing formula combines sources; both existing reports rank by one raw metric + context columns |

## Player contribution — blended score

Composite ranking metric per player, built from z-scored components (avoid
raw-unit averaging across sources with different scales):

- Impect: `PXT_ATTACK` (xT), successful passes, ground+aerial duels won,
  shots/xG (`SHOT_XG`)
- DVMS: distance covered, high-speed running (from Second Spectrum physical
  summary, TIP split preferred — in-possession running is the relevant
  signal for an attacking contribution score)

Exact weights are an implementation-time judgment call, expected to need
visual tuning against 2-3 known matches (a player everyone agrees had a
poor/good game should rank accordingly) — not fixed in this spec. Table
shows the composite rank plus context columns from both sources (xT,
passes, duels, distance, high-speed running, shots/xG), same visual pattern
as the existing tables (rank by one number, show context alongside).

## Layout discipline — the hard constraint

"Keep the layout exactly the same" means:

- New template is a byte-for-byte copy of `post_match_report_v2.html.j2`'s
  CSS block and panel structure (header, stats+shots row, momentum+chance
  sources row, average positions row, entries+contribution row). Diff the
  CSS block against v2's after writing it — expect zero differences outside
  panel copy.
- No new panels. No resized panel `flex` values (stats panel stays `0 0
  76mm`, entries panel stays `0 0 102mm`).
- Match stats table stays at **13 rows** — do not append tracked-only rows
  (e.g. defensive line height, block depth); if a tracked metric is wanted
  in the table it replaces an existing row's *source*, not adds a row.
- The through/over/around split has no dedicated chart slot — it renders as
  a caption/inline text or small bar within the existing entries panel's
  `chartbox`, not a new panel.
- Shotmap/xG labelling stays plain "xG" everywhere (not DVMS's
  `xg_label`/`XG_MODEL_LABEL` wording) since Impect's real model, not
  `xg_lite`, feeds this panel.

## New plumbing

1. **Fixture linking**: CLI takes both `--impect-match-id` and
   `--dvms-fixture-id` (no auto-matching between providers — that mapping
   doesn't exist today and isn't worth building for a manually-run report).
   After both load, assert team names and match date agree between the two;
   abort with a clear error if they don't, rather than silently rendering
   two different matches into one report.
2. **Vendoring**: copy (not import across repos) `palette.py`, `pitch.py`,
   `chart.py`, `chart_dvms.py`, `badges.py`, `assets/badges/`, and the
   `src/dvms/` package from `board-post-match-report`, per that package's
   own `VENDOR.md` convention. Copy `post_match_report_v2.html.j2` as the
   template starting point.
3. **Caching**: point the DVMS preprocessing step at
   `board-post-match-report`'s existing cache directory (or copy the
   relevant artifacts) for matches already preprocessed there, to avoid
   re-downloading ~28MB and re-parsing 1.5-2M tracking frames on first run.
4. **WeasyPrint base_url**: must be set correctly so `assets/badges/` crests
   resolve in the new project's own directory structure, not blank.

## Out of scope

- Passing network panel (v1-only, already dropped in v2 — stays dropped).
- Any auto-matching of Impect matches to DVMS fixtures.
- Migrating Impect access from `IMPECT_EVENTS_STAGING` to
  `CAFC_DB.IMPECT_RAW.EVENTS`.
- Any report other than board-post-match (no set-piece, no pre-match).

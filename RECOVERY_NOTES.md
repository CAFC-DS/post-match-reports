# Recovery notes: `expanded` (16-page) analyst report

This file is forensic documentation for the recovery of
`src/report/expanded/` — the 16-page "Charlton Athletic Analyst Report",
distinct from the canonical one-page report this repository otherwise
generates (`src/report/render_combined.py`).

## What actually happened (read this first)

An earlier session ("codex", per the user) believed this report had been
permanently deleted and attempted a from-scratch reconstruction purely from
a PDF, on branch `restore/deleted-expanded-report`. Two things about that
attempt were wrong and are corrected here:

1. **The report was not fabricated from nothing.** `outputs/expanded_analyst_report_Charlton_Athletic_v_Derby_County_15-08-2026.pdf`
   has an mtime of **2026-08-20 12:01:50**, which predates *every* `restore:`
   commit on this branch (earliest: 16:39:32 the same day). That PDF is a
   genuine surviving artefact from before the deletion — not something the
   recovery agent generated and mislabeled. Preserving a copy of it at
   `recovery/reference/` (commit `6a5393b`) was legitimate, correct
   forensics, not fraud.
2. **But the code was never verified against it.** The `restore:` commits
   after that point claim to "rebuild a functioning 16-page report," but
   `outputs/...pdf`'s mtime never advanced past 12:01:50 — meaning the
   rebuilt code was never actually run to completion and compared against
   the reference before being declared done. Running it (once the correct
   match IDs were found — see below) showed 3–45% pixel divergence per page,
   several genuinely broken charts, and hardcoded placeholder text
   presented as data.

The true reference PDF is preserved, additionally, at
`recovery/reference/verified_original/` (a second, explicit copy made this
session, so a future report-generation run can never silently overwrite the
only surviving ground truth by writing to `outputs/`).

## Match identity

The reference PDF is Charlton Athletic 2–1 Derby County, 15/08/2026,
Championship. The correct IDs (neither obvious from the repo — both required
querying Snowflake directly, since `--impect-match-id 207019` in this
report's own `--help` example is actually the *Swansea* fixture):

- **Impect match id: `267831`**
- **DVMS/Opta match id: `2647253`**

Invoke with:
```
python3 generate_report_expanded.py --impect-match-id 267831 --dvms-match-id 2647253
```

## What was recovered vs. reconstructed vs. still wrong

### Recovered (high confidence — real, pre-existing, tested code reused as-is)
- `metrics.passing_network`, `pitch.passing_network_map`, `pitch.entry_map`,
  `pitch.average_position_map`, `metrics_dvms.avg_position_frame` /
  `line_height_m`, `chart_dvms.territory_chart` — all real, already-used
  functions from the canonical one-page report's shared pipeline
  (`render_combined.build_context`), reused unchanged.
- The report's fixture-matching, badge resolution, and general page
  scaffold (`build_shared_context` call in `working.py`).

### Fixed (real bugs in the prior "restore" attempt, not styling)
- **Fonts.** The reference embeds Helvetica (body) and Iowan Old Style
  Italic (captions) — not the Arial/Georgia the prior CSS fell back to.
  Root cause: the CSS `font-family` stack was missing the intermediate
  `system-ui, -apple-system` fallbacks that the *sibling* canonical
  report's real design system defines
  (`post-match-report/.../post_match_report_combined.html.j2`:
  `--sans: 'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI',
  sans-serif`). Restored that exact stack.
- **Passing network had zero edges and drew all ~20 players, not the
  starting XI.** `working.py` fell back to a broken path because CAFC_DB's
  events table has no `passReceiverPlayerName` column (present in the older
  `IMPECT_EVENTS_STAGING` source `metrics.passing_network` was written
  against, lost in the 2026-07-30 migration to CAFC_DB — see
  `impect_cafcdb_source.py`'s own docstring). Fixed by deriving the receiver
  from the `RECEPTION` event that immediately follows each successful pass
  (`_infer_pass_receivers`, 615/616 = 99.8% coverage on the reference
  fixture), then using the real `metrics.passing_network` unchanged,
  restricted to the starting XI (`_starters_only_network`) to match the
  reference's "starting XI · shared match scales" caption.
- **Average-position pages paginated phase-first (both teams' "in
  possession" on one page, both teams' "out of possession" on the next).**
  Reference paginates team-first (one team, both phases, per page). Fixed
  the template loop order; the underlying chart function was already
  correct.
- **Match Stats table was a flat 13-row list with no baseline column, no
  bars, and 5 fewer rows than the reference** (missing Unsuccessful passes,
  Non-shot xG (packing), Opponents/Defenders bypassed, Second-ball wins).
  The 18-row grouped structure with a season-baseline column and inline
  bars is new (`STAT_ROWS_EXPANDED`, `_stat_rows_expanded`) — see "Season
  baseline" below.
- **Team Performance was a broken raw-value radar** (summed to well over
  100%, no labels, no legend) instead of a percentile-vs-season wheel.
  Rebuilt as `_performance_wheel` against real season data.
- **Match Highlights were three hardcoded, non-data-driven sentences**
  (`'Progressive actions and territory set the attacking platform.'` etc.,
  literally the same on every report regardless of the match). Replaced
  with `_match_highlights`, computed from the same percentile data as the
  wheel.
- **Player Duel Performance (page 13) rendered the identical single-team
  chart twice** (once per team, same image both times) instead of the
  reference's four-panel mirrored won/lost bars (aerial/ground ×
  Charlton/Derby). Root cause: a duel's *loser* is never the acting player
  on any event row — the loser's `LOST_*_DUELS` value lives in a **second
  entry** of that same event's `EVENT_KPIS` JSON array, keyed by the
  loser's own `playerId`, which `load_match_events`' one-entry-per-row
  flattening silently drops. New `impect_cafcdb_source.load_duel_involvement`
  reads every entry in the array, not just the row's own player. After the
  fix, every player and every won/lost count on this page matches the
  reference exactly.

### Reconstructed (real data, but the original formula does not survive —
best-effort, documented, and should be treated as approximate)
- **Season baseline** (`src/report/expanded/season_baseline.py`): Charlton's
  25/26 season is fully complete and 15/08/2026 is (evidently) matchday 1 of
  26/27, so the reference compares this match against the *prior full
  season* rather than a season-to-date average — confirmed by the "CAFC
  BASELINE" column header and "percentile vs CAFC 25/26 averages" wheel
  caption. Built by pulling all 46 of Charlton's 25/26 Impect match ids
  (queried directly from Snowflake, not documented anywhere in-repo) and
  computing `metrics.team_stats` plus four new metrics per match, cached to
  `~/.cache/charlton-post-match-analyst/season_baseline_1410.parquet` (46
  Snowflake round-trips; **outside the repo**, so a clean clone rebuilds it
  on first run — this is slow, ~1-2 minutes, by design, not a bug).
  **Validation: this baseline reproduces the reference's own "CAFC
  BASELINE" column numbers almost exactly** (43%, 65%, 242, 124, 56%, 246,
  30, 23, 29, 49 all match or are within rounding) — strong evidence the
  season-match-list and the underlying metric definitions are correct, even
  though the exact original code that produced them is gone.
- **Progressive actions**: successful pass/dribble gaining ≥10m of adjusted
  X. **Passes into final third**: successful pass crossing the 17.5m
  boundary. **Pressing intensity**: `-PPDA` (opponent passes completed in
  their own defensive half ÷ the reporting team's defensive actions in that
  same zone; negated so "higher is better" holds for the wheel). **Counter-
  press regains**: a ball win in the opponent's half within 5s of the
  team's own prior loss. None of these are named/defined anywhere else in
  the codebase — these are reasonable, standard football-analytics
  definitions, not recovered originals.
- **Transition speed** ("m/s of ball progress" in the Match Highlights
  footer): forward ground gained ÷ elapsed time across
  `ATTACKING_TRANSITION`-phase successful actions. **This one is flagged as
  still wrong**: it produces ~0.6 m/s for both teams on the reference
  fixture, vs. the reference's 3.65/3.38. The magnitude is off by roughly
  5–6×, which is too large to be a rounding/definition nuance — the
  original formula is not what's implemented here. Left in place with this
  caveat rather than removed, since a labelled-wrong number is more useful
  than silently dropping the highlight; whoever picks this up next should
  treat the *ranking* logic (best/worst percentile) as validated and this
  one number as the remaining open item.

### Not yet done (pages not substantially reworked this session)
Pages 9, 10, 12, 14, 16 still use the prior session's simpler chart
functions (`_event_map`, `_threat_heatmap`) rather than the reference's
richer, KPI-annotated versions:
- **Page 9** (Threat Creation): reference's "Threat Density Map" is a
  smooth jet-colormap heatmap with a "2.57 positive PXT Attack · 470
  actions" caption; current is a coarse 10×14-bin `hist2d`. Entries panel
  (`side_by_team[subject].entries`) already reuses the real
  `pitch.entry_map` and should be close.
- **Page 12** (Pressure Activity & Duel Performance): reference has a full
  jet-colormap pressure heatmap with a 4-cell KPI strip underneath
  (opposition-half share / opposition-third pressures / median intensity /
  top presser) and won/lost-marker duel-location maps with a "most
  involved" caption. Current `_event_map` is a bare scatter plot with none
  of that. No `pressure_heatmap` or duel-location function exists anywhere
  in the codebase to reuse — this needs new chart code, following the same
  pattern used for `_duel_bars_by_type` (query `EVENT_KPIS` array entries
  properly rather than the flattened one-entry-per-row events table, since
  pressure "intensity" and duel location/outcome likely have the same
  loser-is-a-second-array-entry issue found on page 13).
- **Page 14** (Regains & Second Balls): similar gap — reference has KPI
  strips with season-baseline deltas; current is bare scatter maps.
- **Page 16** (Defensive Transition): reference likely has a similarly
  richer map/KPI treatment; not compared in detail this session.

`src/report/expanded/render.py` and `src/report/expanded/metrics/` (three
files) are **non-functional dead code** from the prior session — `render.py`
imports `src.report.render` and a `src.report.metrics` *package* that don't
exist anywhere in this repo or any sibling repo (confirmed by search), and
targets a template (`post_match_analyst_report_expanded.html.j2`) that was
never created. They are retained per the no-delete recovery rule, not
because they're part of the working pipeline — `working.py` is the real
entry point (wired from `generate_report_expanded.py`). A future session
should either delete this dead code (with the user's explicit sign-off,
since deletion is exactly what caused this whole recovery task) or
genuinely finish it as an alternative implementation — not leave it as a
trap that looks like real infrastructure.

## Evidence used, by decision

| Decision | Evidence |
|---|---|
| Report is genuinely lost source, not just a bad diff | `git log --all -S` across this repo and both sibling repos found zero hits for the expanded report's template name or metrics package |
| `recovery/reference/...pdf` is real, not fabricated | SHA256-identical to `outputs/...pdf`, whose mtime (12:01:50) predates every `restore:` commit |
| Font stack | Sibling `post-match-report` repo's real `--sans`/`--serif-text` CSS variables, cross-checked against both PDFs' embedded font names via PyMuPDF |
| Passing-network receiver derivation | Verified 615/616 successful passes get a receiver from the `RECEPTION`-follows-`PASS` pattern, on the actual match's event log |
| Duel loser attribution | Direct Snowflake query of one event's raw `EVENT_KPIS` JSON, showing the second array entry |
| Season baseline correctness | The reconstructed baseline column reproduces the reference PDF's own baseline numbers almost exactly, across ~18 stat rows |
| Renderer / general provenance dead ends | Both PDFs share identical `Producer: Skia/PDF m151`, `Creator: HeadlessChrome/151.0.0.0` — no renderer divergence to chase |

## Validation performed this session

- `pytest -q`: 81 passed, 1 skipped (before *and* after every shared-code
  change — `metrics.team_stats`'s two new columns are optional/backward
  compatible specifically because a test fixture lacks them).
- `python -m src.report.render_combined --html-only`: canonical one-page
  report's full data pipeline still runs end-to-end after the shared
  `metrics.py`/`impect_cafcdb_source.py` changes (PDF step itself fails in
  this environment on a missing native WeasyPrint library — pre-existing,
  unrelated to this work).
- Full 16-page pixel-diff against the reference, before and after each
  major change, plus manual visual inspection of every page listed above.
- Page 13's duel-performance numbers cross-checked player-by-player and
  matched the reference exactly after the fix.

## How to regenerate

```bash
python3 generate_report_expanded.py --impect-match-id 267831 --dvms-match-id 2647253 --output-dir outputs
```

First run rebuilds the season baseline cache (~46 Snowflake queries, ~1-2
minutes); subsequent runs read `~/.cache/charlton-post-match-analyst/`.
**Do not point `--output-dir` at `outputs/` while iterating** — it will
overwrite the only verified copy of the reference fixture's original
generated PDF filename. Use a scratch directory instead, and only write to
`outputs/` once you're confident in the result (the true reference is
additionally preserved at `recovery/reference/verified_original/`
regardless).

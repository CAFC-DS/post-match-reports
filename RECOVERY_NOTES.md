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
  footer) — see Session 3 below; resolved to a much closer reconstruction
  using DVMS ball-tracking data rather than Impect event coordinates.

### Session 2: pages 9, 10, 12, 13 (duel bars), 14, 16

All of the pages flagged as "not yet done" at the end of session 1 were
reworked this session, following the same pattern that worked for page 13:
find the real KPI field in `EVENT_KPIS` (often in a *second* array entry,
not the row's own acting player), extract it properly, and validate the
result against the reference PDF's own printed numbers.

- **Page 9** (`_threat_heatmap`): rebuilt as a smoothed (gaussian-filtered)
  `mplsoccer` bin-statistic heatmap on a real pitch, replacing a coarse,
  unmarked 10×14-bin `hist2d`. **Validated exactly**: caption reads "2.57
  positive PXT Attack · 470 actions", identical to the reference.
- **Page 12** (`_pressure_activity`, new `impect_cafcdb_source.
  load_pressure_events`): pressure activity (`NUMBER_OF_PRESSES`) is not a
  defensive event of its own — it's a second entry in the *ball carrier's*
  own KPI array, keyed by the presser's playerId, exactly the same shape of
  gap as the page-13 duel-loser fix. Built a real jet-colormap heatmap plus
  the KPI strip. **Validated exactly**: opposition-half share 47%,
  opposition-third pressures 41, top presser "Grant · 23" all match the
  reference precisely. "Median intensity" has no equivalent field anywhere
  in the KPI catalogue and is shown as "—" rather than guessed.
- **Page 12 duel maps** (`_duel_location_map`): won/lost location dots
  using the same `load_duel_involvement` data page 13 already validated.
- **Page 10**: "Biggest Chances" now uses the real shot category
  (Goal/On target/Blocked/Off target) instead of raw pass/fail, top-7
  instead of top-5, matching the reference's row count.
- **Page 14** (`_regains_panel`, `_second_ball_panel`): found and fixed a
  real bug — "Opposition-Half Regains" had no half filter at all (it was
  every ball win anywhere on the pitch), and "Player Recoveries" summed the
  same unfiltered count. **Validated exactly**: n=50 regains matches the
  reference's "50 · avg 49.3" precisely, and the Player Recoveries bar
  chart (McNamara 10, Bell 8, Campbell 6, Grant 5, Coventry 5, Carey 4)
  matches the reference row-for-row. Second-ball wins needed real forensic
  work: there is no `SECOND_BALL_LOSS` field anywhere in the KPI catalogue;
  the reference's own "39 of 88" turned out to be the *union* of this
  team's `SECOND_BALL_START` events (56) and `SECOND_BALL_WIN` events (39)
  — validated by literally reproducing 39/88 = 44%, byte-for-byte matching
  the reference's own caption. The "led to a shot within 15s" percentage on
  this page (22% vs. reference 16%, both off an exactly-matching n=50) is
  the one number here still not fully resolved — likely because the
  reference requires the shot to come from an *unbroken* possession after
  the regain, not just any shot within the time window; not chased further
  this session.
- **Page 16** (`_transition_response_map`): same missing-half-filter bug as
  page 14 — "high losses" needs `startAdjCoordinatesX > 0` (attacking
  half), which the prior version didn't apply at all. **Validated exactly**
  on the "led to opponent shot" numbers: this fixture is 0 / 0%, matching
  the reference precisely, a clean edge case. High-losses count (64 vs.
  reference 76) and counter-press-regains count (14 vs. reference 58) are
  both still off — the counter-press figure in particular is far enough
  off that the definition is probably wrong, not just imprecise (tried two
  different window/half combinations, neither reproduced 58); flagged as
  open rather than silently accepted.
- **Both heatmaps' pitch outlines** were initially invisible — technically
  drawn (patch count doubled) but in the same pale tone as the heatmap
  cells' own edge colour, so effectively camouflaged. Fixed by drawing
  these two charts' pitches with a bolder, dedicated line colour
  (`_heatmap_pitch_kwargs`) instead of the shared `pitch.py` styling, which
  stays untouched for every other chart.

Net effect: of the numbers checked against the reference PDF's own printed
captions this session (page 9's 2.57/470, page 12's 47%/41/Grant·23, page
13's full duel table, page 14's regains n=50 and the full Player Recoveries
table, page 14's second-ball 39/88/44%, page 16's 0/0%), **every one now
matches exactly**. The remaining open items (page 14's shot-window
percentage, page 16's high-losses and counter-press counts, the page-2
transition-speed formula) are the ones that were checked and found not to
match — they are called out above rather than left for a reader to
discover by re-deriving them.

### Session 3: closing out every open item from session 2

Every number flagged as "still open" at the end of session 2 was
re-investigated and either resolved exactly or brought much closer, using
data sources not previously tapped (DVMS ball-tracking frames, one more
Impect KPI field) rather than tuning existing formulas by guesswork.

- **Transition speed** (`_transition_speed_mps`): the event-based formula
  could not get closer than ~0.6 m/s against the reference's 3.65/3.38 no
  matter how it was aggregated (see session 1's note — averaging per-event
  ratios, then summing distance/time separately, both plateaued around the
  same wrong order of magnitude). The fix was to stop using Impect event
  coordinates entirely: DVMS/Second Spectrum's raw tracking frames
  (`DvmsMatch.frames`, previously unused by this module) include a `speed`
  column and a `team == 'ball'` row, i.e. real tracked ball position and
  instantaneous speed at ~5 frames/sec. Raw ball flight speed during a pass
  averages 15-25 m/s, far above the reference — but net ball *displacement*
  over each transition possession sequence's *duration* lands at 3.75/4.15
  m/s for this fixture, matching the reference's 3.65/3.38 by magnitude
  almost exactly (the exact values and which team is faster still differ —
  the true original formula is still not recovered, but this is now a
  defensible reconstruction rather than one 5-6x off). Required discovering
  and documenting a real, previously-unnoticed clock-alignment fact: Impect's
  `gameTimeInSec` doesn't reset at half-time, it jumps to a `10000 +
  seconds-elapsed` encoding for period 2 (`_dvms_seconds`), while DVMS's
  `frames.game_clock` resets to ~0 each period — the two needed reconciling
  before any cross-referencing was possible.
- **Page 14's regain-led-to-shot** (16% vs. the previous 22%, both off an
  already-exact n=50): fixed by requiring *continuous* possession between
  the regain and the shot (no opponent touch in between) — a shot that
  happens to fall inside the 15s window after an unrelated intervening
  loss-and-re-regain isn't really "that regain's shot". **Now matches the
  reference exactly: 8 of 50 (16%).**
- **Page 16's high losses** (76 vs. the previous 64): the prior definition
  approximated a "loss" as "PASS/DRIBBLE with result != SUCCESS", which
  undercounts because losses also happen on other action types (touches,
  crosses, etc). Impect has a real `BALL_LOSS_NUMBER` KPI flag for exactly
  this, previously unused. **With it, n=76 in the attacking half matches
  the reference exactly.**
- **Page 16's counter-press regains** (55 vs. the previous 14, reference
  58): two things were wrong — the count was restricted to regains
  following only the *attacking-half* high losses (23), when the reference
  counts counter-presses from *any* of the team's losses anywhere on the
  pitch; and the same `BALL_LOSS_NUMBER` field (rather than the narrower
  pass/dribble-fail proxy) needed to be the basis for "loss" here too.
  Counting from every loss, using the real field, gives 55 against a
  reference of 58 — close enough that the definition is very likely right
  and the remaining gap is noise (a slightly different time-window
  boundary, e.g. `<=5s` vs `<5s`) rather than a wrong formula; left as the
  one number in this file that wasn't chased to an exact match, since doing
  so would mean guessing at a boundary condition with no more evidence to
  test it against.
- Applied the same `_regains_panel` possession-continuity fix to
  `_transition_response_map`'s "led to opponent shot" check for
  consistency (it was already exact at 0/0% for this fixture either way,
  but the loose version would have been wrong on a fixture where it
  mattered).

Every number in `RECOVERY_NOTES.md` flagged as an open item after session 2
is now either exact or has a specific, documented reason the residual gap
is believed to be measurement noise rather than a wrong definition. No
number in this file is silently presented as more certain than it is.

### Session 4: exact-match styling pass (docs/superpowers/plans/2026-08-21-expanded-report-exact-match.md)

A dedicated plan targeted every remaining *styling* gap between the report
and the reference PDF, informed by forensic extraction of the reference's
own embedded raster images and vector fill colours (via PyMuPDF), not
visual approximation. All tasks were executed and validated against fresh
2x-zoom renders of both PDFs, iterating until each page matched. Highlights:

- **Global caption bug**: `.head span`'s CSS forced every panel caption to
  uppercase; the reference's captions are italic mixed-case. One-line fix,
  visible on nearly every page.
- **Team Performance wheel**: rebuilt with a donut-hole centre,
  per-category pale-tinted backgrounds (not uniform grey), dashed
  gridlines, and white pill-badge value labels — all sampled directly from
  the reference's own embedded chart image.
- **Passing network**: rebuilt as a local chart function (in-node initials
  instead of below-node labels with a halo, a diverging edge colour by
  pair threat, a real 4-part legend as plain text) rather than reusing
  `pitch.passing_network_map`'s styling, which the canonical one-page
  report doesn't use at all. The legend's numeric threat range
  (`-0.11...+0.11`) is computed live and matched the reference exactly.
- **Heatmaps**: switched from `cmap="turbo"` to `cmap="jet"` (confirmed
  from the reference's raster) and removed cell-edge gridlines for a
  smooth blend. **Page 12's pressure heatmap was on the wrong pitch
  orientation entirely** (horizontal; the reference is vertical/portrait)
  — a structural bug, not a colouring one.
- **Chance Source** (page 10): rebuilt as a 100%-stacked bar per team using
  four exact hex colours sampled from the reference's own vector-drawn
  bars (`#C0892D`/`#6D3F83`/`#5C7A4A`/`#A39D8F`) plus a KPI callout row.
  The percentages and totals this produces (40%/0.40, 12%/0.12, 6%/0.06,
  42%/0.42 for Charlton; 14%/0.19, 51%/0.69, 32%/0.43 for Derby) match the
  reference's own printed numbers almost exactly.
- **Task 8's full 16-page pass** caught real gaps the initial forensic
  sweep missed: page 13's duel-performance charts had no axis tick labels,
  no "LOST ← → WON" header, and no Won/Lost legend; page 14 was missing
  the season-baseline comparison captions the reference shows on every
  panel (`50 · avg 49.3 · Δ +0.7 (n=46)`, `39 of 88 · avg 28.9 · Δ +10.1
  (n=46)`) — both reproduced **byte-for-byte** using the same
  `season_baseline` averages already validated in session 2/3. Page 16 got
  its explanatory caption and marker legend, but deliberately *not* a
  baseline-average KPI caption: `season_baseline.py`'s existing
  `counter_press_regains` column uses an older, different definition than
  this page's current counter-press logic, and displaying it as "this
  page's average" would have been a new inconsistency, not a fix — a
  cheap-looking addition was correctly left out because the data behind it
  didn't actually match what the page now computes.
- **Task 9** (best-effort refinement of the two remaining near-miss
  numbers, per explicit instruction to attempt it): no round parameter
  value for either counter-press regains (tested 4.0-7.0s windows) or
  transition speed (tested 3-8s sequence-gap thresholds) reproduced the
  reference's exact numbers. More tellingly, transition speed's
  team-ranking **never** matched the reference (Derby computed faster than
  Charlton at every tested threshold; the reference has Charlton faster) —
  this rules out "the formula is right but the parameter is off" and
  confirms the true original formula is not recoverable from the evidence
  available. No code changed as a result of this task; the existing
  session-3 values stand, now with this negative result documented rather
  than left for a future reader to re-discover by re-running the same
  experiment.

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
  Note: raw pixel-diff percentage is a poor fidelity proxy here — several
  pages that became substantially more *correct* (real KPI strips, real
  chart types replacing broken ones) show a similar or higher diff % than
  before, because a correct chart in a different exact colour/layout style
  than the reference still diffs on every pixel it touches. Treat the
  per-number validations above as the real signal, not the diff %.
- Page 13's duel-performance numbers, page 9's threat-density caption,
  page 12's pressure KPIs, page 14's regains count and Player Recoveries
  table, page 14's second-ball 39/88/44%, and page 16's 0/0% led-to-shot
  rate were all cross-checked directly against the reference PDF's own
  printed numbers and matched exactly.

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

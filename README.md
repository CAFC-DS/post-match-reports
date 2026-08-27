# CAFC post-match reports

Private production bundle for Charlton Athletic first-team fixtures:

1. the 16-page expanded analyst report;
2. the one-page board report;
3. the one-page set-piece report (light theme, hybrid corners, player tables).

Generate all three reports and a validated manifest with:

```bash
python -m post_match_reports generate \
  --impect-match-id 267843 \
  --dvms-match-id 2647272 \
  --output-dir dist/267843
```

Discover the latest completed fixture for which every production source is
ready with:

```bash
python -m post_match_reports discover \
  --team "Charlton Athletic" --not-before 2026-08-29 --json
```

Deployment and delivery configuration is documented in
[`docs/automation.md`](docs/automation.md).

## Board report

Canonical one-page A4 post-match report for Charlton Athletic.

IMPECT is the stable analytical source. When an exact home-team, away-team and
date match is available in DVMS, tracking and physical data enrich the page.
When DVMS is absent or an individual asset is unusable, the affected panel uses
an explicitly labelled IMPECT fallback. Fixture ambiguity and identity mismatch
are errors rather than silent fallbacks.

## Generate

```bash
python -m src.report.render_combined --impect-match-id 207019
python -m src.report.render_combined --impect-match-id 207019 --force-impect-only
python -m src.report.render_combined --impect-match-id 207019 --dvms-match-id 2566913
```

Use `--html-only`, `--pdf-only`, or `--output-dir PATH` as needed. The default
command auto-discovers DVMS and preprocesses its tracking cache on first use.

## Provider contract

- IMPECT: result, form, core statistics, shots/xG, chance sources, entries and
  player ranking by total `PXT_ATTACK`.
- DVMS when valid: tracked possession, territory, four tracked team shapes,
  line-break route and physical display columns.
- IMPECT fallback: event possession, pXT momentum, two in-possession event
  location pitches and entry effectiveness. It never invents tracked
  out-of-possession shapes or through/over/around classifications.

Run tests with `pytest -q`. Secrets belong in the ignored `.env`; `.env.example`
documents the required keys.

## Expanded analyst report

Generate the 16-page DVMS-enriched analyst report with:

```bash
python generate_report_expanded.py --impect-match-id 267843 --dvms-match-id 2647272
```

The renderer discovers Chrome/Chromium on `PATH` and in standard install
locations. Use `--chrome-bin PATH` or `CHROME_BIN` to select it explicitly.
The West Ham report in `tests/golden/` is the production regression reference;
compare a generated PDF with `python -m src.report.expanded.regression
CANDIDATE GOLDEN --exact` when using the reference Chrome version.

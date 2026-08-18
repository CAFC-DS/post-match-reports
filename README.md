# Post-match report

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

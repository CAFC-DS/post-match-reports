# src/dvms — DVMS (Opta + Second Spectrum) data package

**This copy is now the source of truth.** It began as a byte-identical
downstream vendor copy of `board-post-match-report/src/dvms/`, but that repo
and the other historical siblings (`post-match-report`, `set-piece-report`,
`dvms-sample-pack`) are dead — consolidated ~2026-08-18, no live remotes.
`CAFC-DS/post-match-reports` is the sole remaining consumer, so edit this
directory directly and run `pytest tests/dvms/`.

One in-repo mirror still exists: `reports/set_piece/src/dvms/` (used by the
set-piece sub-report). Keep it byte-identical to this directory until the two
trees are deduplicated.

Data formats are documented in the DVMS handover
(`cafc-data-platform/docs/dvms-data-handover.md`); parsers are unit-tested
against the real sample files in `~/Desktop/dvms_samples/`.

History: last vendor sync from the old canonical was 2026-07-29. Diverged
2026-09-01 — `fixtures_table()` repointed to the deduped
`CAFC_DB.DVMS_RAW_STAGING.STG_DVMS__FIXTURES` view (PR #1).

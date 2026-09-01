# src/dvms — DVMS (Opta + Second Spectrum) data package

In-repo mirror of the top-level `src/dvms/` (the source of truth — see its
VENDOR.md). Keep this directory byte-identical to `<repo root>/src/dvms/`
until the two trees are deduplicated; edit there, then copy here.

The old external canonical (`board-post-match-report/src/dvms/`) and the
historical sibling repos are dead — consolidated ~2026-08-18.

Data formats are documented in the DVMS handover
(`cafc-data-platform/docs/dvms-data-handover.md`); parsers are unit-tested
against the real sample files in `~/Desktop/dvms_samples/`.

History: last vendor sync from the old canonical was 2026-07-19. Diverged
2026-09-01 — `fixtures_table()` repointed to the deduped
`CAFC_DB.DVMS_RAW_STAGING.STG_DVMS__FIXTURES` view (PR #1).

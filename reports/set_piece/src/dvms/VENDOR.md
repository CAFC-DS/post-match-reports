# src/dvms — vendored DVMS (Opta + Second Spectrum) data package

Canonical copy: `board-post-match-report/src/dvms/`. The sibling repos
(`charlton-post-match-analyst`, `set-piece-report`,
`pre-match-set-piece-report`, `dvms-sample-pack`) carry byte-identical
copies, the same convention as `src/db/`. Edit here, run the tests
(`pytest tests/dvms/`), then re-copy; never edit a downstream copy.

Data formats are documented in the DVMS handover
(`cafc-data-platform/docs/dvms-data-handover.md`); parsers are unit-tested
against the real sample files in `~/Desktop/dvms_samples/`.

Last sync: 2026-07-19.

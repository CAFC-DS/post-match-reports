# Consolidation record

Created on 18 August 2026 from the Git history of
`combined-post-match-report`, branch `worktree-combined-report-impl` at
`4f195cfd368e2d322403c53adc9781a65fa6f9d9`.

The source implementation worktree's report metrics, DVMS metrics, template,
badge resolver and Derby badge changes were preserved before development.

From `board-post-match-report`, the canonical repository imports
`src/report/metrics_v2.py`: the event-based in-possession average-location
method and its event-derived line-height helper. Other board renderers and DVMS
copies were not imported because they duplicate the combined implementation.

`charlton-post-match-analyst` is explicitly outside this consolidation.

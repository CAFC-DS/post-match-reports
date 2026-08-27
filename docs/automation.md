# Post-match report automation

The production bundle contains the 16-page expanded analyst report, the
one-page board report, and the light/hybrid/player-table set-piece report.
Scheduled runs never publish partial or fallback bundles. Emailing is manual.

## GitHub configuration

Create a private `CAFC-DS/post-match-reports` repository and a protected
`production` environment. Give the repository access to the existing
Snowflake organization secrets, including `SNOWFLAKE_PRIVATE_KEY`.

Set these repository/environment variables:

- `AUTOMATION_START_DATE`: first fixture date eligible for automatic delivery.
- `CAFC_TEAM_NAME`: `Charlton Athletic`.

## Operating model

The scheduled workflow checks five times per London day. A published private
release tagged `match-<impect-id>` contains all three PDFs plus `manifest.json`
and prevents duplicate generation. Download those PDFs from the release and
attach them to the existing Outlook distribution-list email manually.

Use a manual workflow run with both provider IDs and `archive_release` disabled
for a generation-only test. Enable `archive_release` when the reviewed bundle
should become the permanent private release for that fixture.

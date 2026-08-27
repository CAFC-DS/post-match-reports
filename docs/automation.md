# Post-match report automation

The production bundle contains the 16-page expanded analyst report, the
one-page board report, and the light/hybrid/player-table set-piece report.
Scheduled runs never send partial or fallback bundles.

## GitHub configuration

Create a private `CAFC-DS/post-match-reports` repository and a protected
`production` environment. Give the repository access to the existing
Snowflake organization secrets, including `SNOWFLAKE_PRIVATE_KEY`.

Set these repository/environment variables:

- `AUTOMATION_START_DATE`: first fixture date eligible for automatic delivery.
- `CAFC_TEAM_NAME`: `Charlton Athletic`.
- `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`: delegated Entra application.
- `MAIL_RECIPIENT`: Microsoft 365 distribution-list address.
- `ALERT_RECIPIENT`: operational owner (reserved for failure notifications).

The Entra application uses delegated `Mail.Send`, `Mail.ReadWrite`, and
`offline_access` permissions and sends as the signed-in CAFC user. Enable public
client flows, then run `scripts/authorize_graph_delegated.py` once to store the
MSAL cache as the `MSAL_TOKEN_CACHE` GitHub secret. Microsoft or CAFC policy may
periodically require the user to repeat this sign-in.

## Operating model

The scheduled workflow checks five times per London day. A published private
release tagged `match-<impect-id>` is the delivery marker. A draft release means
generation completed but delivery may have been interrupted; scheduled runs do
not resend it automatically. Reconcile the shared mailbox's Sent Items, then
publish or delete the draft before a deliberate manual rerun.

Use a manual workflow run with both provider IDs and `send_email` disabled for
the first deployment test. Add a test recipient and enable `send_email` only
after the PDFs and manifest have been reviewed.

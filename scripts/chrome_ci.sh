#!/usr/bin/env bash
set -euo pipefail

: "${REAL_CHROME_BIN:?REAL_CHROME_BIN must point to the installed Chromium executable}"
exec "$REAL_CHROME_BIN" --no-sandbox "$@"

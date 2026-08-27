#!/usr/bin/env python3
"""Perform one device-code login and store its MSAL cache in GitHub secrets."""

from __future__ import annotations

import argparse
import subprocess

import msal

from post_match_reports.delegated_auth import SCOPES, _cache, serialized_cache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--repo", default="CAFC-DS/post-match-reports")
    args = parser.parse_args()

    cache = _cache()
    app = msal.PublicClientApplication(
        args.client_id,
        authority=f"https://login.microsoftonline.com/{args.tenant_id}",
        token_cache=cache,
    )
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Could not start Microsoft device login: {flow}")
    print(flow["message"], flush=True)
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", str(result)))

    subprocess.run(
        ["gh", "secret", "set", "MSAL_TOKEN_CACHE", "--repo", args.repo],
        input=serialized_cache(cache),
        text=True,
        check=True,
    )
    print("Delegated token cache stored in GitHub as MSAL_TOKEN_CACHE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

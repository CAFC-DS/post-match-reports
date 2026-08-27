from __future__ import annotations

import base64
import os

import msal


SCOPES = ["Mail.Send", "Mail.ReadWrite"]


def _cache(encoded: str | None = None) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if encoded:
        cache.deserialize(base64.b64decode(encoded).decode("utf-8"))
    return cache


def serialized_cache(cache: msal.SerializableTokenCache) -> str:
    return base64.b64encode(cache.serialize().encode("utf-8")).decode("ascii")


def delegated_access_token() -> str:
    """Acquire a token silently from the delegated cache stored by GitHub."""
    client_id = os.environ["AZURE_CLIENT_ID"]
    tenant_id = os.environ["AZURE_TENANT_ID"]
    cache = _cache(os.environ["MSAL_TOKEN_CACHE"])
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("Delegated Microsoft token cache contains no account")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        detail = (result or {}).get("error_description", "interactive sign-in is required")
        raise RuntimeError(f"Delegated Microsoft authentication failed: {detail}")
    return result["access_token"]

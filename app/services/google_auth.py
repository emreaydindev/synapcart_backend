"""OAuth2 access tokens for Google service accounts (Play Developer API, FCM).

Implements the JWT-bearer flow directly with python-jose and httpx so the
backend doesn't need google-auth/firebase-admin.
"""
import json
import os
import time
from typing import Dict, Optional, Tuple

import httpx
from jose import jwt

TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPE_ANDROID_PUBLISHER = "https://www.googleapis.com/auth/androidpublisher"
SCOPE_FCM = "https://www.googleapis.com/auth/firebase.messaging"


class GoogleAuthError(Exception):
    pass


def load_service_account(value: str) -> Optional[dict]:
    """`value` is the key file's JSON content or a path to it; empty = not configured."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        if not value.startswith("{") and os.path.exists(value):
            with open(value, encoding="utf-8") as f:
                return json.load(f)
        return json.loads(value)
    except (OSError, ValueError) as e:
        raise GoogleAuthError("Invalid service account JSON") from e


_cache: Dict[Tuple[str, str], Tuple[float, str]] = {}


async def access_token(account: dict, scope: str) -> str:
    key = (account.get("client_email", ""), scope)
    hit = _cache.get(key)
    if hit and hit[0] - 60 > time.time():
        return hit[1]

    now = int(time.time())
    token_uri = account.get("token_uri") or TOKEN_URI
    try:
        assertion = jwt.encode(
            {"iss": account["client_email"], "scope": scope, "aud": token_uri, "iat": now, "exp": now + 3600},
            account["private_key"],
            algorithm="RS256",
            headers={"kid": account.get("private_key_id", "")},
        )
    except Exception as e:  # missing fields or a malformed key
        raise GoogleAuthError("Could not sign service account assertion") from e

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                token_uri,
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            )
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise GoogleAuthError(f"Token exchange failed: {type(e).__name__}") from e

    token = data["access_token"]
    _cache[key] = (time.time() + int(data.get("expires_in", 3600)), token)
    return token

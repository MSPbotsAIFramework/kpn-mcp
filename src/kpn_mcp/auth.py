"""KPN OAuth2 client-credentials token exchange with a fingerprint-keyed cache.

Design decision (see docs/tickets/PRD-21262.md, "Decisions made by DEV01"):
the access token is cached in-process, keyed by a hash of the client
id+secret pair, with the cache entry's TTL taken from KPN's own
`expires_in`. This is the exact exception SOP section 3.4 allows ("unless
the cache key includes a credential fingerprint and an expiry") -- it never
holds a token outside of a key tied to the exact credentials that produced
it, so two tenants with different credentials never share a cache entry.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import httpx

from kpn_mcp.config import settings

# Refresh this many seconds before the token's reported expiry, to avoid
# a request racing a token that expires mid-flight.
_EXPIRY_SAFETY_MARGIN_SECONDS = 30


class KpnAuthError(Exception):
    """Raised when KPN's OAuth token endpoint rejects the credentials or fails."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float


_token_cache: dict[str, _CachedToken] = {}


def _fingerprint(client_id: str, client_secret: str) -> str:
    """Hash the credential pair -- the cache key never stores the raw secret."""
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def get_access_token(client: httpx.AsyncClient, client_id: str, client_secret: str) -> str:
    """Return a cached or freshly fetched KPN OAuth2 access token.

    Raises KpnAuthError if KPN's token endpoint returns a non-2xx response
    or the request fails outright.
    """
    key = _fingerprint(client_id, client_secret)
    cached = _token_cache.get(key)
    now = time.monotonic()
    if cached is not None and cached.expires_at > now:
        return cached.access_token

    try:
        response = await client.post(
            settings.kpn_token_url,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
    except httpx.HTTPError as exc:
        raise KpnAuthError(0, f"KPN token endpoint request failed: {exc}") from exc

    if response.status_code >= 400:
        raise KpnAuthError(
            response.status_code,
            f"KPN token endpoint returned {response.status_code}",
        )

    body = response.json()
    access_token = body["access_token"]
    expires_in = float(body.get("expires_in", 300))
    expires_at = now + max(expires_in - _EXPIRY_SAFETY_MARGIN_SECONDS, 1.0)
    _token_cache[key] = _CachedToken(access_token=access_token, expires_at=expires_at)
    return access_token


def _clear_cache_for_testing() -> None:
    """Test-only helper: tests must not leak cached tokens across cases."""
    _token_cache.clear()

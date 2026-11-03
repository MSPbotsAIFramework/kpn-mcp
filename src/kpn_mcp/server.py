"""FastMCP factory and the request-scoped KPN credential middleware.

Credentials travel only as request headers (SOP section 3.1) and are read
into a ContextVar for the lifetime of the request, then reset in a
`finally` block (SOP section 3.3). No global or module-level variable ever
holds a credential -- that is what keeps concurrent, different-tenant
requests from leaking into each other (AC5).
"""

from __future__ import annotations

import json
from contextvars import ContextVar

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from kpn_mcp.api_client import KpnApiClient

CLIENT_ID_HEADER = "X-Kpn-Client-Id"
CLIENT_SECRET_HEADER = "X-Kpn-Client-Secret"

_credentials: ContextVar["tuple[str, str] | None"] = ContextVar("kpn_credentials", default=None)

INSTRUCTIONS = (
    "KPN connector for Dutch telecom data: network disturbance status, internet "
    "speed/availability, and SIM-swap fraud signal, each keyed by a Dutch address "
    "or mobile number. All three tools are read-only lookups against KPN's public "
    "developer-portal APIs. Typical use: check kpn_check_disturbance or "
    "kpn_check_internet_speed before advising a customer on a connectivity issue "
    "at an address; check kpn_check_sim_swap as one fraud/account-takeover signal "
    "before a sensitive account action on a phone number."
)


def client_factory() -> KpnApiClient | None:
    """Build an API client from the current request's credentials.

    Returns None when no credentials are set for this request -- callers
    (tools) must turn that into a `not_configured` error envelope rather
    than raising, since in practice the middleware already rejects
    requests with missing headers before a tool ever runs.
    """
    creds = _credentials.get()
    if creds is None:
        return None
    client_id, client_secret = creds
    return KpnApiClient(client_id, client_secret)


class CredentialHeaderMiddleware:
    """Pure ASGI middleware: reads the two KPN credential headers into a
    ContextVar for the duration of the request, or short-circuits with 401
    if either is missing -- no call to KPN is made in that case (AC4).

    `exempt_paths` (e.g. `/health`) are passed through untouched: the health
    probe must stay a pure local check, not require tenant credentials
    (SOP section 1.1).
    """

    def __init__(self, app: ASGIApp, exempt_paths: frozenset[str] = frozenset()) -> None:
        self._app = app
        self._exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self._exempt_paths:
            await self._app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        headers = request.headers
        client_id = headers.get(CLIENT_ID_HEADER.lower())
        client_secret = headers.get(CLIENT_SECRET_HEADER.lower())
        missing = [
            name
            for name, value in (
                (CLIENT_ID_HEADER, client_id),
                (CLIENT_SECRET_HEADER, client_secret),
            )
            if not value
        ]
        if missing:
            response = JSONResponse(
                {"error": "missing_headers", "missing": missing},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Both are guaranteed non-None here: `missing` above is empty only
        # when neither header was absent or blank.
        assert client_id is not None
        assert client_secret is not None
        token = _credentials.set((client_id, client_secret))
        try:
            await self._app(scope, receive, send)
        finally:
            _credentials.reset(token)


def create_mcp_server() -> FastMCP:
    """Build the FastMCP instance. Registration of tools happens in __main__.py
    after this call, via each tools/<resource>.py module's `register(mcp, client_factory)`.
    """
    return FastMCP(
        name="kpn-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def error_envelope(code: str, message: str, retryable: bool) -> str:
    """Serialize the fixed error envelope shape (SOP section 4.2)."""
    return json.dumps(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def dumps(payload: object) -> str:
    """Compact, non-ASCII-escaping JSON serialization for tool results (SOP section 2.5)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

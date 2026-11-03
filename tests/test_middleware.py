"""Missing-credential-header 401 handling and request-level credential isolation.

Covers TC7 (AC4) and TC8 (AC5) from docs/tickets/PRD-21262.ac.json.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from kpn_mcp.server import CredentialHeaderMiddleware, _credentials, client_factory


async def _lifespan_aware_app(scope, receive, send, calls: list[str]):
    """Minimal ASGI app that records every HTTP path it is invoked for,
    and answers lifespan startup/shutdown so TestClient's context manager works.
    """
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return
    calls.append(scope["path"])
    response = PlainTextResponse("ok")
    await response(scope, receive, send)


def _build_app(calls: list[str]):
    async def inner(scope, receive, send):
        await _lifespan_aware_app(scope, receive, send, calls)

    return CredentialHeaderMiddleware(inner, exempt_paths=frozenset({"/health"}))


def test_missing_credential_headers_returns_401():
    calls: list[str] = []
    app = _build_app(calls)
    with TestClient(app) as client:
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "missing_headers"
    assert set(body["missing"]) == {"X-Kpn-Client-Id", "X-Kpn-Client-Secret"}
    # No call reached KPN or even the inner MCP handler -- short-circuited before that.
    assert calls == []


def test_missing_one_credential_header_lists_only_that_one():
    calls: list[str] = []
    app = _build_app(calls)
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"X-Kpn-Client-Id": "abc"},
        )

    assert response.status_code == 401
    assert response.json()["missing"] == ["X-Kpn-Client-Secret"]
    assert calls == []


def test_health_endpoint_is_exempt_from_credential_check():
    calls: list[str] = []
    app = _build_app(calls)
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert calls == ["/health"]


def test_present_credentials_reach_the_inner_app():
    calls: list[str] = []
    app = _build_app(calls)
    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"X-Kpn-Client-Id": "abc", "X-Kpn-Client-Secret": "shh"},
        )

    assert response.status_code == 200
    assert calls == ["/mcp"]


async def test_concurrent_requests_do_not_leak_credentials():
    """Two concurrent asyncio tasks, each simulating one in-flight request
    with its own credentials; each must only ever observe its own pair.

    This relies on the same mechanism the real middleware relies on:
    asyncio.Task copies the current contextvars.Context at creation time,
    so a ContextVar.set() inside one task is invisible to a sibling task.
    """
    barrier = asyncio.Barrier(2)

    async def simulate_request(client_id: str, client_secret: str):
        token = _credentials.set((client_id, client_secret))
        try:
            # Force both tasks to be in-flight at the same time before either reads back.
            await barrier.wait()
            client = client_factory()
            assert client is not None
            try:
                return client._client_id, client._client_secret
            finally:
                await client.aclose()
        finally:
            _credentials.reset(token)

    result_a, result_b = await asyncio.gather(
        simulate_request("tenant-a-id", "tenant-a-secret"),
        simulate_request("tenant-b-id", "tenant-b-secret"),
    )

    assert result_a == ("tenant-a-id", "tenant-a-secret")
    assert result_b == ("tenant-b-id", "tenant-b-secret")


async def test_credentials_are_not_visible_outside_the_request_scope():
    assert _credentials.get() is None
    token = _credentials.set(("x", "y"))
    _credentials.reset(token)
    assert _credentials.get() is None
    assert client_factory() is None

"""tools/list snapshot, per-tool happy path, and the KPN -> envelope error-mapping table.

Covers TC1, TC2, TC3, TC5, TC6, TC9 from docs/tickets/PRD-21262.ac.json.
All KPN calls are mocked at the httpx.AsyncClient.request level -- no
network traffic leaves this process.
"""

from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest

from kpn_mcp import api_client as api_client_module
from kpn_mcp.server import _credentials, client_factory, create_mcp_server
from kpn_mcp.tools import identity, network


class _HttpStub:
    """Replaces httpx.AsyncClient.request for the duration of a test."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._responses: httpx.Response | list[httpx.Response] | None = None

    def set(self, responses: httpx.Response | list[httpx.Response]) -> None:
        self._responses = responses

    async def __call__(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        self.calls.append((method, path, kwargs))
        if isinstance(self._responses, list):
            return self._responses.pop(0)
        assert self._responses is not None, "test forgot to call kpn_http.set(...)"
        return self._responses


@pytest.fixture
def kpn_http(monkeypatch: pytest.MonkeyPatch) -> _HttpStub:
    async def fake_get_access_token(client: object, client_id: str, client_secret: str) -> str:
        return f"token-for-{client_id}"

    monkeypatch.setattr(api_client_module, "get_access_token", fake_get_access_token)

    async def no_delay(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(api_client_module.asyncio, "sleep", no_delay)

    stub = _HttpStub()
    monkeypatch.setattr(httpx.AsyncClient, "request", stub)
    return stub


@contextmanager
def credentials(client_id: str = "test-client-id", client_secret: str = "test-client-secret"):
    token = _credentials.set((client_id, client_secret))
    try:
        yield
    finally:
        _credentials.reset(token)


@pytest.fixture
def mcp_app():
    mcp = create_mcp_server()
    network.register(mcp, client_factory)
    identity.register(mcp, client_factory)
    return mcp


def _response(status_code: int, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status_code=status_code, json=body if body is not None else {}, headers=headers or {})


async def _call(mcp_app, tool_name: str, arguments: dict) -> dict:
    content, _ = await mcp_app.call_tool(tool_name, arguments)
    assert len(content) == 1
    return json.loads(content[0].text)


# ---------------------------------------------------------------------------
# tools/list snapshot (names + required params)
# ---------------------------------------------------------------------------


async def test_tools_list_snapshot(mcp_app):
    tools = await mcp_app.list_tools()
    by_name = {t.name: t for t in tools}

    assert set(by_name) == {"kpn_check_disturbance", "kpn_check_internet_speed", "kpn_check_sim_swap"}

    assert by_name["kpn_check_disturbance"].inputSchema["required"] == ["zip_code", "house_number"]
    assert by_name["kpn_check_internet_speed"].inputSchema["required"] == ["zip_code", "house_number"]
    assert "house_number_extension" not in by_name["kpn_check_internet_speed"].inputSchema["required"]
    assert by_name["kpn_check_sim_swap"].inputSchema["required"] == ["phone_number"]

    for tool in tools:
        assert tool.name.startswith("kpn_")
        assert tool.description, f"{tool.name} has no description"
        first_line = tool.description.strip().splitlines()[0]
        assert len(first_line) <= 100, f"{tool.name} first line too long: {first_line!r}"
        assert len(tool.description) <= 500, f"{tool.name} description too long"


# ---------------------------------------------------------------------------
# TC1 / TC2 -- kpn_check_disturbance
# ---------------------------------------------------------------------------


async def test_check_disturbance_returns_known_disturbance(mcp_app, kpn_http):
    kpn_http.set(
        _response(
            200,
            {
                "broadband": [
                    {
                        "id": "d-1",
                        "type": "outage",
                        "service": "I-TV",
                        "state": "open",
                        "cause": "fiber-cut",
                        "description": "Fiber cut near exchange",
                        "start_date": "2026-11-01T10:00:00Z",
                        "end_date": None,
                        "region": None,
                        "affected_elements_count": 3,
                    }
                ],
                "fixed": [],
                "mobile": [],
                "generic": [],
            },
        )
    )
    with credentials():
        result = await _call(mcp_app, "kpn_check_disturbance", {"zip_code": "1234AB", "house_number": 12})

    assert result["has_disturbance"] is True
    assert len(result["disturbances"]) == 1
    entry = result["disturbances"][0]
    assert entry["service"] == "I-TV"
    assert entry["state"] == "open"
    assert entry["description"] == "Fiber cut near exchange"
    assert "affected_elements_count" not in entry  # trimmed per field-trimming rule


async def test_check_disturbance_empty_is_not_error(mcp_app, kpn_http):
    kpn_http.set(_response(200, {"broadband": [], "fixed": [], "mobile": [], "generic": []}))
    with credentials():
        result = await _call(mcp_app, "kpn_check_disturbance", {"zip_code": "1234AB", "house_number": 12})

    assert result == {"has_disturbance": False, "disturbances": []}
    assert "error" not in result


# ---------------------------------------------------------------------------
# TC3 -- kpn_check_internet_speed
# ---------------------------------------------------------------------------


async def test_check_internet_speed_returns_technologies(mcp_app, kpn_http):
    kpn_http.set(
        _response(
            200,
            {
                "available_on_address": {
                    "technologies": [
                        {"name": "FIBER", "download": 500, "upload": 500},
                        {"name": "NoAccess", "download": 0, "upload": 0},
                    ],
                    "house_number_extensions": [],
                },
                "max_bandwidth": {"up": 500, "down": 500},
                "alerts": [],
            },
        )
    )
    with credentials():
        result = await _call(
            mcp_app, "kpn_check_internet_speed", {"zip_code": "1234AB", "house_number": 12}
        )

    assert result["max_download_mbps"] == 500
    assert result["max_upload_mbps"] == 500
    assert result["technologies"] == [{"name": "FIBER", "download": 500, "upload": 500}]


# ---------------------------------------------------------------------------
# TC5 / TC6 -- kpn_check_sim_swap
# ---------------------------------------------------------------------------


async def test_check_sim_swap_returns_latest_change(mcp_app, kpn_http):
    kpn_http.set(_response(200, {"latestSimChange": "2026-10-29T17:38:22.306Z"}))
    with credentials():
        result = await _call(mcp_app, "kpn_check_sim_swap", {"phone_number": "+31612345678"})

    assert result == {"latest_sim_change": "2026-10-29T17:38:22.306Z"}


async def test_check_sim_swap_unknown_number_is_not_found(mcp_app, kpn_http):
    kpn_http.set(_response(404, {"code": "SIM_SWAP.UNKNOWN_PHONE_NUMBER", "message": "not found"}))
    with credentials():
        result = await _call(mcp_app, "kpn_check_sim_swap", {"phone_number": "+31600000000"})

    assert result["error"]["code"] == "not_found"
    assert result["error"]["retryable"] is False


# ---------------------------------------------------------------------------
# TC9 -- error-mapping table, every documented status + a connect error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected_code", "expected_retryable"),
    [
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (409, "upstream_error", True),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
        (504, "upstream_error", True),
    ],
)
async def test_error_mapping_table(mcp_app, kpn_http, status_code, expected_code, expected_retryable):
    # 429/5xx are retried by api_client up to _MAX_RETRIES; queue enough
    # identical responses so the final mapped result is still deterministic.
    kpn_http.set([_response(status_code, {"code": "X"}) for _ in range(3)])
    with credentials():
        result = await _call(mcp_app, "kpn_check_sim_swap", {"phone_number": "+31612345678"})

    assert result["error"]["code"] == expected_code
    assert result["error"]["retryable"] is expected_retryable


async def test_error_mapping_connect_timeout(mcp_app, kpn_http, monkeypatch):
    # kpn_http already patched get_access_token and asyncio.sleep; only the
    # outbound request itself needs to raise here. Plain functions assigned
    # to a class attribute get bound on instance access, so this needs an
    # explicit `self` -- unlike _HttpStub, which is an already-bound instance.
    async def raise_timeout(self: object, method: str, path: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated connect timeout")

    monkeypatch.setattr(httpx.AsyncClient, "request", raise_timeout)

    with credentials():
        result = await _call(mcp_app, "kpn_check_sim_swap", {"phone_number": "+31612345678"})

    assert result["error"]["code"] == "upstream_error"
    assert result["error"]["retryable"] is True

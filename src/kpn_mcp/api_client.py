"""Async HTTP client wrapping KPN's three public developer-portal endpoints.

Each call raises KpnApiError on a non-2xx response; the tools layer maps
that to the structured error envelope (see tools/network.py, tools/identity.py
and the error-mapping table in docs/tickets/PRD-21262.md).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from kpn_mcp.auth import KpnAuthError, get_access_token
from kpn_mcp.config import settings

_CONNECT_TIMEOUT_SECONDS = 5.0
_READ_TIMEOUT_SECONDS = 30.0

# 429/5xx get a short bounded retry; everything else is not retried here --
# the tools layer decides retryability for the caller via the error envelope.
_MAX_RETRIES = 2
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class KpnApiError(Exception):
    """Carries KPN's status code and parsed error body for the tools layer to map."""

    def __init__(self, status_code: int, body: dict | str | None, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.message = message


class KpnApiClient:
    """One instance per request; holds the request's own KPN credentials.

    Never shared across requests and never stored outside the request's
    ContextVar-scoped lifetime (see server.py) -- this is what gives
    per-tenant isolation (AC5).
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = httpx.AsyncClient(
            base_url=settings.kpn_base_url,
            timeout=httpx.Timeout(_READ_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "KpnApiClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _bearer_headers(self) -> dict[str, str]:
        token = await get_access_token(self._http, self._client_id, self._client_secret)
        return {"Authorization": f"Bearer {token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        last_response: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                headers = await self._bearer_headers()
            except KpnAuthError as exc:
                raise KpnApiError(exc.status_code or 401, None, exc.message) from exc

            try:
                response = await self._http.request(method, path, headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue
                raise KpnApiError(0, None, f"Request to KPN failed: {exc}") from exc

            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                retry_after = response.headers.get("Retry-After")
                await asyncio.sleep(float(retry_after) if retry_after else _backoff_seconds(attempt))
                last_response = response
                continue

            last_response = response
            break

        assert last_response is not None
        if last_response.status_code >= 400:
            body = _safe_json(last_response)
            raise KpnApiError(last_response.status_code, body, f"KPN returned {last_response.status_code}")
        return last_response

    async def check_disturbance(self, zip_code: str, house_number: int) -> dict:
        response = await self._request(
            "GET",
            "/network/kpn/disturbance-check/address",
            params={"zip_code": zip_code, "house_number": house_number},
        )
        return response.json()

    async def check_internet_speed(
        self, zip_code: str, house_number: int, house_number_extension: str
    ) -> dict:
        service_address: dict[str, object] = {
            "house_number": house_number,
            "zip_code": zip_code,
        }
        if house_number_extension:
            service_address["house_number_extension"] = house_number_extension
        response = await self._request(
            "POST",
            "/network/kpn/internet-speed-check/offer",
            json={"service_address": service_address},
        )
        return response.json()

    async def check_sim_swap(self, phone_number: str) -> dict:
        response = await self._request(
            "POST",
            "/kpn/sim-swap",
            json={"phoneNumber": phone_number},
        )
        return response.json()


def _backoff_seconds(attempt: int) -> float:
    return 0.5 * (2**attempt)


def _safe_json(response: httpx.Response) -> dict | str | None:
    try:
        return response.json()
    except ValueError:
        return response.text or None

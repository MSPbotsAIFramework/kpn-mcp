"""Network-product tools: disturbance check and internet speed check."""

from __future__ import annotations

from typing import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from kpn_mcp.api_client import KpnApiClient, KpnApiError
from kpn_mcp.errors import map_kpn_error
from kpn_mcp.server import dumps, error_envelope

_READ_ONLY_IDEMPOTENT = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

# Descriptions are passed explicitly (rather than left as the function's
# docstring) because FastMCP uses `fn.__doc__` verbatim, with no dedent --
# an indented docstring would ship its leading whitespace to the agent as
# part of the description (SOP section 2.2: keep descriptions compact).
_DISTURBANCE_DESCRIPTION = (
    "Check current KPN network disturbances at a Dutch address.\n"
    'Args: zip_code is a Dutch postal code (e.g. "1234AB"); house_number is '
    "the street number. Returns all open broadband/fixed/mobile/generic "
    "disturbances for that address, or an empty list when there are none "
    "(no disturbances is a normal result, not an error)."
)

_INTERNET_SPEED_DESCRIPTION = (
    "Check maximum internet speed and available carrier technology at a Dutch address.\n"
    'Args: zip_code is a Dutch postal code (e.g. "1234AB"); house_number is the street '
    'number; house_number_extension is optional (e.g. "A"). Returns the fastest '
    "download/upload speed in Mbps and which technologies (fibre/copper) are "
    "available; an address with no access returns an empty technologies list, "
    "which is a normal result, not an error."
)


def register(mcp: FastMCP, client_factory: Callable[[], KpnApiClient | None]) -> None:
    @mcp.tool(description=_DISTURBANCE_DESCRIPTION, annotations=_READ_ONLY_IDEMPOTENT)
    async def kpn_check_disturbance(zip_code: str, house_number: int) -> str:
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "No KPN credentials for this request", False)

        async with client:
            try:
                raw = await client.check_disturbance(zip_code, house_number)
            except KpnApiError as exc:
                code, message, retryable = map_kpn_error(exc)
                return error_envelope(code, message, retryable)

        disturbances = []
        for bucket in ("broadband", "fixed", "mobile", "generic"):
            for item in raw.get(bucket, []) or []:
                disturbances.append(
                    {
                        "id": item.get("id"),
                        "service": item.get("service"),
                        "state": item.get("state"),
                        "cause": item.get("cause"),
                        "description": item.get("description"),
                        "start_date": item.get("start_date"),
                        "end_date": item.get("end_date"),
                        "region": item.get("region"),
                    }
                )
        return dumps({"has_disturbance": len(disturbances) > 0, "disturbances": disturbances})

    @mcp.tool(description=_INTERNET_SPEED_DESCRIPTION, annotations=_READ_ONLY_IDEMPOTENT)
    async def kpn_check_internet_speed(
        zip_code: str, house_number: int, house_number_extension: str = ""
    ) -> str:
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "No KPN credentials for this request", False)

        async with client:
            try:
                raw = await client.check_internet_speed(zip_code, house_number, house_number_extension)
            except KpnApiError as exc:
                code, message, retryable = map_kpn_error(exc)
                return error_envelope(code, message, retryable)

        available = raw.get("available_on_address", {}) or {}
        technologies = [
            {"name": tech.get("name"), "download": tech.get("download"), "upload": tech.get("upload")}
            for tech in available.get("technologies", []) or []
            if tech.get("name") != "NoAccess"
        ]
        max_bandwidth = raw.get("max_bandwidth", {}) or {}
        return dumps(
            {
                "max_download_mbps": max_bandwidth.get("down"),
                "max_upload_mbps": max_bandwidth.get("up"),
                "technologies": technologies,
            }
        )

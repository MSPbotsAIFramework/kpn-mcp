"""Identity/fraud-signal tool: SIM-swap check."""

from __future__ import annotations

from typing import Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from kpn_mcp.api_client import KpnApiClient, KpnApiError
from kpn_mcp.errors import map_kpn_error
from kpn_mcp.server import dumps, error_envelope

_READ_ONLY_IDEMPOTENT = ToolAnnotations(readOnlyHint=True, idempotentHint=True)

# Passed explicitly rather than left as the docstring -- see network.py for why
# (FastMCP ships fn.__doc__ verbatim, with no dedent).
_SIM_SWAP_DESCRIPTION = (
    "Check the most recent SIM-swap date for a mobile number.\n"
    'Args: phone_number in E.164 format (e.g. "+31612345678"). Use this as one '
    "fraud/account-takeover signal before a sensitive action on the account tied "
    "to this number; this tool returns the raw fact only, not a risk score. A "
    "number KPN does not recognize returns a not_found error, not an exception."
)


def register(mcp: FastMCP, client_factory: Callable[[], KpnApiClient | None]) -> None:
    @mcp.tool(description=_SIM_SWAP_DESCRIPTION, annotations=_READ_ONLY_IDEMPOTENT)
    async def kpn_check_sim_swap(phone_number: str) -> str:
        client = client_factory()
        if client is None:
            return error_envelope("not_configured", "No KPN credentials for this request", False)

        async with client:
            try:
                raw = await client.check_sim_swap(phone_number)
            except KpnApiError as exc:
                code, message, retryable = map_kpn_error(exc)
                return error_envelope(code, message, retryable)

        return dumps({"latest_sim_change": raw.get("latestSimChange")})

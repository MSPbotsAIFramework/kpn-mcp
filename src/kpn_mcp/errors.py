"""Maps KPN HTTP status codes to the fixed error-envelope vocabulary.

Table source: docs/tickets/PRD-21262.md, Tech design "Data & API contract".
Applied uniformly to all three tools (Decisions made by DEV01, item 5):
only SIM Swap's documentation published an explicit error-code table, so
the same table is assumed for the two Network-product endpoints too.
"""

from __future__ import annotations

from kpn_mcp.api_client import KpnApiError

_STATUS_TO_CODE: dict[int, tuple[str, bool]] = {
    400: ("invalid_argument", False),
    401: ("unauthorized", False),
    403: ("unauthorized", False),
    404: ("not_found", False),
    409: ("upstream_error", True),  # concurrent request for the same MSISDN; safe to retry shortly
    429: ("rate_limited", True),
    500: ("upstream_error", True),
    502: ("upstream_error", True),
    503: ("upstream_error", True),
    504: ("upstream_error", True),
}

_DEFAULT = ("upstream_error", True)


def map_kpn_error(exc: KpnApiError) -> tuple[str, str, bool]:
    """Return (code, message, retryable) for a KpnApiError.

    status_code == 0 means the request never got an HTTP response at all
    (connection error / timeout), which also maps to upstream_error/retryable.
    """
    code, retryable = _STATUS_TO_CODE.get(exc.status_code, _DEFAULT)
    return code, exc.message, retryable

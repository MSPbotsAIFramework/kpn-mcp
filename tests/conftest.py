"""Shared test fixtures."""

from __future__ import annotations

import pytest

from kpn_mcp import auth as auth_module


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """Every test starts with an empty OAuth token cache -- tests must not
    see tokens cached by a previous test's credentials.
    """
    auth_module._clear_cache_for_testing()
    yield
    auth_module._clear_cache_for_testing()

"""Entrypoint: build the Starlette app (health probe + mounted MCP app) and
serve it with uvicorn.

The MCP app returned by `streamable_http_app()` already wires its own
lifespan (`session_manager.run()`); this module adds the health route and
credential middleware directly onto that same Starlette instance instead
of `Mount()`-ing it inside a second outer app, since `Mount()` does not
run a sub-app's lifespan (SOP section 7) -- the symptom is `/mcp` failing
with "Task group is not initialized" while `/health` still returns 200.
"""

from __future__ import annotations

import uvicorn
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from kpn_mcp.config import settings
from kpn_mcp.server import CredentialHeaderMiddleware, client_factory, create_mcp_server
from kpn_mcp.tools import identity, network


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app() -> CredentialHeaderMiddleware:
    mcp = create_mcp_server()
    network.register(mcp, client_factory)
    identity.register(mcp, client_factory)

    app = mcp.streamable_http_app()
    app.router.routes.insert(0, Route("/health", health, methods=["GET"]))

    return CredentialHeaderMiddleware(app, exempt_paths=frozenset({"/health"}))


def main() -> None:
    uvicorn.run(build_app(), host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()

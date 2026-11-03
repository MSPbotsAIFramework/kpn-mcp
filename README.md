# kpn-mcp

MCP server for KPN (Dutch telecom operator), exposing three read-only tools against KPN's
public developer-portal APIs: network disturbance/outage status, internet speed/availability,
and SIM-swap fraud signal, each keyed by a Dutch address or mobile number.

- Transport: MCP Streamable HTTP (`POST /mcp`), stateless, `GET /health` for liveness.
- Stack: Python 3.12, FastMCP, httpx, pydantic-settings.
- License: Apache-2.0. Copyright MSPbots.ai.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Authentication headers

Every `/mcp` request must carry both of the following headers. Credentials are read
per request only -- never from an environment variable or a configuration file.

| Header | Required | Meaning | Where to obtain |
|---|---|---|---|
| `X-Kpn-Client-Id` | Yes | KPN OAuth2 client ID | KPN Developer Portal (`developer.kpn.com`) → app registration |
| `X-Kpn-Client-Secret` | Yes | KPN OAuth2 client secret | KPN Developer Portal (`developer.kpn.com`) → app registration |

Missing either header returns `401` with a body listing the missing header name(s); no call
reaches KPN in that case.

## Tools

| Tool | Args | Notes |
|---|---|---|
| `kpn_check_disturbance` | `zip_code`, `house_number` | Current network disturbances for a Dutch address. Empty result is not an error. |
| `kpn_check_internet_speed` | `zip_code`, `house_number`, `house_number_extension` (optional) | Max download/upload speed and available technologies (fibre/copper) for a Dutch address. |
| `kpn_check_sim_swap` | `phone_number` (E.164) | Most recent SIM-swap date for a mobile number, as one fraud/account-takeover signal. |

All three tools are read-only and idempotent. Errors use the fixed envelope
`{"error": {"code", "message", "retryable"}}`; see
`docs/tickets/PRD-21262.md` ("Data & API contract") for the full status-code mapping table.

## Running locally

```bash
uv sync
uv run python -m kpn_mcp
# in another shell:
curl -X POST http://localhost:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-Kpn-Client-Id: <your test client id>' -H 'X-Kpn-Client-Secret: <your test client secret>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Or via `docker-compose.yml`:

```bash
docker compose up --build
```

## Tests

```bash
uv run pytest
```

Unit tests mock the KPN API (`httpx.AsyncClient.request`); no network traffic leaves the
test process. One test case (speed-check against a real address) needs a real KPN
developer-portal account and is documented as a manual case in `docs/tickets/PRD-21262.ac.json`
(`TC4`) -- it does not block development or deployment.

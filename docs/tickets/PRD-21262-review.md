# PRD-21262 · Code review

## Round 1 · 2026-11-03 · reviewed dev/PRD-21262 @ 853a01c (base 351cff1)

Verdict: changes requested

### Findings

1. [must-fix] docs/tickets/PRD-21262.md:318 — contains the Chinese word "必须" inside an otherwise-English sentence ("Manual end-to-end with a real Agent client (§10, "必须"): not run ..."). SOP §0.4 requires the repo to be entirely English with no Chinese content, and `references/mcp-track.md` §4.3's review checklist lists "no Chinese in the repo" as a must-fix condition. This line was introduced by the final "freeze" commit (`853a01c`, which added the Self-test/Handoff sections) — `git show d9a06a8:docs/tickets/PRD-21262.md` confirms the word is absent at the commit the dev leg's own `grep -rnP '[\x{4e00}-\x{9fff}]' ...` gate ran clean against, so the Self-test's "No Chinese content: clean" line is stale relative to the doc actually being submitted for review. Confirmed by re-running the same grep on the current HEAD (`853a01c`): it is the only hit in the repo. Fix: replace the Chinese character with an English equivalent (e.g. `(§10, a "must" requirement)` or just drop the quote marks), then re-run the Chinese-content grep on the new commit before re-submitting.

### Independent verification performed this round

- `uv sync && uv run pytest -q` on `dev/PRD-21262 @ 853a01c`: 22 passed, matches the Self-test table.
- `uv run mypy`: "Success: no issues found in 10 source files", matches the Self-test table.
- `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .`: 1 hit (the finding above); the Self-test table's "clean" result is stale as explained above.
- `docker build --platform linux/amd64 -t kpn-mcp:review .`: succeeds.
- Ran the built image, `curl`'d directly: `GET /health` -> `200 {"status":"ok"}`; `POST /mcp` with no credential headers -> `401 {"error":"missing_headers","missing":["X-Kpn-Client-Id","X-Kpn-Client-Secret"]}`; `POST /mcp` with both headers and `tools/list` (no `initialize` first) -> `200` listing all 3 tools (`kpn_check_disturbance`, `kpn_check_internet_speed`, `kpn_check_sim_swap`) — confirms `stateless_http=True` and matches the Self-test's "Live contract check" row.
- Read `src/kpn_mcp/{server,auth,api_client,errors,config,__main__}.py`, `src/kpn_mcp/tools/{network,identity}.py`, `tests/test_tools.py`, `tests/test_middleware.py` in full: credential Headers are read into a `ContextVar` and reset in a `finally` block (no module-level credential state); the OAuth token cache is keyed by `sha256(client_id:client_secret)` with a TTL from `expires_in`, matching the SOP §3.4 fingerprint-keyed exception; `KpnApiClient` instances and their `httpx.AsyncClient` are created per call and closed via `async with client:` in every tool (no connection leak); the error-mapping table in `errors.py` matches the Tech design's table exactly (plus an extra, harmless `502` entry not required by the design).
- `diff` of the README's "MSPbots Connector" section against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md`: identical content (only a trailing-blank-line difference from my own extraction, not a real diff).

No other must-fix found. The implementation matches the Tech design's tool contracts, error envelope, and multi-tenant isolation design; test coverage (TC1-TC3, TC5-TC9) is real and passes; TC4 is correctly left as a documented manual/blocked case needing a real vendor account, which does not block per `mcp-track.md` §2.5.

### Fixes (round 1)

1. **docs/tickets/PRD-21262.md:318** — replaced the Chinese word "必须" with the reviewer's suggested English wording: the line now reads `**Manual end-to-end with a real Agent client** (§10, a "must" requirement): not run — ...`. No other text on the line or elsewhere in the frozen main doc was touched. Fixed in this round's commit (sha in the `[DEV]` stub).
2. **Gate re-run on the fixed commit** (same commands as the Self-test table, dev-lock reacquired, `main` had not moved since `853a01c` so no re-sync was needed):
   - `grep -rnP '[\x{4e00}-\x{9fff}]' --exclude-dir=.git --exclude-dir=.venv .` — the Chinese character at `PRD-21262.md:318` is gone. One hit remains: this file's own line 9 above, which *quotes* the original offending string as part of describing the finding. That quotation was added by the reviewer in the prior round's commit (`924cb9e`) as part of the audit trail, is not part of any deliverable doc or code, and is not something this round's must-fix list asked to change — left as-is per the "only touch the listed must-fix" rule. Flagging it here rather than silently passing over it.
   - `uv run pytest` substitute (`uv` is unavailable on `dev03`; used a `python3.12 -m venv` + `pip install -e .` + the `[dependency-groups].dev` packages, pinned to the same version ranges as `pyproject.toml`) — 22 passed, matches the Self-test table and this round's independent re-run.
   - `uv run mypy` substitute (same venv) — `Success: no issues found in 10 source files`, matches.
   - `sudo docker build --platform linux/amd64 -t kpn-mcp:review2 .` — succeeds; `docker inspect` confirms `Config.User = app` (non-root) and the `HEALTHCHECK` is defined with `curl -fsS http://localhost:8080/health`.
   - Ran the built image (`-p 18273:8080`, matching the Dockerfile's actual `EXPOSE 8080` / `MCP_HTTP_PORT=8080`, not the port assumed on the first attempt): `GET /health` → `200 {"status":"ok"}`; container health transitions to `healthy`; `POST /mcp` with no credential headers → `401 {"error":"missing_headers","missing":["X-Kpn-Client-Id","X-Kpn-Client-Secret"]}`; `POST /mcp` with both headers, `tools/list` only (no `initialize` first) → `200`, lists all 3 tools (`kpn_check_disturbance`, `kpn_check_internet_speed`, `kpn_check_sim_swap`) with their schemas — matches the Self-test's "Live contract check" row and this round's independent verification.
   - No new failures, no regressions. `ac.json` unchanged — the must-fix was a documentation-only defect, no test case's result or evidence changes.

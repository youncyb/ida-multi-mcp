# 07. Transport and Protocol Architecture

Last updated: 2026-09-12

## Governance Alignment
- Authority order: `docs/.ssot/contracts/*` -> `docs/.ssot/PRD.md` -> `docs/.ssot/decisions/*` -> this document.
- Contract reference baseline: `docs/.ssot/contracts/INDEX.md` (v1 baseline).
- This document explains architecture and does not redefine contract semantics.


## Transport Layers
- Client <-> Aggregator: MCP stdio (default) or opt-in Streamable HTTP (`POST /mcp` via `--http`)
- Aggregator <-> IDA instance: HTTP JSON-RPC (`POST /mcp`) on loopback

Opt-in HTTP is implemented by `src/ida_multi_mcp/server.py` using `src/ida_multi_mcp/vendor/zeromcp/mcp.py`. IDA plugin HTTP (`src/ida_multi_mcp/ida_mcp/zeromcp/mcp.py`) stays loopback-only.

## Protocol Calls
Central-server-side core methods:
- `tools/list`: returns the local tool cache
- `tools/call`: invokes a local management tool or a remote IDA tool

Provided by the IDA side (zeromcp):
- `initialize`, `ping`, `tools/*`, `resources/*`, `prompts/*`, `notifications/cancelled`

## Routing Contract
- Immediate error if `instance_id` is missing
- Strip `arguments.instance_id` before forwarding
- Respect the IDA response envelope as-is; apply structured normalization only when necessary


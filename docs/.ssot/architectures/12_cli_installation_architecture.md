# 12. CLI and Installation Architecture

Last updated: 2026-09-12

## Governance Alignment
- Authority order: `docs/.ssot/contracts/*` -> `docs/.ssot/PRD.md` -> `docs/.ssot/decisions/*` -> this document.
- Contract reference baseline: `docs/.ssot/contracts/INDEX.md` (v1 baseline).
- This document explains architecture and does not redefine contract semantics.


## CLI Surface
- Default: run the MCP server (stdio)
- `--http [--host] [--port] [--allowed-host]`: Streamable HTTP aggregator (`POST /mcp`)
- `--install`: deploy the IDA plugin loader + automate MCP client configuration
- `--uninstall`: remove plugin/registry/client configuration
- `--list`: list registered instances
- `--config`: print MCP configuration JSON (`--config --http` prints OpenCode remote JSON)

`--install` still writes stdio client configs. Remote OpenCode (`type: remote`) is configured on the client host, not by VM-side `--install`.

## Installation Architecture
- Install the plugin loader into the IDA plugins directory, preferring a symlink
- Fall back to copy on failure
- Automatically update multiple MCP client config files (JSON/TOML)

## Platform Handling
- Windows rename failure (WinError 5) handled via overwrite fallback
- Built-in per-OS config-path table

## Operational Risks
- If a client process has a config file locked, part of installation may be skipped
- A restart notice is mandatory


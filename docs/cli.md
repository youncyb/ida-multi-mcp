# CLI Reference

Last updated: 2026-09-12

[← back to README](../README.md)

## CLI Commands

### `ida-multi-mcp`
Start the MCP server (stdio). Used by MCP clients. This is the default command.

```bash
ida-multi-mcp
ida-multi-mcp --idalib-python /path/to/python3  # custom Python for headless sessions
```

### `ida-multi-mcp --http [--host ADDR] [--port N] [--allowed-host NAME]`
Start the aggregator over Streamable HTTP (`POST /mcp`) instead of stdio. IDA plugins stay on `127.0.0.1`; only this process is reachable from another machine.

```bash
# VM / remote OpenCode client (bind all interfaces, then point the client at the VM IP)
ida-multi-mcp --http --host 0.0.0.0 --port 8745

# Print OpenCode V2 remote config for that bind
ida-multi-mcp --config --http --host 192.168.239.10 --port 8745
```

`--host` / `--port` / `--allowed-host` require `--http`. `--allowed-host` is repeatable and is only needed for DNS names in the `Host` header; IP-literal hosts are accepted automatically on a non-loopback bind.

OpenCode on the client machine:

```jsonc
{
  "mcp": {
    "servers": {
      "ida-multi-mcp": {
        "type": "remote",
        "url": "http://<VM-IP>:8745/mcp",
        "oauth": false
      }
    }
  }
}
```

`oauth` must be `false`: this server has no OAuth endpoint. Default remains stdio; do not use `--http` on a public network.

### `ida-multi-mcp --list`
List all registered IDA instances.

```bash
ida-multi-mcp --list
```

### `ida-multi-mcp --install [--ida-dir DIR]`
Install the IDA plugin and auto-configure all detected MCP clients (Claude Code, Claude Desktop, Cursor, Windsurf, VS Code, Zed, and 20+ more).

```bash
ida-multi-mcp --install
ida-multi-mcp --install --ida-dir "C:\Program Files\IDA Pro 9.0"  # Windows custom path
```

### `ida-multi-mcp --uninstall [--ida-dir DIR]`
Remove the IDA plugin, clean up registry, and remove MCP client configurations.

```bash
ida-multi-mcp --uninstall
```

### `ida-multi-mcp --config`
Print the MCP client configuration JSON for easy reference. With `--http`, prints OpenCode V2 `type: remote` JSON instead of the stdio `mcpServers` form.

```bash
ida-multi-mcp --config
ida-multi-mcp --config --http --host 192.168.239.10 --port 8745
```

"""Opt-in Streamable HTTP transport for the aggregator (OpenCode type=remote)."""

import http.client
import json
from argparse import Namespace
from unittest.mock import patch

import pytest

from ida_multi_mcp.server import (
    HTTP_DEFAULT_PORT,
    advertised_http_url,
    configure_http_host_policy,
    serve,
)
from ida_multi_mcp.vendor.zeromcp.mcp import (
    McpServer,
    _hostname_from_host_header,
    _is_ip_literal,
)


def _post_mcp(port: int, payload: dict, extra_headers: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", "/mcp", json.dumps(payload).encode("utf-8"), headers)
        response = conn.getresponse()
        body = response.read()
        return response.status, body
    finally:
        conn.close()


def _get_mcp(port: int, extra_headers: dict | None = None):
    headers = extra_headers or {}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/mcp", headers=headers)
        response = conn.getresponse()
        body = response.read()
        return response.status, body
    finally:
        conn.close()


@pytest.fixture
def http_mcp():
    server = McpServer("test-server", version="0.1.0")
    server.serve("127.0.0.1", 0, background=True)
    assert server._http_server is not None
    port = server._http_server.server_address[1]
    try:
        yield server, port
    finally:
        server.stop()


class TestHostHeaderParse:
    def test_ipv4_with_port(self):
        assert _hostname_from_host_header("192.168.239.10:8745") == "192.168.239.10"

    def test_ipv6_brackets(self):
        assert _hostname_from_host_header("[::1]:8745") == "::1"

    def test_localhost_bare(self):
        assert _hostname_from_host_header("localhost") == "localhost"

    def test_dns_with_port(self):
        assert _hostname_from_host_header("ida-vm.local:8745") == "ida-vm.local"

    def test_ip_literal_detect(self):
        assert _is_ip_literal("10.0.0.1") is True
        assert _is_ip_literal("ida-vm") is False


class TestHostPolicy:
    def test_loopback_bind_does_not_allow_ip_literals(self):
        mcp = McpServer("t")
        configure_http_host_policy(mcp, "127.0.0.1")
        assert mcp.allow_ip_literal_hosts is False

    def test_wildcard_bind_allows_ip_literals_and_extra_dns(self):
        mcp = McpServer("t")
        configure_http_host_policy(mcp, "0.0.0.0", ["ida-vm"])
        assert mcp.allow_ip_literal_hosts is True
        assert "ida-vm" in mcp.allowed_hosts
        assert "127.0.0.1" in mcp.allowed_hosts

    def test_specific_lan_bind_is_allowlisted(self):
        mcp = McpServer("t")
        configure_http_host_policy(mcp, "192.168.239.10")
        assert mcp.allow_ip_literal_hosts is True
        assert "192.168.239.10" in mcp.allowed_hosts


class TestHttpRoundtrip:
    def test_initialize_json(self, http_mcp):
        _server, port = http_mcp
        status, body = _post_mcp(
            port,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
        )
        assert status == 200
        parsed = json.loads(body)
        assert parsed["result"]["serverInfo"]["name"] == "test-server"

    def test_get_mcp_is_405(self, http_mcp):
        _server, port = http_mcp
        status, _body = _get_mcp(port)
        assert status == 405

    def test_default_rejects_lan_host_header(self, http_mcp):
        _server, port = http_mcp
        status, body = _post_mcp(
            port,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            extra_headers={"Host": "192.168.239.10:8745"},
        )
        assert status == 403
        assert b"invalid Host header" in body

    def test_default_rejects_dns_rebinding_host(self, http_mcp):
        _server, port = http_mcp
        status, _body = _post_mcp(
            port,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            extra_headers={"Host": "evil.example:8745"},
        )
        assert status == 403

    def test_ip_literal_host_allowed_when_enabled(self, http_mcp):
        server, port = http_mcp
        configure_http_host_policy(server, "0.0.0.0")
        status, body = _post_mcp(
            port,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            extra_headers={"Host": "192.168.239.10:8745"},
        )
        assert status == 200
        assert json.loads(body)["result"] == {}

    def test_dns_host_still_rejected_without_allowlist(self, http_mcp):
        server, port = http_mcp
        configure_http_host_policy(server, "0.0.0.0")
        status, _body = _post_mcp(
            port,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            extra_headers={"Host": "evil.example:8745"},
        )
        assert status == 403

    def test_allowed_host_dns_name(self, http_mcp):
        server, port = http_mcp
        configure_http_host_policy(server, "0.0.0.0", ["ida-vm.local"])
        status, body = _post_mcp(
            port,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            extra_headers={"Host": "ida-vm.local:8745"},
        )
        assert status == 200
        assert json.loads(body)["result"] == {}


class TestAdvertisedUrl:
    def test_specific_host(self):
        assert advertised_http_url("192.168.239.10", 8745) == (
            "http://192.168.239.10:8745/mcp"
        )

    def test_ipv6_host_is_bracketed(self):
        assert advertised_http_url("::1", 8745) == "http://[::1]:8745/mcp"


class TestServeWiring:
    def test_http_kwargs_reach_run(self):
        captured = {}

        class Fake:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, **kwargs):
                captured.update(kwargs)

        with patch("ida_multi_mcp.server.IdaMultiMcpServer", Fake):
            serve(
                http_host="0.0.0.0",
                http_port=9000,
                allowed_hosts=["ida-vm"],
            )
        assert captured["http_host"] == "0.0.0.0"
        assert captured["http_port"] == 9000
        assert captured["allowed_hosts"] == ["ida-vm"]

    def test_stdio_default_leaves_http_unset(self):
        captured = {}

        class Fake:
            def __init__(self, *args, **kwargs):
                pass

            def run(self, **kwargs):
                captured.update(kwargs)

        with patch("ida_multi_mcp.server.IdaMultiMcpServer", Fake):
            serve()
        assert captured["http_host"] is None
        assert captured["http_port"] is None


class TestCliHttp:
    def test_parser_http_flags(self):
        from ida_multi_mcp.__main__ import build_parser

        args = build_parser().parse_args(
            ["--http", "--host", "0.0.0.0", "--port", "9000"]
        )
        assert args.http is True
        assert args.host == "0.0.0.0"
        assert args.port == 9000

    def test_allowed_host_repeatable(self):
        from ida_multi_mcp.__main__ import build_parser

        args = build_parser().parse_args(
            ["--http", "--allowed-host", "ida-vm", "--allowed-host", "ida.local"]
        )
        assert args.allowed_host == ["ida-vm", "ida.local"]

    def test_host_without_http_errors(self, capsys):
        from ida_multi_mcp.__main__ import main

        with patch("sys.argv", ["ida-multi-mcp", "--host", "0.0.0.0"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        assert "--http" in capsys.readouterr().err

    def test_config_http_prints_opencode_remote(self, capsys):
        from ida_multi_mcp.__main__ import cmd_config

        rc = cmd_config(
            Namespace(http=True, host="192.168.239.10", port=8745, allowed_host=None)
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        entry = payload["mcp"]["servers"]["ida-multi-mcp"]
        assert entry["type"] == "remote"
        assert entry["url"] == "http://192.168.239.10:8745/mcp"
        assert entry["oauth"] is False

    def test_config_http_default_port(self, capsys):
        from ida_multi_mcp.__main__ import cmd_config

        cmd_config(Namespace(http=True, host="10.0.0.2", port=None, allowed_host=None))
        entry = json.loads(capsys.readouterr().out)["mcp"]["servers"]["ida-multi-mcp"]
        assert entry["url"] == f"http://10.0.0.2:{HTTP_DEFAULT_PORT}/mcp"

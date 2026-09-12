"""Singleton HTTP aggregator auto-start (one listener for N IDA processes)."""

import socket
import threading
import time
from unittest.mock import MagicMock

import pytest

from ida_multi_mcp.http_aggregator import (
    EnsureResult,
    aggregator_listening,
    ensure_http_aggregator,
    http_auto_enabled,
    probe_host,
)


class TestProbe:
    def test_wildcard_probes_loopback(self):
        assert probe_host("0.0.0.0") == "127.0.0.1"

    def test_specific_host_unchanged(self):
        assert probe_host("192.168.239.10") == "192.168.239.10"

    def test_listening_true_and_false(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert aggregator_listening("127.0.0.1", port) is True
        finally:
            sock.close()
        assert aggregator_listening("127.0.0.1", port) is False


class TestEnsure:
    def test_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("IDA_MCP_HTTP", "0")
        assert http_auto_enabled() is False
        result = ensure_http_aggregator(state_dir=tmp_path, port=8745)
        assert result.action == "disabled"

    def test_already_running_does_not_spawn(self, tmp_path):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        spawned = []

        def popen(*_a, **_k):
            spawned.append(1)
            raise AssertionError("must not spawn")

        try:
            result = ensure_http_aggregator(
                host="127.0.0.1",
                port=port,
                state_dir=tmp_path,
                python_executable="python",
                _popen=popen,
            )
        finally:
            sock.close()
        assert result.action == "already_running"
        assert spawned == []
        assert result.url.endswith(f":{port}/mcp")

    def test_spawns_when_not_listening(self, tmp_path):
        listening = {"on": False}
        spawned = []

        def probe(_host, _port):
            return listening["on"]

        def popen(cmd, **_kwargs):
            spawned.append(cmd)
            listening["on"] = True
            proc = MagicMock()
            proc.pid = 4242
            proc.poll.return_value = None
            return proc

        result = ensure_http_aggregator(
            host="0.0.0.0",
            port=8745,
            state_dir=tmp_path,
            python_executable="python",
            ready_timeout=1.0,
            _probe=probe,
            _popen=popen,
        )
        assert result.action == "started"
        assert result.pid == 4242
        assert spawned[0][-5:] == [
            "--http", "--host", "0.0.0.0", "--port", "8745",
        ]

    def test_concurrent_calls_spawn_once(self, tmp_path):
        listening = {"on": False}
        spawned = []
        lock = threading.Lock()

        def probe(_host, _port):
            return listening["on"]

        def popen(cmd, **_kwargs):
            time.sleep(0.15)
            with lock:
                spawned.append(cmd)
                listening["on"] = True
            proc = MagicMock()
            proc.pid = 7
            proc.poll.return_value = None
            return proc

        results: list[EnsureResult] = []

        def worker():
            results.append(
                ensure_http_aggregator(
                    host="127.0.0.1",
                    port=8745,
                    state_dir=tmp_path,
                    python_executable="python",
                    ready_timeout=2.0,
                    _probe=probe,
                    _popen=popen,
                )
            )

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(spawned) == 1
        actions = {r.action for r in results}
        assert actions <= {"started", "already_running"}
        assert "started" in actions

    def test_child_exit_before_listen_is_spawn_failed(self, tmp_path):
        def probe(_host, _port):
            return False

        def popen(*_a, **_k):
            proc = MagicMock()
            proc.pid = 9
            proc.poll.return_value = 1
            return proc

        result = ensure_http_aggregator(
            host="127.0.0.1",
            port=8745,
            state_dir=tmp_path,
            python_executable="python",
            ready_timeout=1.0,
            _probe=probe,
            _popen=popen,
        )
        assert result.action == "spawn_failed"


class TestAddrInUse:
    def test_eaddrinuse_is_detected(self):
        import errno

        from ida_multi_mcp.server import _is_addr_in_use

        assert _is_addr_in_use(OSError(errno.EADDRINUSE, "in use")) is True
        other = OSError(errno.EPERM, "denied")
        other.winerror = 10048
        assert _is_addr_in_use(other) is True
        assert _is_addr_in_use(OSError(errno.EPERM, "denied")) is False

    def test_run_returns_when_serve_raises_eaddrinuse(self, tmp_path, monkeypatch):
        import errno

        from ida_multi_mcp.server import IdaMultiMcpServer

        server = IdaMultiMcpServer(str(tmp_path / "instances.json"))
        monkeypatch.setattr(
            server.server,
            "serve",
            lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EADDRINUSE, "in use")),
        )
        server.run(http_host="127.0.0.1", http_port=8745)
        assert server.server._running is False

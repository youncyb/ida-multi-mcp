"""Singleton Streamable HTTP aggregator started from the IDA GUI plugin.

Multiple IDA processes may call ``ensure_http_aggregator`` at once. Only the
first one spawns ``python -m ida_multi_mcp --http``; later callers probe the
bind and return. The aggregator is a separate process (not in-process in IDA)
and is left running when databases close.

Disable with ``IDA_MCP_HTTP=0``. Override bind with ``IDA_MCP_HTTP_HOST`` /
``IDA_MCP_HTTP_PORT``.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .filelock import FileLock, FileLockTimeout

HTTP_AUTO_DEFAULT_HOST = "0.0.0.0"
HTTP_AUTO_DEFAULT_PORT = 8745
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::", ""})
_DISABLE_VALUES = frozenset({"0", "false", "off", "no"})


@dataclass(frozen=True)
class EnsureResult:
    action: str  # disabled | already_running | started | spawn_failed | lock_timeout
    host: str
    port: int
    pid: int | None = None
    url: str | None = None
    error: str | None = None


def http_auto_enabled() -> bool:
    raw = os.environ.get("IDA_MCP_HTTP", "1").strip().lower()
    return raw not in _DISABLE_VALUES


def http_bind_host() -> str:
    return os.environ.get("IDA_MCP_HTTP_HOST", HTTP_AUTO_DEFAULT_HOST).strip() or HTTP_AUTO_DEFAULT_HOST


def http_bind_port() -> int:
    raw = os.environ.get("IDA_MCP_HTTP_PORT", "").strip()
    if not raw:
        return HTTP_AUTO_DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        return HTTP_AUTO_DEFAULT_PORT
    if not (1 <= port <= 65535):
        return HTTP_AUTO_DEFAULT_PORT
    return port


def aggregator_state_dir() -> Path:
    override = os.environ.get("IDA_MULTI_MCP_REGISTRY_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve().parent
    return Path.home() / ".ida-mcp"


def probe_host(bind_host: str) -> str:
    """Address used to check whether the aggregator is accepting connections."""
    if bind_host in _WILDCARD_BINDS:
        return "127.0.0.1"
    return bind_host


def aggregator_listening(host: str, port: int, timeout: float = 0.3) -> bool:
    target = probe_host(host)
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False


def _python_executable() -> str:
    override = os.environ.get("IDA_MCP_HTTP_PYTHON", "").strip()
    if override:
        return override
    from .__main__ import get_python_executable

    return get_python_executable()


def _spawn_cmd(python_executable: str, host: str, port: int) -> list[str]:
    return [
        python_executable,
        "-m",
        "ida_multi_mcp",
        "--http",
        "--host",
        host,
        "--port",
        str(port),
    ]


def ensure_http_aggregator(
    *,
    host: str | None = None,
    port: int | None = None,
    state_dir: str | Path | None = None,
    python_executable: str | None = None,
    ready_timeout: float = 5.0,
    _probe: Callable[[str, int], bool] | None = None,
    _popen: Callable[..., Any] | None = None,
) -> EnsureResult:
    """Start the HTTP aggregator if it is not already listening.

    Safe to call from every IDA GUI instance. Uses a file lock plus a TCP
    probe so concurrent opens produce one listener.
    """
    bind_host = host if host is not None else http_bind_host()
    bind_port = port if port is not None else http_bind_port()
    if not http_auto_enabled():
        return EnsureResult("disabled", bind_host, bind_port, error="IDA_MCP_HTTP=0")

    probe = _probe or (lambda h, p: aggregator_listening(h, p))
    popen = _popen or subprocess.Popen
    python = python_executable or _python_executable()
    base = Path(state_dir) if state_dir is not None else aggregator_state_dir()
    base.mkdir(parents=True, exist_ok=True)
    lock_path = str(base / "http-aggregator.lock")

    if probe(bind_host, bind_port):
        return EnsureResult(
            "already_running",
            bind_host,
            bind_port,
            url=_url(bind_host, bind_port),
        )

    try:
        with FileLock(lock_path, timeout=5.0):
            if probe(bind_host, bind_port):
                return EnsureResult(
                    "already_running",
                    bind_host,
                    bind_port,
                    url=_url(bind_host, bind_port),
                )
            return _spawn_locked(
                bind_host,
                bind_port,
                base,
                python,
                ready_timeout,
                probe,
                popen,
            )
    except FileLockTimeout as exc:
        if probe(bind_host, bind_port):
            return EnsureResult(
                "already_running",
                bind_host,
                bind_port,
                url=_url(bind_host, bind_port),
            )
        return EnsureResult(
            "lock_timeout",
            bind_host,
            bind_port,
            error=str(exc),
        )


def _url(bind_host: str, port: int) -> str:
    from .server import advertised_http_url

    return advertised_http_url(bind_host, port)


def _spawn_locked(
    bind_host: str,
    bind_port: int,
    base: Path,
    python: str,
    ready_timeout: float,
    probe: Callable[[str, int], bool],
    popen: Callable[..., Any],
) -> EnsureResult:
    log_path = base / "http-aggregator.log"
    cmd = _spawn_cmd(python, bind_host, bind_port)
    try:
        log_f = open(log_path, "a", encoding="utf-8")
    except OSError as exc:
        return EnsureResult("spawn_failed", bind_host, bind_port, error=str(exc))

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_f,
        "stderr": log_f,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
        kwargs["close_fds"] = True

    try:
        proc = popen(cmd, **kwargs)
    except Exception as exc:
        log_f.close()
        return EnsureResult("spawn_failed", bind_host, bind_port, error=str(exc))
    finally:
        try:
            log_f.close()
        except OSError:
            pass

    deadline = time.monotonic() + max(0.1, ready_timeout)
    while time.monotonic() < deadline:
        if probe(bind_host, bind_port):
            return EnsureResult(
                "started",
                bind_host,
                bind_port,
                pid=getattr(proc, "pid", None),
                url=_url(bind_host, bind_port),
            )
        poll = getattr(proc, "poll", None)
        if callable(poll) and poll() is not None:
            if probe(bind_host, bind_port):
                return EnsureResult(
                    "already_running",
                    bind_host,
                    bind_port,
                    pid=getattr(proc, "pid", None),
                    url=_url(bind_host, bind_port),
                )
            return EnsureResult(
                "spawn_failed",
                bind_host,
                bind_port,
                pid=getattr(proc, "pid", None),
                error=f"aggregator exited before listening (see {log_path})",
            )
        time.sleep(0.05)

    if probe(bind_host, bind_port):
        return EnsureResult(
            "started",
            bind_host,
            bind_port,
            pid=getattr(proc, "pid", None),
            url=_url(bind_host, bind_port),
        )
    return EnsureResult(
        "spawn_failed",
        bind_host,
        bind_port,
        pid=getattr(proc, "pid", None),
        error=f"aggregator did not listen on {bind_host}:{bind_port} (see {log_path})",
    )

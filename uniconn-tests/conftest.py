"""Pytest fixtures for uniconn cross-language integration tests."""

import subprocess
import socket
import sys
import time
import os
import signal

import pytest

# Paths relative to this file.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GO_DIR = os.path.join(REPO_ROOT, "uniconn-go")
PY_DIR = os.path.join(REPO_ROOT, "uniconn-py")
JS_DIR = os.path.join(REPO_ROOT, "uniconn-js")

# Go echo server ports.
GO_TCP_PORT = 19001
GO_WS_PORT = 19002
GO_QUIC_PORT = 19003
GO_WT_PORT = 19004
GO_KCP_PORT = 19005

# Shared state for cert hash (set when Go server is spawned).
_go_cert_hash: str | None = None


def get_go_cert_hash() -> str | None:
    """Return Go echo server's TLS cert SHA-256 hash (hex)."""
    return _go_cert_hash


def _is_port_open(port: int) -> bool:
    """Check if a port is already listening."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except (ConnectionRefusedError, OSError):
        return False


@pytest.fixture(scope="session")
def go_echo_server():
    """Spawn Go echo server and wait for READY signal.

    If the server is already running (port 19001 open), reuse it.
    """
    global _go_cert_hash

    if _is_port_open(GO_TCP_PORT):
        # Server already running — reuse.
        yield None
        return

    # Use pre-built binary to avoid Windows firewall blocking
    # go run's temp binary for UDP (QUIC/WebTransport).
    exe = os.path.join(GO_DIR, "echoserver.exe")
    if not os.path.isfile(exe):
        # Fall back to go run if binary not found.
        cmd = ["go", "run", "./cmd/echoserver"]
    else:
        cmd = [exe]

    proc = subprocess.Popen(
        cmd,
        cwd=GO_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    # Wait for READY line, also capture CERT_HASH.
    deadline = time.time() + 60  # Go build can be slow on first run.
    ready = False
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("CERT_HASH:"):
            _go_cert_hash = line.split(":", 1)[1]
        if line == "READY":
            ready = True
            break

    if not ready:
        proc.kill()
        stderr = proc.stderr.read()
        raise RuntimeError(f"Go echo server did not become ready.\nstderr: {stderr}")

    yield proc

    # Teardown: kill Go server.
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

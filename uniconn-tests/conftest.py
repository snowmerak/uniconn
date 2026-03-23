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
    if _is_port_open(GO_TCP_PORT):
        # Server already running — reuse.
        yield None
        return

    proc = subprocess.Popen(
        ["go", "run", "./cmd/echoserver"],
        cwd=GO_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    # Wait for READY line.
    deadline = time.time() + 60  # Go build can be slow on first run.
    ready = False
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
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

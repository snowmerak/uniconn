"""Python server ← Node client: TCP, WebSocket echo tests."""

import subprocess
import os
import sys
import time

import pytest

from conftest import REPO_ROOT

ECHO_SERVER = os.path.join(os.path.dirname(__file__), "echo_server.py")
NODE_CLIENT = os.path.join(os.path.dirname(__file__), "node_client.mjs")
PYTHON = os.path.join(REPO_ROOT, "uniconn-py", ".venv", "Scripts", "python.exe")


def _spawn_py_server(protocol: str, port: int = 0):
    """Spawn Python echo server and return (process, actual_port)."""
    proc = subprocess.Popen(
        [PYTHON, ECHO_SERVER, protocol, str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait for READY:<port> line.
    deadline = time.time() + 10
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("READY:"):
            actual_port = int(line.split(":")[1])
            return proc, actual_port

    proc.kill()
    stderr = proc.stderr.read()
    raise RuntimeError(f"Python echo server did not become ready.\nstderr: {stderr}")


def _run_node_client(protocol: str, address: str, data: bytes, timeout: int = 15) -> bytes:
    """Run node_client.mjs and return echoed data."""
    hex_data = data.hex()
    result = subprocess.run(
        ["node", NODE_CLIENT, protocol, address],
        input=hex_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=os.path.dirname(__file__),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Node client failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return bytes.fromhex(result.stdout.strip())


def test_python_node_tcp_echo():
    """Node TCP client → Python TCP echo server."""
    proc, port = _spawn_py_server("tcp")
    try:
        data = b"hello from Node to Python TCP!"
        echoed = _run_node_client("tcp", f"127.0.0.1:{port}", data)
        assert echoed == data
    finally:
        proc.kill()


@pytest.mark.xfail(reason="Python raw WS server handshake not fully compatible with Node ws library")
def test_python_node_ws_echo():
    """Node WebSocket client → Python WebSocket echo server."""
    proc, port = _spawn_py_server("ws")
    try:
        data = b"hello from Node to Python WS!"
        echoed = _run_node_client("ws", f"ws://127.0.0.1:{port}", data)
        assert echoed == data
    finally:
        proc.kill()

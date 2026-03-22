"""Python server ← Go client: TCP, WebSocket echo tests."""

import subprocess
import os
import sys
import time

import pytest

from conftest import REPO_ROOT

ECHO_SERVER = os.path.join(os.path.dirname(__file__), "echo_server.py")
GO_CLIENT = os.path.join(os.path.dirname(__file__), "go_client.go")
GO_DIR = os.path.join(REPO_ROOT, "uniconn-go")
PYTHON = os.path.join(REPO_ROOT, "uniconn-py", ".venv", "Scripts", "python.exe")


def _spawn_py_server(protocol: str, port: int = 0):
    """Spawn Python echo server and return (process, actual_port)."""
    proc = subprocess.Popen(
        [PYTHON, ECHO_SERVER, protocol, str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line.startswith("READY:"):
            actual_port = int(line.split(":")[1])
            return proc, actual_port

    proc.kill()
    stderr = proc.stderr.read()
    raise RuntimeError(f"Python echo server did not become ready.\nstderr: {stderr}")


def _run_go_client(protocol: str, address: str, data: bytes, timeout: int = 15) -> bytes:
    """Run go_client.go and return echoed data."""
    hex_data = data.hex()
    result = subprocess.run(
        ["go", "run", GO_CLIENT, protocol, address],
        input=hex_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=GO_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Go client failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    return bytes.fromhex(result.stdout.strip())


# ── Python server ← Go client ───────────────────────

def test_python_go_tcp_echo():
    """Go TCP client → Python TCP echo server."""
    proc, port = _spawn_py_server("tcp")
    try:
        data = b"hello from Go to Python TCP!"
        echoed = _run_go_client("tcp", f"127.0.0.1:{port}", data)
        assert echoed == data
    finally:
        proc.kill()


def test_python_go_tcp_large():
    """Go TCP client → Python TCP echo server: 64KB."""
    proc, port = _spawn_py_server("tcp")
    try:
        data = bytes(range(256)) * 256  # 64KB
        echoed = _run_go_client("tcp", f"127.0.0.1:{port}", data, timeout=30)
        assert echoed == data
    finally:
        proc.kill()


def test_python_go_ws_echo():
    """Go WS client → Python WS echo server."""
    proc, port = _spawn_py_server("ws")
    try:
        data = b"hello from Go to Python WS!"
        echoed = _run_go_client("ws", f"ws://127.0.0.1:{port}", data)
        assert echoed == data
    finally:
        proc.kill()


def test_python_go_ws_large():
    """Go WS client → Python WS echo server: 64KB."""
    proc, port = _spawn_py_server("ws")
    try:
        data = bytes(range(256)) * 256  # 64KB
        echoed = _run_go_client("ws", f"ws://127.0.0.1:{port}", data, timeout=30)
        assert echoed == data
    finally:
        proc.kill()

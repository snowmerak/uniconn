"""Go server ← Node client: TCP, WebSocket echo tests.

Runs Node.js client scripts via subprocess and verifies echo results.
"""

import subprocess
import os

from conftest import GO_TCP_PORT, GO_WS_PORT, REPO_ROOT

NODE_CLIENT = os.path.join(os.path.dirname(__file__), "node_client.mjs")


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


def test_go_node_tcp_echo(go_echo_server):
    """Node TCP client → Go TCP echo server."""
    data = b"hello from Node TCP!"
    echoed = _run_node_client("tcp", f"127.0.0.1:{GO_TCP_PORT}", data)
    assert echoed == data


def test_go_node_tcp_large(go_echo_server):
    """Node TCP client → Go TCP echo server: 64KB payload."""
    data = bytes(range(256)) * 256  # 64KB
    echoed = _run_node_client("tcp", f"127.0.0.1:{GO_TCP_PORT}", data, timeout=30)
    assert echoed == data


def test_go_node_ws_echo(go_echo_server):
    """Node WebSocket client → Go WebSocket echo server."""
    data = b"hello from Node WebSocket!"
    echoed = _run_node_client("ws", f"ws://127.0.0.1:{GO_WS_PORT}/echo", data)
    assert echoed == data


def test_go_node_ws_large(go_echo_server):
    """Node WebSocket client → Go WebSocket echo server: 64KB."""
    data = bytes(range(256)) * 256  # 64KB
    echoed = _run_node_client("ws", f"ws://127.0.0.1:{GO_WS_PORT}/echo", data, timeout=30)
    assert echoed == data

"""Go secure crosstest server ← Python E2EE client: TCP and WebSocket tests.

Launches the Go secure/crosstest/server, exchanges fingerprints,
performs USCP v1 handshake, then E2EE encrypted echo round-trip.
"""

import asyncio
import json
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "uniconn-py"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GO_DIR = os.path.join(REPO_ROOT, "uniconn-go")

from uniconn.tcp.dialer import TcpDialer
from uniconn.websocket.dialer import WsDialer
from uniconn.secure.identity import Identity
from uniconn.secure.handshake import handshake_initiator


def _spawn_secure_server():
    """Spawn Go secure crosstest echo server.

    Returns (proc, tcp_port, ws_port, server_fp, py_identity).
    """
    py_identity = Identity.generate()
    py_fp = py_identity.fingerprint()

    proc = subprocess.Popen(
        ["go", "run", "./secure/crosstest/server"],
        cwd=GO_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )

    deadline = time.time() + 60
    info = None
    while time.time() < deadline:
        line = proc.stdout.readline().strip()
        if line:
            try:
                info = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if info is None:
        proc.kill()
        stderr = proc.stderr.read()
        raise RuntimeError(f"Go secure server did not produce info.\nstderr: {stderr}")

    tcp_port = info["port"]
    ws_port = info["wsPort"]
    server_fp = bytes.fromhex(info["fingerprint"])

    proc.stdin.write(py_fp.hex() + "\n")
    proc.stdin.flush()

    # Give Go server time to set up
    time.sleep(0.2)

    return proc, tcp_port, ws_port, server_fp, py_identity


def _kill_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


@pytest.mark.asyncio
async def test_e2ee_tcp_echo():
    """Python E2EE TCP client → Go secure crosstest server."""
    proc, tcp_port, ws_port, server_fp, py_identity = _spawn_secure_server()
    try:
        dialer = TcpDialer()
        conn = await dialer.dial(f"127.0.0.1:{tcp_port}")

        secure_conn = await handshake_initiator(conn, py_identity, server_fp)
        secure_conn.bind(conn)

        data = b"hello, E2EE over TCP!"
        await secure_conn.write(data)

        buf = bytearray(1024)
        n = await secure_conn.read(buf)
        assert buf[:n] == data

        await secure_conn.close()
    finally:
        _kill_server(proc)


@pytest.mark.asyncio
async def test_e2ee_ws_echo():
    """Python E2EE WebSocket client → Go secure crosstest server."""
    proc, tcp_port, ws_port, server_fp, py_identity = _spawn_secure_server()
    try:
        dialer = WsDialer()
        # Go's x/net/websocket requires Origin header.
        import websockets
        ws = await websockets.connect(
            f"ws://127.0.0.1:{ws_port}/ws",
            additional_headers={"Origin": f"http://127.0.0.1:{ws_port}"},
        )
        from uniconn.websocket.conn import WsConn
        conn = WsConn(ws)

        # WS protocol: send our fingerprint, receive server's fingerprint.
        py_fp = py_identity.fingerprint()
        await conn.write(py_fp)

        fp_buf = bytearray(64)
        n = await conn.read(fp_buf)

        secure_conn = await handshake_initiator(conn, py_identity, server_fp)
        secure_conn.bind(conn)

        data = b"hello, E2EE over WebSocket!"
        await secure_conn.write(data)

        buf = bytearray(1024)
        n = await secure_conn.read(buf)
        assert buf[:n] == data

        await secure_conn.close()
    finally:
        _kill_server(proc)

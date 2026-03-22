"""Go server ← Python client: TCP, WebSocket, KCP echo tests."""

import sys
import os

# Add uniconn-py to path so we can import uniconn.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "uniconn-py"))

from conftest import GO_TCP_PORT, GO_WS_PORT, GO_KCP_PORT

from uniconn.tcp.dialer import TcpDialer
from uniconn.websocket.dialer import WsDialer


def test_go_tcp_echo(go_echo_server):
    """Python TCP client → Go TCP echo server."""
    dialer = TcpDialer()
    conn = dialer.dial(f"127.0.0.1:{GO_TCP_PORT}")

    data = b"hello from Python TCP!"
    conn.write(data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == data

    conn.close()


def test_go_tcp_large(go_echo_server):
    """Python TCP client → Go TCP echo server: 64KB payload."""
    dialer = TcpDialer()
    conn = dialer.dial(f"127.0.0.1:{GO_TCP_PORT}")

    data = bytes(range(256)) * 256  # 64KB
    conn.write(data)

    received = bytearray()
    buf = bytearray(4096)
    while len(received) < len(data):
        n = conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    conn.close()


def test_go_ws_echo(go_echo_server):
    """Python WebSocket client → Go WebSocket echo server."""
    dialer = WsDialer()
    conn = dialer.dial(f"ws://127.0.0.1:{GO_WS_PORT}/echo")

    data = b"hello from Python WebSocket!"
    conn.write(data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == data

    conn.close()


def test_go_ws_large(go_echo_server):
    """Python WebSocket client → Go WebSocket echo server: 64KB."""
    dialer = WsDialer()
    conn = dialer.dial(f"ws://127.0.0.1:{GO_WS_PORT}/echo")

    data = bytes(range(256)) * 256  # 64KB
    conn.write(data)

    received = bytearray()
    buf = bytearray(4096)
    while len(received) < len(data):
        n = conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    conn.close()


def test_go_kcp_echo(go_echo_server):
    """Python KCP client → Go KCP echo server."""
    from uniconn.kcp import KcpDialer

    dialer = KcpDialer(conv_id=1)
    conn = dialer.dial(f"127.0.0.1:{GO_KCP_PORT}")

    import time
    time.sleep(0.2)  # Let KCP settle.

    data = b"hello from Python KCP!"
    conn.write(data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == data

    conn.close()

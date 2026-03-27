"""Go server ← Python client: TCP, WebSocket, KCP echo tests (async)."""

import asyncio
import sys
import os

import pytest

# Add uniconn-py to path so we can import uniconn.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "uniconn-py"))

from conftest import GO_TCP_PORT, GO_WS_PORT, GO_KCP_PORT, GO_QUIC_PORT, GO_WT_PORT

from uniconn.tcp.dialer import TcpDialer
from uniconn.websocket.dialer import WsDialer
from uniconn.quic import QuicDialer
from uniconn.webtransport import WebTransportDialer


@pytest.mark.asyncio
async def test_go_tcp_echo(go_echo_server):
    """Python TCP client → Go TCP echo server."""
    dialer = TcpDialer()
    conn = await dialer.dial(f"127.0.0.1:{GO_TCP_PORT}")

    data = b"hello from Python TCP!"
    await conn.write(data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == data

    await conn.close()


@pytest.mark.asyncio
async def test_go_tcp_large(go_echo_server):
    """Python TCP client → Go TCP echo server: 64KB payload."""
    dialer = TcpDialer()
    conn = await dialer.dial(f"127.0.0.1:{GO_TCP_PORT}")

    data = bytes(range(256)) * 256  # 64KB
    await conn.write(data)

    received = bytearray()
    buf = bytearray(4096)
    while len(received) < len(data):
        n = await conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    await conn.close()


@pytest.mark.asyncio
async def test_go_ws_echo(go_echo_server):
    """Python WebSocket client → Go WebSocket echo server."""
    dialer = WsDialer()
    conn = await dialer.dial(f"ws://127.0.0.1:{GO_WS_PORT}/echo")

    data = b"hello from Python WebSocket!"
    await conn.write(data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == data

    await conn.close()


@pytest.mark.asyncio
async def test_go_ws_large(go_echo_server):
    """Python WebSocket client → Go WebSocket echo server: 64KB."""
    dialer = WsDialer()
    conn = await dialer.dial(f"ws://127.0.0.1:{GO_WS_PORT}/echo")

    data = bytes(range(256)) * 256  # 64KB
    await conn.write(data)

    received = bytearray()
    buf = bytearray(256 * 1024)
    while len(received) < len(data):
        n = await conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    await conn.close()


@pytest.mark.asyncio
async def test_go_kcp_echo(go_echo_server):
    """Python KCP client → Go KCP echo server."""
    from uniconn.kcp import KcpDialer

    dialer = KcpDialer(conv_id=1)
    conn = await dialer.dial(f"127.0.0.1:{GO_KCP_PORT}")

    await asyncio.sleep(0.2)  # Let KCP settle.

    data = b"hello from Python KCP!"
    await conn.write(data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == data

    await conn.close()


@pytest.mark.asyncio
async def test_go_quic_echo(go_echo_server):
    """Python QUIC client → Go QUIC echo server."""
    dialer = QuicDialer(verify_mode=False)
    conn = await dialer.dial(f"127.0.0.1:{GO_QUIC_PORT}")

    data = b"hello from Python QUIC!"
    await conn.write(data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == data

    await conn.close()


@pytest.mark.asyncio
async def test_go_quic_large(go_echo_server):
    """Python QUIC client → Go QUIC echo server: 64KB payload."""
    dialer = QuicDialer(verify_mode=False)
    conn = await dialer.dial(f"127.0.0.1:{GO_QUIC_PORT}")

    data = bytes(range(256)) * 256  # 64KB
    await conn.write(data)

    received = bytearray()
    buf = bytearray(256 * 1024)
    while len(received) < len(data):
        n = await conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    await conn.close()


@pytest.mark.asyncio
async def test_go_wt_echo(go_echo_server):
    """Python WebTransport client → Go WebTransport echo server."""
    dialer = WebTransportDialer(verify_ssl=False)
    conn = await dialer.dial(f"https://127.0.0.1:{GO_WT_PORT}/")

    data = b"hello from Python WebTransport!"
    await conn.write(data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == data
    await conn.close()


@pytest.mark.asyncio
async def test_go_wt_large(go_echo_server):
    """Python WebTransport client → Go WebTransport echo server: 64KB payload."""
    dialer = WebTransportDialer(verify_ssl=False)
    conn = await dialer.dial(f"https://127.0.0.1:{GO_WT_PORT}/")

    data = bytes(range(256)) * 256  # 64KB
    await conn.write(data)

    received = bytearray()
    buf = bytearray(256 * 1024)
    while len(received) < len(data):
        n = await conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data
    await conn.close()


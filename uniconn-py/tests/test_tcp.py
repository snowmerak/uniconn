"""Unit tests for uniconn TCP adapter (async)."""

import asyncio
import pytest

from uniconn.tcp.listener import TcpListener
from uniconn.tcp.dialer import TcpDialer


@pytest.mark.asyncio
async def test_tcp_echo():
    """TCP: dialer sends data, listener echoes back."""
    listener = await TcpListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    async def server():
        conn = await listener.accept()
        buf = bytearray(1024)
        n = await conn.read(buf)
        await conn.write(bytes(buf[:n]))
        await conn.close()

    task = asyncio.create_task(server())

    dialer = TcpDialer()
    conn = await dialer.dial(f"127.0.0.1:{port}")

    test_data = b"hello, uniconn Python TCP!"
    await conn.write(test_data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == test_data

    await conn.close()
    await task
    await listener.close()


@pytest.mark.asyncio
async def test_tcp_large_payload():
    """TCP: 64KB payload echo."""
    listener = await TcpListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    data = bytes(range(256)) * 256  # 64KB

    async def server():
        conn = await listener.accept()
        received = bytearray()
        buf = bytearray(4096)
        while len(received) < len(data):
            n = await conn.read(buf)
            if n == 0:
                break
            received.extend(buf[:n])
        await conn.write(bytes(received))
        await conn.close()

    task = asyncio.create_task(server())

    dialer = TcpDialer()
    conn = await dialer.dial(f"127.0.0.1:{port}")
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
    await task
    await listener.close()

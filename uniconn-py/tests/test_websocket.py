"""Unit tests for uniconn WebSocket adapter (async)."""

import asyncio
import pytest

from uniconn.websocket.listener import WsListener
from uniconn.websocket.dialer import WsDialer


@pytest.mark.asyncio
async def test_ws_echo():
    """WebSocket: dialer sends data, listener echoes back."""
    listener = await WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    async def server():
        conn = await listener.accept()
        buf = bytearray(1024)
        n = await conn.read(buf)
        await conn.write(bytes(buf[:n]))

    task = asyncio.create_task(server())

    dialer = WsDialer()
    conn = await dialer.dial(f"ws://127.0.0.1:{port}")

    test_data = b"hello, uniconn Python WebSocket!"
    await conn.write(test_data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == test_data

    await conn.close()
    await task
    await listener.close()


@pytest.mark.asyncio
async def test_ws_large_payload():
    """WebSocket: 64KB payload echo."""
    listener = await WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    data = bytes(range(256)) * 256  # 64KB

    async def server():
        conn = await listener.accept()
        buf = bytearray(256 * 1024)
        received = bytearray()
        while len(received) < len(data):
            n = await conn.read(buf)
            if n == 0:
                break
            received.extend(buf[:n])
        await conn.write(bytes(received))

    task = asyncio.create_task(server())

    dialer = WsDialer()
    conn = await dialer.dial(f"ws://127.0.0.1:{port}")
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
    await task
    await listener.close()


@pytest.mark.asyncio
async def test_ws_multiple_messages():
    """WebSocket: multiple messages in sequence."""
    listener = await WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    messages = [b"msg1", b"message two", b"third message!!!"]

    async def server():
        conn = await listener.accept()
        for _ in messages:
            buf = bytearray(256)
            n = await conn.read(buf)
            await conn.write(bytes(buf[:n]))

    task = asyncio.create_task(server())

    dialer = WsDialer()
    conn = await dialer.dial(f"ws://127.0.0.1:{port}")

    for msg in messages:
        await conn.write(msg)
        buf = bytearray(256)
        n = await conn.read(buf)
        assert buf[:n] == msg

    await conn.close()
    await task
    await listener.close()

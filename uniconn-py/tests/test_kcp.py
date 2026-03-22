"""Unit tests for uniconn KCP adapter."""

import asyncio
import pytest

from uniconn.kcp import KcpListener, KcpDialer


@pytest.mark.asyncio
async def test_kcp_echo():
    """KCP: dialer sends data, listener echoes back."""
    listener = await KcpListener.bind("127.0.0.1", 19100, conv_id=1)

    async def server():
        conn = await asyncio.wait_for(listener.accept(), timeout=5.0)
        buf = bytearray(1024)
        n = await asyncio.wait_for(conn.read(buf), timeout=5.0)
        await conn.write(bytes(buf[:n]))
        # Small delay to ensure flush.
        await asyncio.sleep(0.1)

    server_task = asyncio.create_task(server())

    dialer = KcpDialer(conv_id=1)
    conn = await dialer.dial("127.0.0.1:19100")

    test_data = b"hello, uniconn Python KCP!"
    await conn.write(test_data)

    buf = bytearray(1024)
    n = await asyncio.wait_for(conn.read(buf), timeout=5.0)
    assert buf[:n] == test_data

    await conn.close()
    await server_task
    await listener.close()

"""Unit tests for uniconn KCP adapter (async)."""

import asyncio
import pytest

from uniconn.kcp import KcpListener, KcpDialer


@pytest.mark.asyncio
async def test_kcp_echo():
    """KCP: dialer sends data, listener echoes back."""
    listener = await KcpListener.bind("127.0.0.1", 19200, conv_id=1)

    async def server():
        conn = await listener.accept()
        buf = bytearray(1024)
        n = await conn.read(buf)
        await conn.write(bytes(buf[:n]))

    task = asyncio.create_task(server())

    dialer = KcpDialer(conv_id=1)
    conn = await dialer.dial("127.0.0.1:19200")

    await asyncio.sleep(0.1)  # Let KCP handshake settle.

    test_data = b"hello, uniconn Python KCP!"
    await conn.write(test_data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == test_data

    await conn.close()
    await task
    await listener.close()

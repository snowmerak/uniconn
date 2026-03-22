"""KCP transport adapter for uniconn (asyncio).

Uses the ``kcp`` PyPI package (kcp-py) which provides Python bindings
for the KCP reliable UDP protocol.

- KcpListener: uses KCPServerAsync directly (no thread wrapper)
- KcpDialer: uses KCPClientSync in asyncio.to_thread (sync-only API)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from ..conn import Addr, Conn, Listener, Dialer
from ..errors import ConnectionClosedError


class KcpConn(Conn):
    """KCP connection backed by kcp-py."""

    def __init__(
        self,
        kcp_conn: Any,
        send_fn: Any = None,
        local_address: str | None = None,
        remote_address: str | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._conn = kcp_conn
        self._send_fn = send_fn
        self._local_addr = local_address
        self._remote_addr = remote_address
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_buf = bytearray()
        self._closed = False
        self._loop = loop or asyncio.get_event_loop()

    def _on_data(self, data: bytes) -> None:
        """Called when data arrives."""
        if not self._closed:
            self._recv_queue.put_nowait(data)

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        if self._recv_buf:
            n = min(len(buf), len(self._recv_buf))
            buf[:n] = self._recv_buf[:n]
            self._recv_buf = self._recv_buf[n:]
            return n

        try:
            data = await asyncio.wait_for(self._recv_queue.get(), timeout=10.0)
        except asyncio.TimeoutError:
            return 0

        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        if n < len(data):
            self._recv_buf.extend(data[n:])
        return n

    async def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        if self._send_fn:
            self._send_fn(data)
        else:
            self._conn.enqueue(data)
        return len(data)

    async def close(self) -> None:
        self._closed = True

    def local_addr(self) -> Addr | None:
        if self._local_addr:
            return Addr(network="kcp", address=self._local_addr)
        return None

    def remote_addr(self) -> Addr | None:
        if self._remote_addr:
            return Addr(network="kcp", address=self._remote_addr)
        return None


class KcpListener(Listener):
    """KCP listener using KCPServerAsync directly."""

    def __init__(self, addr: Addr) -> None:
        self._addr = addr
        self._conn_queue: asyncio.Queue[KcpConn] = asyncio.Queue()
        self._connections: dict[tuple, KcpConn] = {}
        self._server: Any = None
        self._closed = False

    @classmethod
    async def bind(
        cls, host: str = "0.0.0.0", port: int = 0, conv_id: int = 1
    ) -> "KcpListener":
        """Create and start a KCP listener."""
        from kcp import KCPServerAsync

        listener = cls(Addr(network="kcp", address=f"{host}:{port}"))
        loop = asyncio.get_running_loop()
        listener._loop = loop

        server = KCPServerAsync(host, port, conv_id=conv_id)

        @server.on_data
        async def handle_data(connection: Any, data: bytes) -> None:
            addr_tuple = connection.address_tuple
            if addr_tuple not in listener._connections:
                kcp_conn = KcpConn(
                    connection,
                    local_address=f"{host}:{port}",
                    remote_address=f"{addr_tuple[0]}:{addr_tuple[1]}",
                    loop=loop,
                )
                listener._connections[addr_tuple] = kcp_conn
                listener._conn_queue.put_nowait(kcp_conn)
            listener._connections[addr_tuple]._on_data(data)

        listener._server = server

        # listen() is a coroutine — run as a background task in current loop.
        asyncio.create_task(server.listen())
        await asyncio.sleep(0.15)  # Let server bind.

        return listener

    async def accept(self) -> Conn:
        return await self._conn_queue.get()

    async def close(self) -> None:
        self._closed = True

    def addr(self) -> Addr:
        return self._addr


class KcpDialer(Dialer):
    """KCP dialer using KCPClientSync via asyncio.to_thread."""

    def __init__(self, conv_id: int = 1) -> None:
        self._conv_id = conv_id

    async def dial(self, address: str) -> Conn:
        from kcp import KCPClientSync

        host, port_str = address.rsplit(":", 1)
        port = int(port_str)

        kcp_conn = KcpConn(None, remote_address=address)

        client = KCPClientSync(
            host, port,
            conv_id=self._conv_id,
            no_delay=True,
            update_interval=10,
            resend_count=2,
            no_congestion_control=True,
            receive_window_size=128,
            send_window_size=128,
        )

        @client.on_data
        def on_data(data: bytes) -> None:
            kcp_conn._on_data(data)

        kcp_conn._send_fn = client.send

        # KCPClientSync.start() is blocking, run in thread.
        thread = threading.Thread(target=client.start, daemon=True)
        thread.start()
        await asyncio.sleep(0.05)  # Let client connect.

        return kcp_conn

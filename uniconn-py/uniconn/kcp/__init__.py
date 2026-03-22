"""KCP transport adapter for uniconn.

Uses the `kcp` PyPI package (kcp-py) which provides Python bindings
for the KCP reliable UDP protocol with asyncio support.

Note: kcp-py's API is callback/event-based. This adapter wraps it
into uniconn's async read/write Conn interface using asyncio.Queue.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..conn import Addr, Conn, Listener, Dialer
from ..errors import ConnectionClosedError


class KcpConn(Conn):
    """KCP connection wrapping a kcp-py Connection object."""

    def __init__(
        self,
        kcp_conn: Any,
        local_address: str | None = None,
        remote_address: str | None = None,
    ) -> None:
        self._conn = kcp_conn
        self._local_addr = local_address
        self._remote_addr = remote_address
        self._recv_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_buf = bytearray()
        self._closed = False

    def _on_data(self, data: bytes) -> None:
        """Called when data arrives on this KCP connection."""
        if not self._closed:
            self._recv_queue.put_nowait(data)

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        # Return buffered data first.
        if self._recv_buf:
            n = min(len(buf), len(self._recv_buf))
            buf[:n] = self._recv_buf[:n]
            self._recv_buf = self._recv_buf[n:]
            return n

        # Wait for next data.
        try:
            data = await self._recv_queue.get()
        except asyncio.CancelledError:
            return 0

        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        if n < len(data):
            self._recv_buf.extend(data[n:])
        return n

    async def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
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
    """
    KCP listener wrapping kcp-py KCPServerAsync.

    Uses the internal listen() coroutine integrated into the
    current asyncio event loop.
    """

    def __init__(self, server: Any, addr: Addr, listen_task: asyncio.Task) -> None:
        self._server = server
        self._addr = addr
        self._listen_task = listen_task
        self._conn_queue: asyncio.Queue[KcpConn] = asyncio.Queue()
        self._connections: dict[tuple, KcpConn] = {}
        self._closed = False

    @classmethod
    async def bind(
        cls,
        host: str = "0.0.0.0",
        port: int = 0,
        conv_id: int = 1,
    ) -> "KcpListener":
        """Create and start a KCP listener on the given host:port."""
        from kcp import KCPServerAsync

        conn_queue: asyncio.Queue[KcpConn] = asyncio.Queue()
        connections: dict[tuple, KcpConn] = {}

        server = KCPServerAsync(host, port, conv_id=conv_id)

        # Inject our event loop (kcp-py creates its own by default).
        server._loop = asyncio.get_running_loop()

        @server.on_data
        def handle_data(connection: Any, data: bytes) -> None:
            addr_tuple = connection.address_tuple
            if addr_tuple not in connections:
                kcp_conn = KcpConn(
                    connection,
                    local_address=f"{host}:{port}",
                    remote_address=f"{addr_tuple[0]}:{addr_tuple[1]}",
                )
                connections[addr_tuple] = kcp_conn
                conn_queue.put_nowait(kcp_conn)
            connections[addr_tuple]._on_data(data)

        # Start the server's listen coroutine in the current event loop.
        listen_task = asyncio.create_task(server.listen())

        # Small delay for UDP endpoint to be ready.
        await asyncio.sleep(0.05)

        actual_addr = Addr(network="kcp", address=f"{host}:{port}")
        listener = cls(server, actual_addr, listen_task)
        listener._conn_queue = conn_queue
        listener._connections = connections
        return listener

    async def accept(self) -> Conn:
        return await self._conn_queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

    def addr(self) -> Addr:
        return self._addr


class KcpDialer(Dialer):
    """
    KCP dialer.

    Note: kcp-py's KCPClientSync is blocking and not easily integrated
    with asyncio. For cross-language integration tests, use the Go echo
    server with a raw UDP + KCP approach.

    This is a placeholder that will be refined when a better async KCP
    client API is available.
    """

    async def dial(self, address: str) -> Conn:
        """
        Dial a KCP connection.

        Args:
            address: "host:port" format, e.g. "127.0.0.1:19005"
        """
        raise NotImplementedError(
            "KcpDialer is not yet implemented. "
            "kcp-py's KCPClientSync is blocking. "
            "For cross-platform tests, use Go/Node.js as client."
        )

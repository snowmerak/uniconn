"""KCP transport adapter for uniconn.

Uses the `kcp` PyPI package (kcp-py) which provides Python bindings
for the KCP reliable UDP protocol with asyncio support.

Architecture:
- KcpListener: wraps kcp-py's KCPServerAsync (asyncio-native server)
- KcpDialer: custom async KCP client using asyncio.DatagramProtocol
  + KCP C bindings with outbound_handler callback for sending data
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..conn import Addr, Conn, Listener, Dialer
from ..errors import ConnectionClosedError


class KcpConn(Conn):
    """KCP connection wrapping a kcp-py Connection (server side)
    or a raw KCP object (client side)."""

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
        self._update_task: asyncio.Task | None = None

    def _on_data(self, data: bytes) -> None:
        """Called when decoded data arrives."""
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
        # enqueue works on both kcp-py Connection and raw KCP objects.
        self._conn.enqueue(data)
        return len(data)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._update_task:
                self._update_task.cancel()
                try:
                    await self._update_task
                except asyncio.CancelledError:
                    pass

    def local_addr(self) -> Addr | None:
        if self._local_addr:
            return Addr(network="kcp", address=self._local_addr)
        return None

    def remote_addr(self) -> Addr | None:
        if self._remote_addr:
            return Addr(network="kcp", address=self._remote_addr)
        return None


class KcpListener(Listener):
    """KCP listener wrapping kcp-py KCPServerAsync."""

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
        """Create and start a KCP listener."""
        from kcp import KCPServerAsync

        conn_queue: asyncio.Queue[KcpConn] = asyncio.Queue()
        connections: dict[tuple, KcpConn] = {}

        server = KCPServerAsync(host, port, conv_id=conv_id)
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

        listen_task = asyncio.create_task(server.listen())
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


class _KcpClientProtocol(asyncio.DatagramProtocol):
    """Async UDP protocol for KCP client."""

    def __init__(self, kcp_obj: Any, kcp_conn: KcpConn) -> None:
        self._kcp = kcp_obj
        self._kcp_conn = kcp_conn
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        # Feed raw UDP data into KCP for decoding.
        self._kcp.receive(data)
        decoded = self._kcp.get_all_received()
        if decoded:
            for chunk in decoded:
                self._kcp_conn._on_data(chunk)

    def error_received(self, exc: Exception) -> None:
        pass

    def connection_lost(self, exc: Exception | None) -> None:
        pass


class KcpDialer(Dialer):
    """
    Async KCP dialer using asyncio.DatagramProtocol + KCP C bindings.

    Uses KCP's outbound_handler callback to send encoded data
    through the asyncio UDP transport.
    """

    def __init__(self, conv_id: int = 1) -> None:
        self._conv_id = conv_id

    async def dial(self, address: str) -> Conn:
        """
        Dial a KCP connection.

        Args:
            address: "host:port" format, e.g. "127.0.0.1:19005"
        """
        from kcp import KCP

        host, port_str = address.rsplit(":", 1)
        port = int(port_str)
        remote_tuple = (host, port)

        kcp_obj = KCP(self._conv_id)
        kcp_conn = KcpConn(
            kcp_obj,
            remote_address=address,
        )

        loop = asyncio.get_running_loop()
        protocol = _KcpClientProtocol(kcp_obj, kcp_conn)

        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol,
            remote_addr=remote_tuple,
        )

        # Register outbound_handler — KCP calls this when update()
        # produces output data to be sent over UDP.
        @kcp_obj.outbound_handler
        def on_output(data: bytes) -> None:
            if transport and not transport.is_closing():
                transport.sendto(data, remote_tuple)

        # Periodic update task to flush KCP state.
        async def update_loop() -> None:
            try:
                while not kcp_conn._closed:
                    ts = int(time.monotonic() * 1000) & 0xFFFFFFFF
                    kcp_obj.update(ts)
                    await asyncio.sleep(0.01)  # 10ms interval
            except asyncio.CancelledError:
                pass

        kcp_conn._update_task = asyncio.create_task(update_loop())

        return kcp_conn

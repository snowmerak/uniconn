"""TCP listener using asyncio."""

from __future__ import annotations

import asyncio

from ..conn import Addr, Conn, Listener
from .conn import TcpConn


class TcpListener(Listener):
    """TCP listener backed by asyncio.Server."""

    def __init__(self, server: asyncio.Server, addr: Addr) -> None:
        self._server = server
        self._addr = addr
        self._conn_queue: asyncio.Queue[TcpConn] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "TcpListener":
        """Create and start a TCP listener."""
        listener = cls.__new__(cls)
        listener._conn_queue = asyncio.Queue()
        listener._closed = False

        async def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            conn = TcpConn(reader, writer)
            await listener._conn_queue.put(conn)

        server = await asyncio.start_server(on_connect, host, port)
        sock = server.sockets[0]
        bound = sock.getsockname()
        listener._server = server
        listener._addr = Addr(network="tcp", address=f"{bound[0]}:{bound[1]}")
        return listener

    async def accept(self) -> Conn:
        return await self._conn_queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._server.close()
            await self._server.wait_closed()

    def addr(self) -> Addr:
        return self._addr

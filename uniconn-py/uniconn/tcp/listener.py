"""TCP listener."""

from __future__ import annotations

import asyncio

from ..conn import Addr, Conn, Listener
from .conn import TcpConn


class TcpListener(Listener):
    """TCP listener backed by asyncio.start_server."""

    def __init__(self, server: asyncio.Server, addr: Addr) -> None:
        self._server = server
        self._addr = addr
        self._queue: asyncio.Queue[TcpConn] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "TcpListener":
        """Create and start a TCP listener."""
        queue: asyncio.Queue[TcpConn] = asyncio.Queue()

        async def on_connection(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            conn = TcpConn(reader, writer)
            await queue.put(conn)

        server = await asyncio.start_server(on_connection, host, port)
        sockname = server.sockets[0].getsockname()
        addr = Addr(network="tcp", address=f"{sockname[0]}:{sockname[1]}")
        listener = cls(server, addr)
        listener._queue = queue
        return listener

    async def accept(self) -> Conn:
        return await self._queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._server.close()
            await self._server.wait_closed()

    def addr(self) -> Addr:
        return self._addr

"""WebSocket listener using the ``websockets`` library."""

from __future__ import annotations

import asyncio

import websockets
import websockets.asyncio.server

from ..conn import Addr, Conn, Listener
from .conn import WsConn


class WsListener(Listener):
    """WebSocket listener backed by ``websockets.serve``."""

    def __init__(self, server: websockets.asyncio.server.Server, addr: Addr) -> None:
        self._server = server
        self._addr = addr
        self._conn_queue: asyncio.Queue[WsConn] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "WsListener":
        """Create and start a WebSocket listener."""
        listener = cls.__new__(cls)
        listener._conn_queue = asyncio.Queue()
        listener._closed = False

        async def handler(ws: websockets.asyncio.server.ServerConnection):
            local = Addr(network="websocket", address=f"{host}:{port}")
            try:
                remote_info = ws.remote_address
                remote = Addr(network="websocket", address=f"{remote_info[0]}:{remote_info[1]}")
            except Exception:
                remote = None
            conn = WsConn(ws, local=local, remote=remote)
            await listener._conn_queue.put(conn)
            # Keep the handler alive until the connection closes.
            await ws.wait_closed()

        server = await websockets.asyncio.server.serve(
            handler, host, port,
        )
        # Resolve actual bound port.
        sock = list(server.sockets)[0]
        bound = sock.getsockname()
        listener._server = server
        listener._addr = Addr(network="websocket", address=f"{bound[0]}:{bound[1]}")
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

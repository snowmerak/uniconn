"""WebSocket listener."""

from __future__ import annotations

import asyncio
from typing import Any

import websockets
import websockets.server

from ..conn import Addr, Conn, Listener
from .conn import WsConn


class WsListener(Listener):
    """WebSocket listener using websockets.serve."""

    def __init__(self, server: Any, addr: Addr) -> None:
        self._server = server
        self._addr = addr
        self._queue: asyncio.Queue[WsConn] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "WsListener":
        """Create and start a WebSocket listener."""
        queue: asyncio.Queue[WsConn] = asyncio.Queue()

        async def handler(ws: Any) -> None:
            conn = WsConn(ws)
            await queue.put(conn)
            # Keep handler alive until the ws closes.
            try:
                await ws.wait_closed()
            except Exception:
                pass

        server = await websockets.serve(handler, host, port)
        sockname = list(server.sockets)[0].getsockname()
        addr = Addr(network="websocket", address=f"{sockname[0]}:{sockname[1]}")
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

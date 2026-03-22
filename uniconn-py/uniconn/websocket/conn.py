"""WebSocket connection wrapping the websockets library."""

from __future__ import annotations

import asyncio
from typing import Any

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class WsConn(Conn):
    """
    WebSocket connection.

    Converts between message-oriented WebSocket and stream-oriented Conn
    by buffering partial reads.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._read_buf = bytearray()
        self._closed = False

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        # Return buffered data first.
        if self._read_buf:
            n = min(len(buf), len(self._read_buf))
            buf[:n] = self._read_buf[:n]
            self._read_buf = self._read_buf[n:]
            return n

        try:
            msg = await self._ws.recv()
        except Exception:
            return 0

        if isinstance(msg, str):
            data = msg.encode("utf-8")
        else:
            data = bytes(msg)

        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        if n < len(data):
            self._read_buf.extend(data[n:])
        return n

    async def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        await self._ws.send(data)
        return len(data)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                await self._ws.close()
            except Exception:
                pass

    def local_addr(self) -> Addr | None:
        return None

    def remote_addr(self) -> Addr | None:
        try:
            remote = self._ws.remote_address
            if remote:
                return Addr(network="websocket", address=f"{remote[0]}:{remote[1]}")
        except Exception:
            pass
        return None

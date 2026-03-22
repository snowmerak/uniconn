"""WebSocket connection using the ``websockets`` library."""

from __future__ import annotations

from typing import Any

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class WsConn(Conn):
    """
    WebSocket connection (async).

    Wraps a ``websockets`` connection object (client or server side).
    Converts between message‐oriented WebSocket and stream‐oriented Conn
    by buffering partial reads.
    """

    def __init__(self, ws: Any, local: Addr | None = None, remote: Addr | None = None) -> None:
        self._ws = ws
        self._read_buf = bytearray()
        self._closed = False
        self._local = local
        self._remote = remote

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        # Return buffered leftovers first.
        if self._read_buf:
            n = min(len(buf), len(self._read_buf))
            buf[:n] = self._read_buf[:n]
            self._read_buf = self._read_buf[n:]
            return n

        try:
            data = await self._ws.recv()
        except Exception:
            return 0

        if isinstance(data, str):
            data = data.encode()

        if not data:
            return 0

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
        return self._local

    def remote_addr(self) -> Addr | None:
        return self._remote

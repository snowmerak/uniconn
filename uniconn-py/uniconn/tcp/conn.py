"""TCP connection wrapping asyncio streams."""

from __future__ import annotations

import asyncio

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class TcpConn(Conn):
    """TCP connection backed by asyncio StreamReader/StreamWriter."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._closed = False

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()
        data = await self._reader.read(len(buf))
        if not data:
            return 0
        n = len(data)
        buf[:n] = data
        return n

    async def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        self._writer.write(data)
        await self._writer.drain()
        return len(data)

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    def local_addr(self) -> Addr | None:
        try:
            addr = self._writer.get_extra_info("sockname")
            if addr:
                return Addr(network="tcp", address=f"{addr[0]}:{addr[1]}")
        except Exception:
            pass
        return None

    def remote_addr(self) -> Addr | None:
        try:
            addr = self._writer.get_extra_info("peername")
            if addr:
                return Addr(network="tcp", address=f"{addr[0]}:{addr[1]}")
        except Exception:
            pass
        return None

"""QUIC connection using aioquic (asyncio StreamReader/StreamWriter)."""

from __future__ import annotations

import asyncio
from typing import Any

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class QuicConn(Conn):
    """QUIC connection backed by aioquic stream (StreamReader/StreamWriter).

    Follows the uniconn pattern: one QUIC session = one bidirectional stream.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        protocol: Any = None,
        local_address: str | None = None,
        remote_address: str | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._protocol = protocol  # QuicConnectionProtocol, kept for close
        self._local_addr = local_address
        self._remote_addr = remote_address
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
            if self._protocol is not None:
                self._protocol.close()

    def local_addr(self) -> Addr | None:
        if self._local_addr:
            return Addr(network="quic", address=self._local_addr)
        return None

    def remote_addr(self) -> Addr | None:
        if self._remote_addr:
            return Addr(network="quic", address=self._remote_addr)
        return None

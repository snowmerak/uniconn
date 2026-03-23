"""WebTransport connection wrapping an aioquic QUIC+H3 session."""

from __future__ import annotations

import asyncio
from typing import Optional

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class WebTransportConn(Conn):
    """WebTransport connection over a single bidi stream.

    Uses low-level QUIC stream I/O (not H3 DATA frames) for the WT stream.
    """

    def __init__(
        self,
        protocol,  # QuicConnectionProtocol
        h3_conn,   # H3Connection
        stream_id: int,
        session_id: int,
        remote_addr: tuple[str, int] | None = None,
    ) -> None:
        self._protocol = protocol
        self._h3 = h3_conn
        self._stream_id = stream_id
        self._session_id = session_id
        self._remote_addr = remote_addr
        self._closed = False
        self._buf = bytearray()
        self._data_event = asyncio.Event()
        self._eof = False

    def feed_data(self, data: bytes, stream_ended: bool) -> None:
        """Called by the H3 event handler when WT stream data arrives."""
        self._buf.extend(data)
        if stream_ended:
            self._eof = True
        self._data_event.set()

    async def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        while not self._buf and not self._eof:
            self._data_event.clear()
            await self._data_event.wait()

        if not self._buf:
            return 0  # EOF

        n = min(len(buf), len(self._buf))
        buf[:n] = self._buf[:n]
        del self._buf[:n]
        return n

    async def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()

        # Send directly on the QUIC stream (no H3 DATA framing).
        self._protocol._quic.send_stream_data(self._stream_id, data, end_stream=False)
        self._protocol.transmit()
        return len(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._protocol._quic.send_stream_data(
                self._stream_id, b"", end_stream=True
            )
            self._protocol.transmit()
        except Exception:
            pass

    def local_addr(self) -> Addr:
        return Addr(network="webtransport", address="local")

    def remote_addr(self) -> Addr:
        if self._remote_addr:
            return Addr(
                network="webtransport",
                address=f"{self._remote_addr[0]}:{self._remote_addr[1]}",
            )
        return Addr(network="webtransport", address="unknown")

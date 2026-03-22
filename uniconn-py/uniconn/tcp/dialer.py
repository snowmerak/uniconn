"""TCP dialer using asyncio."""

from __future__ import annotations

import asyncio

from ..conn import Conn, Dialer
from .conn import TcpConn


class TcpDialer(Dialer):
    """TCP dialer using asyncio.open_connection."""

    async def dial(self, address: str) -> Conn:
        host, port_str = address.rsplit(":", 1)
        port = int(port_str)
        reader, writer = await asyncio.open_connection(host, port)
        return TcpConn(reader, writer)

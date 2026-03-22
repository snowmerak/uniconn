"""TCP dialer."""

from __future__ import annotations

import asyncio

from ..conn import Conn, Dialer
from .conn import TcpConn


class TcpDialer(Dialer):
    """TCP dialer using asyncio.open_connection."""

    async def dial(self, address: str) -> Conn:
        """
        Dial a TCP connection.

        Args:
            address: "host:port" format, e.g. "127.0.0.1:8080"
        """
        host, port_str = address.rsplit(":", 1)
        port = int(port_str)
        reader, writer = await asyncio.open_connection(host, port)
        return TcpConn(reader, writer)

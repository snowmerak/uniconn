"""WebSocket dialer."""

from __future__ import annotations

import websockets

from ..conn import Conn, Dialer
from .conn import WsConn


class WsDialer(Dialer):
    """WebSocket dialer using websockets.connect."""

    async def dial(self, address: str) -> Conn:
        """
        Dial a WebSocket connection.

        Args:
            address: WebSocket URL, e.g. "ws://127.0.0.1:8080"
        """
        ws = await websockets.connect(address)
        return WsConn(ws)

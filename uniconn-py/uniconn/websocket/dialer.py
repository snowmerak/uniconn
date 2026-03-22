"""WebSocket dialer using the ``websockets`` library."""

from __future__ import annotations

import websockets

from ..conn import Addr, Conn, Dialer
from .conn import WsConn


class WsDialer(Dialer):
    """WebSocket dialer using ``websockets.connect``."""

    async def dial(self, address: str) -> Conn:
        """Connect to a WebSocket server.

        ``address`` should be a full ws:// or wss:// URL.
        """
        ws = await websockets.connect(address)
        try:
            remote_info = ws.remote_address
            remote = Addr(network="websocket", address=f"{remote_info[0]}:{remote_info[1]}")
        except Exception:
            remote = None
        return WsConn(ws, remote=remote)

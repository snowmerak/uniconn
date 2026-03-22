"""WebSocket connection wrapping websocket-client library."""

from __future__ import annotations

from typing import Any

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class WsConn(Conn):
    """
    WebSocket connection (synchronous).

    Converts between message-oriented WebSocket and stream-oriented Conn
    by buffering partial reads.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._read_buf = bytearray()
        self._closed = False

    def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        if self._read_buf:
            n = min(len(buf), len(self._read_buf))
            buf[:n] = self._read_buf[:n]
            self._read_buf = self._read_buf[n:]
            return n

        try:
            opcode, data = self._ws.recv_data()
        except Exception:
            return 0

        if not data:
            return 0

        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        if n < len(data):
            self._read_buf.extend(data[n:])
        return n

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        self._ws.send(data, opcode=0x2)  # binary
        return len(data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._ws.close()
            except Exception:
                pass

    def local_addr(self) -> Addr | None:
        return None

    def remote_addr(self) -> Addr | None:
        try:
            sock = self._ws.sock
            if sock:
                addr = sock.getpeername()
                return Addr(network="websocket", address=f"{addr[0]}:{addr[1]}")
        except Exception:
            pass
        return None

"""TCP connection wrapping stdlib socket."""

from __future__ import annotations

import socket

from ..conn import Addr, Conn
from ..errors import ConnectionClosedError


class TcpConn(Conn):
    """TCP connection backed by a stdlib socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._closed = False

    def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()
        data = self._sock.recv(len(buf))
        if not data:
            return 0
        n = len(data)
        buf[:n] = data
        return n

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        self._sock.sendall(data)
        return len(data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._sock.close()
            except Exception:
                pass

    def local_addr(self) -> Addr | None:
        try:
            addr = self._sock.getsockname()
            return Addr(network="tcp", address=f"{addr[0]}:{addr[1]}")
        except Exception:
            return None

    def remote_addr(self) -> Addr | None:
        try:
            addr = self._sock.getpeername()
            return Addr(network="tcp", address=f"{addr[0]}:{addr[1]}")
        except Exception:
            return None

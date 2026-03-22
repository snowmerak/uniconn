"""TCP listener."""

from __future__ import annotations

import socket

from ..conn import Addr, Conn, Listener
from .conn import TcpConn


class TcpListener(Listener):
    """TCP listener backed by a stdlib socket."""

    def __init__(self, sock: socket.socket, addr: Addr) -> None:
        self._sock = sock
        self._addr = addr
        self._closed = False

    @classmethod
    def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "TcpListener":
        """Create and start a TCP listener."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(128)
        bound = sock.getsockname()
        addr = Addr(network="tcp", address=f"{bound[0]}:{bound[1]}")
        return cls(sock, addr)

    def accept(self) -> Conn:
        client_sock, _ = self._sock.accept()
        return TcpConn(client_sock)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._sock.close()

    def addr(self) -> Addr:
        return self._addr

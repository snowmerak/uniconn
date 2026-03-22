"""TCP dialer."""

from __future__ import annotations

import socket

from ..conn import Conn, Dialer
from .conn import TcpConn


class TcpDialer(Dialer):
    """TCP dialer using stdlib socket."""

    def dial(self, address: str) -> Conn:
        host, port_str = address.rsplit(":", 1)
        port = int(port_str)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        return TcpConn(sock)

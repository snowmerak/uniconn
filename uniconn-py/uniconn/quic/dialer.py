"""QUIC dialer using aioquic."""

from __future__ import annotations

import asyncio
import socket
from typing import cast

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection

from ..conn import Addr, Conn, Dialer
from .conn import QuicConn


class QuicDialer(Dialer):
    """QUIC dialer using aioquic.

    Opens one bidirectional stream per connection (matching Go's uniconn QUIC).
    """

    def __init__(
        self,
        alpn_protocols: list[str] | None = None,
        verify_mode: bool = True,
    ) -> None:
        self._alpn = alpn_protocols or ["uniconn"]
        self._verify_mode = verify_mode

    async def dial(self, address: str) -> Conn:
        """Connect to a QUIC server.

        ``address`` should be ``host:port``.
        """
        host, port_str = address.rsplit(":", 1)
        port = int(port_str)

        loop = asyncio.get_running_loop()

        config = QuicConfiguration(
            is_client=True,
            alpn_protocols=self._alpn,
        )
        config.server_name = host
        if not self._verify_mode:
            config.verify_mode = False

        # Resolve address.
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        addr = infos[0][4]
        if len(addr) == 2:
            addr = ("::ffff:" + addr[0], addr[1], 0, 0)

        quic_conn = QuicConnection(configuration=config)

        # Bind UDP socket.
        sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.bind(("::", 0, 0, 0))

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: QuicConnectionProtocol(quic_conn),
            sock=sock,
        )
        protocol = cast(QuicConnectionProtocol, protocol)

        protocol.connect(addr)
        await protocol.wait_connected()

        reader, writer = await protocol.create_stream()

        local = None
        try:
            sockname = transport.get_extra_info("sockname")
            if sockname:
                local = f"{sockname[0]}:{sockname[1]}"
        except Exception:
            pass

        conn = QuicConn(
            reader, writer,
            protocol=protocol,
            local_address=local,
            remote_address=address,
        )
        return conn

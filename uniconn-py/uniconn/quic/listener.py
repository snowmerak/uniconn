"""QUIC listener using aioquic."""

from __future__ import annotations

import asyncio
from typing import Any

from aioquic.asyncio import serve as quic_serve
from aioquic.quic.configuration import QuicConfiguration

from ..conn import Addr, Conn, Listener
from .conn import QuicConn


class QuicListener(Listener):
    """QUIC listener backed by aioquic.serve.

    Each incoming QUIC session is treated as one connection with one
    bidirectional stream (matching Go's uniconn QUIC pattern).
    """

    def __init__(self, server: Any, addr: Addr) -> None:
        self._server = server
        self._addr = addr
        self._conn_queue: asyncio.Queue[QuicConn] = asyncio.Queue()
        self._closed = False

    @classmethod
    async def bind(
        cls,
        host: str = "0.0.0.0",
        port: int = 0,
        *,
        certificate_chain: str,
        private_key: str,
        alpn_protocols: list[str] | None = None,
    ) -> "QuicListener":
        """Create and start a QUIC listener.

        Args:
            host: Bind address.
            port: Bind port (0 for auto).
            certificate_chain: Path to PEM certificate file.
            private_key: Path to PEM private key file.
            alpn_protocols: ALPN protocols (default: ["uniconn"]).
        """
        listener = cls.__new__(cls)
        listener._conn_queue = asyncio.Queue()
        listener._closed = False

        config = QuicConfiguration(
            is_client=False,
            alpn_protocols=alpn_protocols or ["uniconn"],
        )
        config.load_cert_chain(certificate_chain, private_key)

        def stream_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            """Called for each new stream opened by a client."""
            # Extract addresses from the writer's transport
            try:
                transport = writer.transport
                protocol = transport._protocol  # QuicConnectionProtocol
                local = f"{host}:{listener._addr.address.split(':')[-1]}"
                peername = writer.get_extra_info("peername")
                remote = f"{peername[0]}:{peername[1]}" if peername else None
            except Exception:
                protocol = None
                local = None
                remote = None

            conn = QuicConn(reader, writer, protocol=protocol,
                           local_address=local, remote_address=remote)
            listener._conn_queue.put_nowait(conn)

        server = await quic_serve(
            host, port,
            configuration=config,
            stream_handler=stream_handler,
        )

        # Resolve actual bound port.
        try:
            bound = server._transport.get_extra_info("sockname")
            if bound:
                listener._addr = Addr(network="quic", address=f"{bound[0]}:{bound[1]}")
        except Exception:
            listener._addr = Addr(network="quic", address=f"{host}:{port}")

        listener._server = server
        return listener

    async def accept(self) -> Conn:
        return await self._conn_queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._server.close()

    def addr(self) -> Addr:
        return self._addr

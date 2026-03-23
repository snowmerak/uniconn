"""WebTransport listener (server) using aioquic (QUIC + H3)."""

from __future__ import annotations

import asyncio
import ssl
from typing import Optional

from aioquic.asyncio import serve as quic_serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent, StreamDataReceived, HandshakeCompleted

from ..conn import Addr, Conn, Listener
from .conn import WebTransportConn


class _WTServerProtocol(QuicConnectionProtocol):
    """Server-side protocol that handles H3 + WebTransport sessions."""

    def __init__(self, *args, listener: "WebTransportListener", **kwargs):
        super().__init__(*args, **kwargs)
        self._h3: Optional[H3Connection] = None
        self._listener = listener
        self._wt_conns: dict[int, WebTransportConn] = {}  # stream_id -> conn
        self._session_ids: set[int] = set()

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, HandshakeCompleted):
            self._h3 = H3Connection(self._quic, enable_webtransport=True)

        if self._h3 is None:
            return

        if isinstance(event, StreamDataReceived):
            # Check if this is data on a known WT stream — bypass H3
            if event.stream_id in self._wt_conns:
                self._wt_conns[event.stream_id].feed_data(
                    event.data, event.end_stream
                )
                return

            for h3_event in self._h3.handle_event(event):
                self._h3_event_received(h3_event)

    def _h3_event_received(self, event) -> None:
        if isinstance(event, HeadersReceived):
            headers = dict(event.headers)
            method = headers.get(b":method", b"")
            protocol = headers.get(b":protocol", b"")

            if method == b"CONNECT" and protocol == b"webtransport":
                # Accept WebTransport session — respond 200 OK.
                self._session_ids.add(event.stream_id)
                self._h3.send_headers(
                    stream_id=event.stream_id,
                    headers=[(b":status", b"200")],
                )
                self.transmit()

        elif isinstance(event, WebTransportStreamDataReceived):
            if event.stream_id not in self._wt_conns:
                # New WT stream — create conn and enqueue.
                remote = None
                try:
                    peername = self._quic._network_paths[0].addr
                    remote = (peername[0], peername[1])
                except Exception:
                    pass

                wt_conn = WebTransportConn(
                    protocol=self,
                    h3_conn=self._h3,
                    stream_id=event.stream_id,
                    session_id=event.session_id,
                    remote_addr=remote,
                )
                self._wt_conns[event.stream_id] = wt_conn
                self._listener._conn_queue.put_nowait(wt_conn)

            self._wt_conns[event.stream_id].feed_data(
                event.data, event.stream_ended
            )


class WebTransportListener(Listener):
    """WebTransport listener.

    Uses aioquic to serve QUIC + H3 + WebTransport sessions.
    Each incoming WT bidi stream becomes a Conn.
    """

    def __init__(self) -> None:
        self._server = None
        self._conn_queue: asyncio.Queue[WebTransportConn] = asyncio.Queue()
        self._closed = False
        self._addr = Addr(network="webtransport", address="unknown")

    @classmethod
    async def bind(
        cls,
        host: str = "0.0.0.0",
        port: int = 0,
        *,
        certificate_chain: str,
        private_key: str,
    ) -> "WebTransportListener":
        """Create and start a WebTransport listener.

        Args:
            host: Bind address.
            port: Bind port (0 for auto).
            certificate_chain: Path to PEM certificate file.
            private_key: Path to PEM private key file.
        """
        listener = cls()

        config = QuicConfiguration(
            is_client=False,
            alpn_protocols=["h3"],
            max_datagram_frame_size=65536,
        )
        config.load_cert_chain(certificate_chain, private_key)

        server = await quic_serve(
            host,
            port,
            configuration=config,
            create_protocol=lambda *args, **kwargs: _WTServerProtocol(
                *args, listener=listener, **kwargs
            ),
        )

        # Resolve actual bound port.
        try:
            bound = server._transport.get_extra_info("sockname")
            if bound:
                listener._addr = Addr(
                    network="webtransport",
                    address=f"{bound[0]}:{bound[1]}",
                )
        except Exception:
            listener._addr = Addr(
                network="webtransport", address=f"{host}:{port}"
            )

        listener._server = server
        return listener

    async def accept(self) -> Conn:
        return await self._conn_queue.get()

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            if self._server:
                self._server.close()

    def addr(self) -> Addr:
        return self._addr

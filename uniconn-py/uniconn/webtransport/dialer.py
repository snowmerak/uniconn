"""WebTransport dialer using aioquic (QUIC + H3)."""

from __future__ import annotations

import asyncio
import socket
import ssl
from typing import Optional, cast
from urllib.parse import urlparse

from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import (
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import QuicEvent, StreamDataReceived, HandshakeCompleted

from ..conn import Addr, Conn, Dialer
from .conn import WebTransportConn


class _WTClientProtocol(QuicConnectionProtocol):
    """Custom QuicConnectionProtocol that handles H3 + WebTransport events."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._h3: Optional[H3Connection] = None
        self._wt_conn: Optional[WebTransportConn] = None
        self._session_ready = asyncio.Event()
        self._session_id: Optional[int] = None
        self._wt_stream_id: Optional[int] = None

    def quic_event_received(self, event: QuicEvent) -> None:
        if isinstance(event, HandshakeCompleted):
            self._h3 = H3Connection(self._quic, enable_webtransport=True)

        if self._h3 is None:
            return

        if isinstance(event, StreamDataReceived):
            # If data arrives on the WT bidi stream, feed it directly
            # to the WebTransportConn.  Go's webtransport-go sends raw
            # data (no H3 framing) on WT streams, but aioquic may not
            # emit a WebTransportStreamDataReceived for server-to-client
            # direction on a client-initiated WT stream.
            if (
                self._wt_conn is not None
                and self._wt_stream_id is not None
                and event.stream_id == self._wt_stream_id
            ):
                self._wt_conn.feed_data(event.data, event.end_stream)
                return

            for h3_event in self._h3.handle_event(event):
                self._h3_event_received(h3_event)

    def _h3_event_received(self, event) -> None:
        if isinstance(event, HeadersReceived):
            headers = dict(event.headers)
            status = headers.get(b":status", b"")
            if status == b"200":
                self._session_id = event.stream_id
                self._session_ready.set()

        elif isinstance(event, WebTransportStreamDataReceived):
            if self._wt_conn and event.stream_id == self._wt_conn._stream_id:
                self._wt_conn.feed_data(event.data, event.stream_ended)


class WebTransportDialer(Dialer):
    """WebTransport dialer.

    Connects to a WebTransport server via QUIC + HTTP/3 CONNECT.
    """

    def __init__(self, verify_ssl: bool = False) -> None:
        self._verify_ssl = verify_ssl

    async def dial(self, address: str) -> Conn:
        """Dial a WebTransport server.

        Args:
            address: URL like "https://host:port/path"
        """
        parsed = urlparse(address)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 443
        path = parsed.path or "/"

        loop = asyncio.get_running_loop()

        config = QuicConfiguration(
            is_client=True,
            alpn_protocols=["h3"],
            max_datagram_frame_size=65536,
        )
        config.server_name = host
        if not self._verify_ssl:
            config.verify_mode = ssl.CERT_NONE

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
            lambda: _WTClientProtocol(quic_conn),
            sock=sock,
        )
        protocol = cast(_WTClientProtocol, protocol)

        # Connect QUIC (H3 is created in HandshakeCompleted callback).
        protocol.connect(addr)
        await protocol.wait_connected()

        # Wait for H3 to be ready.
        for _ in range(50):
            if protocol._h3 is not None:
                break
            await asyncio.sleep(0.01)

        if protocol._h3 is None:
            transport.close()
            raise ConnectionError("H3 connection not established")

        # Small delay so server SETTINGS are processed.
        await asyncio.sleep(0.1)

        # Send CONNECT extended connect for WebTransport session.
        stream_id = protocol._quic.get_next_available_stream_id()
        protocol._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":protocol", b"webtransport"),
                (b":scheme", b"https"),
                (b":authority", f"{host}:{port}".encode()),
                (b":path", path.encode()),
            ],
        )
        protocol.transmit()

        # Wait for session (200 OK).
        try:
            await asyncio.wait_for(protocol._session_ready.wait(), timeout=10)
        except asyncio.TimeoutError:
            transport.close()
            raise ConnectionError("WebTransport session timed out")

        session_id = protocol._session_id

        # Create bidi WebTransport stream.
        wt_stream_id = protocol._h3.create_webtransport_stream(
            session_id=session_id, is_unidirectional=False
        )
        protocol._wt_stream_id = wt_stream_id
        protocol.transmit()

        # Wrap in conn.
        wt_conn = WebTransportConn(
            protocol=protocol,
            h3_conn=protocol._h3,
            stream_id=wt_stream_id,
            session_id=session_id,
            remote_addr=(host, port),
        )
        protocol._wt_conn = wt_conn

        return wt_conn

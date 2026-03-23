"""Tests for multi-protocol negotiate, MultiDialer, and MultiListener."""

import asyncio
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

import pytest

from uniconn.multi import (
    NegotiateResponse,
    ProtocolEntry,
    MultiDialer,
    MultiDialerConfig,
    MultiListener,
    TransportConfig,
)
from uniconn.conn import Conn, Listener, Dialer, Addr


# ─── Mock implementations ───────────────────────────────────


class MockConn(Conn):
    def __init__(self) -> None:
        self._buf = bytearray()
        self.closed = False

    async def read(self, buf: bytearray) -> int:
        n = min(len(buf), len(self._buf))
        buf[:n] = self._buf[:n]
        self._buf = self._buf[n:]
        return n

    async def write(self, data: bytes) -> int:
        self._buf.extend(data)
        return len(data)

    async def close(self) -> None:
        self.closed = True

    def local_addr(self) -> Addr:
        return Addr("mock", "local")

    def remote_addr(self) -> Addr:
        return Addr("mock", "remote")


class MockListener(Listener):
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Conn] = asyncio.Queue()
        self._closed = False

    def push(self, conn: Conn) -> None:
        self._queue.put_nowait(conn)

    async def accept(self) -> Conn:
        if self._closed:
            raise RuntimeError("closed")
        return await self._queue.get()

    async def close(self) -> None:
        self._closed = True

    def addr(self) -> Addr:
        return Addr("mock", "mock:0")


class MockDialer(Dialer):
    def __init__(self, should_fail: bool = False) -> None:
        self._should_fail = should_fail

    async def dial(self, address: str) -> Conn:
        if self._should_fail:
            raise RuntimeError("mock dial failure")
        return MockConn()


# ─── Tests ──────────────────────────────────────────────────


class TestNegotiateResponse:
    def test_json_roundtrip(self):
        resp = NegotiateResponse(protocols=[
            ProtocolEntry(name="tcp", address="server:8001"),
            ProtocolEntry(name="websocket", address="ws://server:8002/ws"),
        ])
        json_str = resp.to_json()
        parsed = NegotiateResponse.from_json(json_str)
        assert len(parsed.protocols) == 2
        assert parsed.protocols[0].name == "tcp"
        assert parsed.protocols[1].address == "ws://server:8002/ws"


class TestMultiListener:
    @pytest.mark.asyncio
    async def test_fan_in(self):
        ln1 = MockListener()
        ln2 = MockListener()

        ml = MultiListener([
            TransportConfig(protocol="tcp", address="host:1", listener=ln1),
            TransportConfig(protocol="websocket", address="ws://host:2", listener=ln2),
        ])
        await ml.start()

        conn1 = MockConn()
        conn2 = MockConn()
        ln1.push(conn1)
        ln2.push(conn2)

        # Small delay for accept loops to process.
        await asyncio.sleep(0.1)

        r1 = await ml.accept_with()
        r2 = await ml.accept_with()
        protos = {r1.protocol, r2.protocol}
        assert "tcp" in protos
        assert "websocket" in protos

        await ml.close()

    def test_negotiate_response(self):
        ml = MultiListener([
            TransportConfig(protocol="tcp", address="host:1", listener=MockListener()),
        ])
        neg = ml.get_negotiate_response()
        assert len(neg.protocols) == 1
        assert neg.protocols[0].name == "tcp"


class TestMultiDialer:
    @pytest.mark.asyncio
    async def test_selects_best_protocol(self):
        """Client only has TCP dialer → should select TCP."""
        neg_resp = {
            "protocols": [
                {"name": "websocket", "address": "ws://127.0.0.1:9999/ws"},
                {"name": "tcp", "address": "127.0.0.1:9998"},
            ]
        }

        # Start a mini HTTP negotiate server.
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(neg_resp).encode())

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            md = MultiDialer(MultiDialerConfig(
                negotiate_url=f"http://127.0.0.1:{port}/negotiate",
                dialers={"tcp": MockDialer()},
            ))
            conn, proto = await md.dial()
            assert proto == "tcp"
            assert not conn.closed  # type: ignore
        finally:
            server.shutdown()

    @pytest.mark.asyncio
    async def test_fallback(self):
        """WS fails → should fall back to TCP."""
        neg_resp = {
            "protocols": [
                {"name": "websocket", "address": "ws://127.0.0.1:9999/ws"},
                {"name": "tcp", "address": "127.0.0.1:9998"},
            ]
        }

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(neg_resp).encode())

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            md = MultiDialer(MultiDialerConfig(
                negotiate_url=f"http://127.0.0.1:{port}/negotiate",
                dialers={
                    "websocket": MockDialer(should_fail=True),
                    "tcp": MockDialer(should_fail=False),
                },
                dial_timeout=1.0,
            ))
            conn, proto = await md.dial()
            assert proto == "tcp"
        finally:
            server.shutdown()

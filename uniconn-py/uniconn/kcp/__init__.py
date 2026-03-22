"""KCP transport adapter for uniconn (synchronous).

Uses the `kcp` PyPI package (kcp-py) which provides Python bindings
for the KCP reliable UDP protocol.

- KcpListener: wraps kcp-py's KCPServerAsync in a background thread
- KcpDialer: wraps kcp-py's KCPClientSync directly
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from queue import Queue, Empty

from ..conn import Addr, Conn, Listener, Dialer
from ..errors import ConnectionClosedError


class KcpConn(Conn):
    """KCP connection backed by kcp-py."""

    def __init__(
        self,
        kcp_conn: Any,
        send_fn: Any = None,
        local_address: str | None = None,
        remote_address: str | None = None,
    ) -> None:
        self._conn = kcp_conn
        self._send_fn = send_fn  # for client-side direct send
        self._local_addr = local_address
        self._remote_addr = remote_address
        self._recv_queue: Queue[bytes] = Queue()
        self._recv_buf = bytearray()
        self._closed = False

    def _on_data(self, data: bytes) -> None:
        """Called when data arrives."""
        if not self._closed:
            self._recv_queue.put(data)

    def read(self, buf: bytearray) -> int:
        if self._closed:
            raise ConnectionClosedError()

        if self._recv_buf:
            n = min(len(buf), len(self._recv_buf))
            buf[:n] = self._recv_buf[:n]
            self._recv_buf = self._recv_buf[n:]
            return n

        try:
            data = self._recv_queue.get(timeout=10.0)
        except Empty:
            return 0

        n = min(len(buf), len(data))
        buf[:n] = data[:n]
        if n < len(data):
            self._recv_buf.extend(data[n:])
        return n

    def write(self, data: bytes) -> int:
        if self._closed:
            raise ConnectionClosedError()
        if self._send_fn:
            self._send_fn(data)
        else:
            self._conn.enqueue(data)
        return len(data)

    def close(self) -> None:
        self._closed = True

    def local_addr(self) -> Addr | None:
        if self._local_addr:
            return Addr(network="kcp", address=self._local_addr)
        return None

    def remote_addr(self) -> Addr | None:
        if self._remote_addr:
            return Addr(network="kcp", address=self._remote_addr)
        return None


class KcpListener(Listener):
    """KCP listener using kcp-py's KCPServerAsync in a background thread."""

    def __init__(self, addr: Addr) -> None:
        self._addr = addr
        self._conn_queue: Queue[KcpConn] = Queue()
        self._connections: dict[tuple, KcpConn] = {}
        self._thread: threading.Thread | None = None
        self._closed = False

    @classmethod
    def bind(
        cls, host: str = "0.0.0.0", port: int = 0, conv_id: int = 1
    ) -> "KcpListener":
        """Create and start a KCP listener."""
        listener = cls(Addr(network="kcp", address=f"{host}:{port}"))
        ready = threading.Event()

        def run_server():
            # Create event loop + KCPServerAsync inside the thread.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            from kcp import KCPServerAsync

            server = KCPServerAsync(host, port, conv_id=conv_id)

            @server.on_data
            def handle_data(connection: Any, data: bytes) -> None:
                addr_tuple = connection.address_tuple
                if addr_tuple not in listener._connections:
                    kcp_conn = KcpConn(
                        connection,
                        local_address=f"{host}:{port}",
                        remote_address=f"{addr_tuple[0]}:{addr_tuple[1]}",
                    )
                    listener._connections[addr_tuple] = kcp_conn
                    listener._conn_queue.put(kcp_conn)
                listener._connections[addr_tuple]._on_data(data)

            ready.set()
            server.start()  # Blocking — runs the event loop.

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        ready.wait(timeout=2.0)
        time.sleep(0.1)  # Extra time for UDP bind.

        listener._thread = thread
        return listener

    def accept(self) -> Conn:
        return self._conn_queue.get()

    def close(self) -> None:
        self._closed = True

    def addr(self) -> Addr:
        return self._addr


class KcpDialer(Dialer):
    """KCP dialer using kcp-py's KCPClientSync."""

    def __init__(self, conv_id: int = 1) -> None:
        self._conv_id = conv_id

    def dial(self, address: str) -> Conn:
        from kcp import KCPClientSync

        host, port_str = address.rsplit(":", 1)
        port = int(port_str)

        kcp_conn = KcpConn(
            None,
            remote_address=address,
        )

        client = KCPClientSync(
            host, port,
            conv_id=self._conv_id,
            no_delay=True,
            update_interval=10,
            resend_count=2,
            no_congestion_control=True,
            receive_window_size=128,
            send_window_size=128,
        )

        @client.on_data
        def on_data(data: bytes) -> None:
            kcp_conn._on_data(data)

        kcp_conn._send_fn = client.send

        # Start client in background thread.
        thread = threading.Thread(target=client.start, daemon=True)
        thread.start()
        time.sleep(0.05)  # Let client connect.

        return kcp_conn

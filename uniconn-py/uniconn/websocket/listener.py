"""WebSocket listener (synchronous)."""

from __future__ import annotations

import socket
import threading
import hashlib
import base64
import struct
from typing import Any

from ..conn import Addr, Conn, Listener
from .conn import WsConn


class WsListener(Listener):
    """
    WebSocket listener using stdlib socket + manual WS handshake.

    For production use, consider a proper WebSocket server library.
    This provides a minimal synchronous implementation for interop testing.
    """

    def __init__(self, sock: socket.socket, addr: Addr) -> None:
        self._sock = sock
        self._addr = addr
        self._closed = False

    @classmethod
    def bind(cls, host: str = "0.0.0.0", port: int = 0) -> "WsListener":
        """Create and start a WebSocket listener."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(128)
        bound = sock.getsockname()
        addr = Addr(network="websocket", address=f"{bound[0]}:{bound[1]}")
        return cls(sock, addr)

    def accept(self) -> Conn:
        """Accept a WebSocket connection (performs HTTP upgrade handshake)."""
        client_sock, _ = self._sock.accept()
        _do_ws_accept_handshake(client_sock)
        return _RawWsConn(client_sock)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._sock.close()

    def addr(self) -> Addr:
        return self._addr


# ── Minimal WebSocket framing for synchronous server ──────

_WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _do_ws_accept_handshake(sock: socket.socket) -> None:
    """Perform the server-side WebSocket handshake over a raw socket."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("client disconnected during handshake")
        data += chunk

    headers = data.decode("utf-8", errors="replace")
    key = ""
    for line in headers.split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
            break

    if not key:
        raise ValueError("missing Sec-WebSocket-Key header")

    accept = base64.b64encode(
        hashlib.sha1((key + _WS_MAGIC.decode()).encode()).digest()
    ).decode()

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    sock.sendall(response.encode())


class _RawWsConn(Conn):
    """Minimal synchronous WebSocket connection over a raw socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._read_buf = bytearray()
        self._closed = False

    def read(self, buf: bytearray) -> int:
        if self._closed:
            return 0

        if self._read_buf:
            n = min(len(buf), len(self._read_buf))
            buf[:n] = self._read_buf[:n]
            self._read_buf = self._read_buf[n:]
            return n

        # Read a WebSocket frame.
        try:
            payload = _read_ws_frame(self._sock)
        except Exception:
            return 0

        if payload is None:
            return 0

        n = min(len(buf), len(payload))
        buf[:n] = payload[:n]
        if n < len(payload):
            self._read_buf.extend(payload[n:])
        return n

    def write(self, data: bytes) -> int:
        if self._closed:
            return 0
        _write_ws_frame(self._sock, data, opcode=0x02)  # binary
        return len(data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                _write_ws_frame(self._sock, b"", opcode=0x08)  # close
            except Exception:
                pass
            self._sock.close()

    def local_addr(self) -> Addr | None:
        try:
            a = self._sock.getsockname()
            return Addr(network="websocket", address=f"{a[0]}:{a[1]}")
        except Exception:
            return None

    def remote_addr(self) -> Addr | None:
        try:
            a = self._sock.getpeername()
            return Addr(network="websocket", address=f"{a[0]}:{a[1]}")
        except Exception:
            return None


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("unexpected EOF")
        buf.extend(chunk)
    return bytes(buf)


def _read_ws_frame(sock: socket.socket) -> bytes | None:
    """Read one WebSocket frame, unmask if needed. Returns payload."""
    header = _recv_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F

    if opcode == 0x08:  # close
        return None

    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]

    mask = _recv_exact(sock, 4) if masked else None
    payload = bytearray(_recv_exact(sock, length))

    if mask:
        for i in range(length):
            payload[i] ^= mask[i % 4]

    return bytes(payload)


def _write_ws_frame(
    sock: socket.socket,
    data: bytes,
    opcode: int = 0x02,
    mask: bool = False,
) -> None:
    """Write a WebSocket frame (server-side, unmasked by default)."""
    header = bytearray()
    header.append(0x80 | opcode)  # FIN + opcode

    length = len(data)
    if length < 126:
        header.append((0x80 if mask else 0x00) | length)
    elif length < 65536:
        header.append((0x80 if mask else 0x00) | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append((0x80 if mask else 0x00) | 127)
        header.extend(struct.pack("!Q", length))

    sock.sendall(bytes(header) + data)

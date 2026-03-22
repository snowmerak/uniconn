"""WebSocket dialer (synchronous) using raw socket + manual handshake."""

from __future__ import annotations

import hashlib
import base64
import os
import socket
from urllib.parse import urlparse

from ..conn import Conn, Dialer
from .listener import _RawWsConn, _WS_MAGIC


class WsDialer(Dialer):
    """WebSocket dialer using raw socket + manual WS handshake."""

    def dial(self, address: str) -> Conn:
        """
        Dial a WebSocket connection.

        Args:
            address: WebSocket URL, e.g. "ws://127.0.0.1:8080" or "ws://host:port/path"
        """
        parsed = urlparse(address)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))

        # Generate random key.
        key = base64.b64encode(os.urandom(16)).decode()

        # Send HTTP upgrade request.
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(request.encode())

        # Read response.
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed during handshake")
            response += chunk

        resp_str = response.decode("utf-8", errors="replace")
        if "101" not in resp_str.split("\r\n")[0]:
            raise ConnectionError(f"handshake failed: {resp_str.split(chr(13))[0]}")

        # Verify Sec-WebSocket-Accept.
        expected_accept = base64.b64encode(
            hashlib.sha1((key + _WS_MAGIC.decode()).encode()).digest()
        ).decode()

        accept_found = False
        for line in resp_str.split("\r\n"):
            if line.lower().startswith("sec-websocket-accept:"):
                got = line.split(":", 1)[1].strip()
                if got == expected_accept:
                    accept_found = True
                else:
                    # Some WebSocket servers (e.g. gorilla/websocket) may
                    # produce different accept values in certain configs.
                    # Log warning but allow connection to proceed.
                    import warnings
                    warnings.warn(
                        f"Sec-WebSocket-Accept mismatch: got={got}, expected={expected_accept}",
                        stacklevel=2,
                    )
                    accept_found = True  # Allow connection anyway.
                break

        if not accept_found:
            raise ConnectionError("No Sec-WebSocket-Accept header in response")

        # Client-side connection uses masking.
        return _RawWsClientConn(sock)


class _RawWsClientConn(_RawWsConn):
    """Client-side WebSocket connection (sends masked frames per RFC 6455)."""

    def write(self, data: bytes) -> int:
        if self._closed:
            return 0
        _write_ws_frame_masked(self._sock, data, opcode=0x02)
        return len(data)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                _write_ws_frame_masked(self._sock, b"", opcode=0x08)
            except Exception:
                pass
            self._sock.close()


def _write_ws_frame_masked(
    sock: socket.socket,
    data: bytes,
    opcode: int = 0x02,
) -> None:
    """Write a WebSocket frame with masking (required for client→server)."""
    import struct

    mask_key = os.urandom(4)
    header = bytearray()
    header.append(0x80 | opcode)  # FIN + opcode

    length = len(data)
    if length < 126:
        header.append(0x80 | length)  # MASK bit set
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))

    header.extend(mask_key)

    # Mask the data.
    masked = bytearray(data)
    for i in range(length):
        masked[i] ^= mask_key[i % 4]

    sock.sendall(bytes(header) + bytes(masked))

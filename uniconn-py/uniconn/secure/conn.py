"""SecureConn — XChaCha20-Poly1305 encrypted connection (synchronous)."""

from __future__ import annotations

import struct
import time

from Crypto.Cipher import ChaCha20_Poly1305  # pycryptodome

from ..conn import Addr, Conn
from .constants import (
    MSG_DATA,
    MSG_ERROR,
    NONCE_PREFIX_SIZE,
    NONCE_SIZE,
    TIMESTAMP_SIZE,
    COUNTER_SIZE,
)
from .message import read_frame_from_conn, write_frame_to_conn, marshal_data, marshal_error


class SecureConn(Conn):
    """
    Encrypted connection wrapping any Conn with XChaCha20-Poly1305 (synchronous).
    """

    def __init__(self, keys, is_initiator: bool) -> None:
        if is_initiator:
            self._send_key = keys.initiator_key
            self._recv_key = keys.responder_key
            self._send_pfx = keys.initiator_nonce_pfx
            self._recv_pfx = keys.responder_nonce_pfx
        else:
            self._send_key = keys.responder_key
            self._recv_key = keys.initiator_key
            self._send_pfx = keys.responder_nonce_pfx
            self._recv_pfx = keys.initiator_nonce_pfx

        self._send_counter: int = 0
        self._recv_buf = bytearray()
        self._inner_conn: Conn | None = None

    def bind(self, conn: Conn) -> "SecureConn":
        """Bind to an underlying Conn. Returns self for chaining."""
        self._inner_conn = conn
        return self

    def read(self, buf: bytearray) -> int:
        assert self._inner_conn is not None

        if self._recv_buf:
            n = min(len(buf), len(self._recv_buf))
            buf[:n] = self._recv_buf[:n]
            self._recv_buf = self._recv_buf[n:]
            return n

        body = read_frame_from_conn(self._inner_conn)
        if not body:
            raise ConnectionError("empty frame")

        msg_type = body[0]

        if msg_type == MSG_DATA:
            return self._handle_data(body, buf)
        elif msg_type == MSG_ERROR:
            reason = "unknown"
            if len(body) >= 3:
                r_len = struct.unpack("!H", body[1:3])[0]
                if 3 + r_len <= len(body):
                    reason = body[3 : 3 + r_len].decode("utf-8", errors="replace")
            raise ConnectionError(f"peer error: {reason}")
        else:
            raise ValueError(f"unexpected message type: 0x{msg_type:02x}")

    def _handle_data(self, body: bytes, buf: bytearray) -> int:
        if len(body) < 13:
            raise ValueError("DATA message too short")

        ts = struct.unpack("!I", body[1:5])[0]
        counter = struct.unpack("!Q", body[5:13])[0]
        ciphertext = body[13:]

        nonce = bytearray(NONCE_SIZE)
        nonce[:NONCE_PREFIX_SIZE] = self._recv_pfx
        struct.pack_into("!I", nonce, NONCE_PREFIX_SIZE, ts)
        struct.pack_into("!Q", nonce, NONCE_PREFIX_SIZE + TIMESTAMP_SIZE, counter)

        cipher = ChaCha20_Poly1305.new(key=self._recv_key, nonce=bytes(nonce))
        try:
            plaintext = cipher.decrypt_and_verify(
                ciphertext[:-16], ciphertext[-16:]
            )
        except ValueError:
            raise ValueError("AEAD decrypt failed: tag mismatch")

        n = min(len(buf), len(plaintext))
        buf[:n] = plaintext[:n]
        if n < len(plaintext):
            self._recv_buf.extend(plaintext[n:])
        return n

    def write(self, data: bytes) -> int:
        assert self._inner_conn is not None

        if not data:
            return 0

        counter = self._send_counter
        self._send_counter += 1
        ts = int(time.time()) & 0xFFFFFFFF

        nonce = bytearray(NONCE_SIZE)
        nonce[:NONCE_PREFIX_SIZE] = self._send_pfx
        struct.pack_into("!I", nonce, NONCE_PREFIX_SIZE, ts)
        struct.pack_into("!Q", nonce, NONCE_PREFIX_SIZE + TIMESTAMP_SIZE, counter)

        cipher = ChaCha20_Poly1305.new(key=self._send_key, nonce=bytes(nonce))
        ciphertext, tag = cipher.encrypt_and_digest(data)
        ct_with_tag = ciphertext + tag

        frame_body = marshal_data(ts, counter, ct_with_tag)
        write_frame_to_conn(self._inner_conn, frame_body)
        return len(data)

    def close(self) -> None:
        if self._inner_conn is not None:
            try:
                err_body = marshal_error("closed")
                write_frame_to_conn(self._inner_conn, err_body)
            except Exception:
                pass
            self._inner_conn.close()

    def local_addr(self) -> Addr | None:
        return self._inner_conn.local_addr() if self._inner_conn else None

    def remote_addr(self) -> Addr | None:
        return self._inner_conn.remote_addr() if self._inner_conn else None

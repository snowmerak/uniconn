"""Wire format marshal/unmarshal for USCP v1 messages (synchronous)."""

from __future__ import annotations

import struct
import socket

from .constants import MAX_MESSAGE_SIZE, MSG_DATA, MSG_ERROR, TIMESTAMP_SIZE, COUNTER_SIZE


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes from a socket."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("unexpected EOF during recv_exact")
        buf.extend(chunk)
    return bytes(buf)


def read_frame_from_conn(conn) -> bytes:
    """Read a framed message from a Conn: [4B big-endian length][body]."""
    len_buf = bytearray(4)
    offset = 0
    while offset < 4:
        remaining = bytearray(4 - offset)
        n = conn.read(remaining)
        if n == 0:
            raise ConnectionError("unexpected EOF reading frame length")
        len_buf[offset:offset + n] = remaining[:n]
        offset += n
    length = struct.unpack("!I", len_buf)[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"frame too large: {length}")

    body = bytearray(length)
    offset = 0
    while offset < length:
        remaining = bytearray(length - offset)
        n = conn.read(remaining)
        if n == 0:
            raise ConnectionError("unexpected EOF reading frame body")
        body[offset:offset + n] = remaining[:n]
        offset += n
    return bytes(body)


def write_frame_to_conn(conn, body: bytes) -> None:
    """Write a framed message to a Conn: [4B big-endian length][body]."""
    frame = struct.pack("!I", len(body)) + body
    conn.write(frame)


def marshal_hello(
    msg_type: int, public_key: bytes, payload: bytes, signature: bytes
) -> bytes:
    """
    Serialize HELLO/HELLO_REPLY with framing:
    [4B frame_len][1B type][2B pk_len][pk][2B pl_len][pl][2B sig_len][sig]
    """
    body = bytearray()
    body.append(msg_type)
    body.extend(struct.pack("!H", len(public_key)))
    body.extend(public_key)
    body.extend(struct.pack("!H", len(payload)))
    body.extend(payload)
    body.extend(struct.pack("!H", len(signature)))
    body.extend(signature)

    frame = struct.pack("!I", len(body)) + body
    return bytes(frame)


def unmarshal_hello(body: bytes) -> dict:
    """Unmarshal HELLO or HELLO_REPLY from a frame body."""
    if not body:
        raise ValueError("empty message body")

    msg_type = body[0]
    off = 1

    pk_len = struct.unpack("!H", body[off : off + 2])[0]
    off += 2
    public_key = body[off : off + pk_len]
    off += pk_len

    pl_len = struct.unpack("!H", body[off : off + 2])[0]
    off += 2
    payload = body[off : off + pl_len]
    off += pl_len

    sig_len = struct.unpack("!H", body[off : off + 2])[0]
    off += 2
    signature = body[off : off + sig_len]

    return {
        "msg_type": msg_type,
        "public_key": bytes(public_key),
        "payload": bytes(payload),
        "signature": bytes(signature),
    }


def marshal_data(timestamp: int, counter: int, ciphertext: bytes) -> bytes:
    """Marshal DATA body: [1B type][4B ts][8B counter][ciphertext]."""
    body = bytearray()
    body.append(MSG_DATA)
    body.extend(struct.pack("!I", timestamp))
    body.extend(struct.pack("!Q", counter))
    body.extend(ciphertext)
    return bytes(body)


def marshal_error(reason: str) -> bytes:
    """Marshal ERROR body."""
    reason_bytes = reason.encode("utf-8")
    body = bytearray()
    body.append(MSG_ERROR)
    body.extend(struct.pack("!H", len(reason_bytes)))
    body.extend(reason_bytes)
    return bytes(body)

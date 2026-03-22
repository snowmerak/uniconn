"""Wire format marshal/unmarshal for USCP v1 messages."""

from __future__ import annotations

import struct

from ..conn import Conn
from .constants import MAX_MESSAGE_SIZE, MSG_DATA, MSG_ERROR, TIMESTAMP_SIZE, COUNTER_SIZE


async def read_exact(conn: Conn, n: int) -> bytes:
    """Read exactly n bytes from a Conn."""
    buf = bytearray(n)
    offset = 0
    while offset < n:
        remaining = bytearray(n - offset)
        read = await conn.read(remaining)
        if read == 0:
            raise ConnectionError("unexpected EOF during read_exact")
        buf[offset : offset + read] = remaining[:read]
        offset += read
    return bytes(buf)


async def read_frame(conn: Conn) -> bytes:
    """Read a framed message: [4B big-endian length][body]."""
    len_buf = await read_exact(conn, 4)
    length = struct.unpack("!I", len_buf)[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"frame too large: {length}")
    return await read_exact(conn, length)


async def write_frame(conn: Conn, body: bytes) -> None:
    """Write a framed message: [4B big-endian length][body]."""
    frame = struct.pack("!I", len(body)) + body
    await conn.write(frame)


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
    """
    Unmarshal a HELLO or HELLO_REPLY from a frame body.
    Returns dict with keys: msg_type, public_key, payload, signature.
    """
    if not body:
        raise ValueError("empty message body")

    msg_type = body[0]
    off = 1

    # Public key.
    pk_len = struct.unpack("!H", body[off : off + 2])[0]
    off += 2
    public_key = body[off : off + pk_len]
    off += pk_len

    # Payload (ek or ct).
    pl_len = struct.unpack("!H", body[off : off + 2])[0]
    off += 2
    payload = body[off : off + pl_len]
    off += pl_len

    # Signature.
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
    """Marshal ERROR body: [1B type][2B reason_len][reason_utf8]."""
    reason_bytes = reason.encode("utf-8")
    body = bytearray()
    body.append(MSG_ERROR)
    body.extend(struct.pack("!H", len(reason_bytes)))
    body.extend(reason_bytes)
    return bytes(body)

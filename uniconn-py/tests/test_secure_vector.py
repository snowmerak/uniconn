import asyncio
import json
from pathlib import Path

import pytest

from uniconn.secure.conn import SecureConn
from uniconn.secure.handshake import SessionKeys


class MemoryConn:
    def __init__(self, data=b""):
        self.data = bytearray(data)
        self.closed = False
        self.writes = 0

    async def read(self, buf):
        await asyncio.sleep(0)
        n = min(len(buf), len(self.data), 3)
        buf[:n] = self.data[:n]
        del self.data[:n]
        return n

    async def write(self, data):
        self.writes += 1
        halfway = len(data) // 2
        self.data.extend(data[:halfway])
        await asyncio.sleep(0)
        self.data.extend(data[halfway:])
        return len(data)

    async def close(self):
        self.closed = True


def vector():
    path = Path(__file__).resolve().parents[2] / "uniconn-tests/vectors/secure-data-v1.json"
    data = json.loads(path.read_text())
    keys = SessionKeys(*(bytes.fromhex(data[field]) for field in (
        "initiator_key", "responder_key", "initiator_nonce_prefix", "responder_nonce_prefix")))
    return data, keys, bytes.fromhex(data["frame"]), bytes.fromhex(data["plaintext"])


@pytest.mark.asyncio
async def test_shared_vector_and_replay_rejection(monkeypatch):
    data, keys, frame, plaintext = vector()
    monkeypatch.setattr("uniconn.secure.conn.time.time", lambda: data["timestamp"])
    wire = MemoryConn()
    sender = SecureConn(keys, True).bind(wire)
    await sender.write(plaintext)
    assert bytes(wire.data) == frame
    wire.data.extend(frame)
    receiver = SecureConn(keys, False).bind(wire)
    buf = bytearray(128)
    n = await receiver.read(buf)
    assert bytes(buf[:n]) == plaintext
    with pytest.raises(ValueError, match="counter"):
        await receiver.read(buf)


@pytest.mark.asyncio
async def test_tampered_tag_does_not_advance_counter():
    _, keys, frame, _ = vector()
    tampered = bytearray(frame)
    tampered[-1] ^= 1
    receiver = SecureConn(keys, False).bind(MemoryConn(tampered + frame))
    with pytest.raises(ValueError, match="tag mismatch"):
        await receiver.read(bytearray(128))
    assert await receiver.read(bytearray(128)) > 0


@pytest.mark.asyncio
async def test_concurrent_frame_io_is_serialized():
    _, keys, _, _ = vector()
    wire = MemoryConn()
    sender = SecureConn(keys, True).bind(wire)
    await asyncio.gather(sender.write(b"first"), sender.write(b"second"))
    receiver = SecureConn(keys, False).bind(wire)
    buffers = [bytearray(128), bytearray(128)]
    sizes = await asyncio.gather(*(receiver.read(buf) for buf in buffers))
    assert [bytes(buf[:n]) for buf, n in zip(buffers, sizes)] == [b"first", b"second"]


@pytest.mark.asyncio
async def test_close_does_not_write_to_the_peer():
    _, keys, _, _ = vector()
    wire = MemoryConn()
    conn = SecureConn(keys, True).bind(wire)
    await conn.close()
    await conn.close()
    assert wire.closed and wire.writes == 0
    with pytest.raises(ConnectionError):
        await conn.write(b"after close")

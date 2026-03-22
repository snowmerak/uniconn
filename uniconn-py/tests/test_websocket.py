"""Unit tests for uniconn WebSocket adapter (synchronous)."""

import threading
import time

from uniconn.websocket.listener import WsListener
from uniconn.websocket.dialer import WsDialer


def test_ws_echo():
    """WebSocket: dialer sends data, listener echoes back."""
    listener = WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    def server():
        conn = listener.accept()
        buf = bytearray(1024)
        n = conn.read(buf)
        conn.write(bytes(buf[:n]))

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = WsDialer()
    conn = dialer.dial(f"ws://127.0.0.1:{port}")

    test_data = b"hello, uniconn Python WebSocket!"
    conn.write(test_data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == test_data

    conn.close()
    t.join(timeout=5)
    listener.close()


def test_ws_large_payload():
    """WebSocket: 64KB payload echo."""
    listener = WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    data = bytes(range(256)) * 256  # 64KB

    def server():
        conn = listener.accept()
        buf = bytearray(1024)
        received = bytearray()
        while len(received) < len(data):
            n = conn.read(buf)
            if n == 0:
                break
            received.extend(buf[:n])
        conn.write(bytes(received))

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = WsDialer()
    conn = dialer.dial(f"ws://127.0.0.1:{port}")
    conn.write(data)

    received = bytearray()
    buf = bytearray(4096)
    while len(received) < len(data):
        n = conn.read(buf)
        if n == 0:
            break
        received.extend(buf[:n])

    assert bytes(received) == data

    conn.close()
    t.join(timeout=5)
    listener.close()


def test_ws_multiple_messages():
    """WebSocket: multiple messages in sequence."""
    listener = WsListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    messages = [b"msg1", b"message two", b"third message!!!"]

    def server():
        conn = listener.accept()
        for _ in messages:
            buf = bytearray(256)
            n = conn.read(buf)
            conn.write(bytes(buf[:n]))

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = WsDialer()
    conn = dialer.dial(f"ws://127.0.0.1:{port}")

    for msg in messages:
        conn.write(msg)
        buf = bytearray(256)
        n = conn.read(buf)
        assert buf[:n] == msg

    conn.close()
    t.join(timeout=5)
    listener.close()

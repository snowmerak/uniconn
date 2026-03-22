"""Unit tests for uniconn TCP adapter (synchronous)."""

import threading
import time

from uniconn.tcp.listener import TcpListener
from uniconn.tcp.dialer import TcpDialer


def test_tcp_echo():
    """TCP: dialer sends data, listener echoes back."""
    listener = TcpListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    def server():
        conn = listener.accept()
        buf = bytearray(1024)
        n = conn.read(buf)
        conn.write(bytes(buf[:n]))
        conn.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = TcpDialer()
    conn = dialer.dial(f"127.0.0.1:{port}")

    test_data = b"hello, uniconn Python TCP!"
    conn.write(test_data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == test_data

    conn.close()
    t.join(timeout=5)
    listener.close()


def test_tcp_large_payload():
    """TCP: 64KB payload echo."""
    listener = TcpListener.bind("127.0.0.1", 0)
    port = int(listener.addr().address.split(":")[1])

    data = bytes(range(256)) * 256  # 64KB

    def server():
        conn = listener.accept()
        received = bytearray()
        buf = bytearray(4096)
        while len(received) < len(data):
            n = conn.read(buf)
            if n == 0:
                break
            received.extend(buf[:n])
        conn.write(bytes(received))
        conn.close()

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = TcpDialer()
    conn = dialer.dial(f"127.0.0.1:{port}")
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

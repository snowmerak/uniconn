"""Unit tests for uniconn KCP adapter (synchronous)."""

import threading
import time

from uniconn.kcp import KcpListener, KcpDialer


def test_kcp_echo():
    """KCP: dialer sends data, listener echoes back."""
    listener = KcpListener.bind("127.0.0.1", 19200, conv_id=1)

    def server():
        conn = listener.accept()
        buf = bytearray(1024)
        n = conn.read(buf)
        conn.write(bytes(buf[:n]))

    t = threading.Thread(target=server, daemon=True)
    t.start()

    dialer = KcpDialer(conv_id=1)
    conn = dialer.dial("127.0.0.1:19200")

    time.sleep(0.1)  # Let KCP handshake settle.

    test_data = b"hello, uniconn Python KCP!"
    conn.write(test_data)

    buf = bytearray(1024)
    n = conn.read(buf)
    assert buf[:n] == test_data

    conn.close()
    t.join(timeout=10)
    listener.close()

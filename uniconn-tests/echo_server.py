"""Python echo server for cross-language integration tests.

Spawned by pytest fixtures to act as server for Go/Node clients.

Usage: python echo_server.py <protocol> <port>
Protocols: tcp, ws

Echoes data back and prints "READY" to stdout when listening.
"""

import sys
import os
import threading

# Add uniconn-py to path.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "uniconn-py"))

from uniconn.tcp.listener import TcpListener
from uniconn.websocket.listener import WsListener


def echo_handler(conn):
    """Echo data back until connection closes."""
    try:
        buf = bytearray(256 * 1024)  # 256KB buffer for large payloads
        while True:
            n = conn.read(buf)
            if n == 0:
                break
            conn.write(bytes(buf[:n]))
    except Exception:
        pass
    finally:
        conn.close()


def run_tcp_server(port: int):
    listener = TcpListener.bind("127.0.0.1", port)
    actual_port = int(listener.addr().address.split(":")[1])
    print(f"READY:{actual_port}", flush=True)

    while True:
        try:
            conn = listener.accept()
            t = threading.Thread(target=echo_handler, args=(conn,), daemon=True)
            t.start()
        except Exception:
            break


def run_ws_server(port: int):
    listener = WsListener.bind("127.0.0.1", port)
    actual_port = int(listener.addr().address.split(":")[1])
    print(f"READY:{actual_port}", flush=True)

    while True:
        try:
            conn = listener.accept()
            t = threading.Thread(target=echo_handler, args=(conn,), daemon=True)
            t.start()
        except Exception:
            break


if __name__ == "__main__":
    protocol = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if protocol == "tcp":
        run_tcp_server(port)
    elif protocol == "ws":
        run_ws_server(port)
    else:
        print(f"Unknown protocol: {protocol}", file=sys.stderr)
        sys.exit(1)

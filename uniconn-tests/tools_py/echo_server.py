"""Python echo server (async) for cross-language integration tests.

Usage: python echo_server.py <protocol> [port]
Protocols: tcp, ws

Prints "READY:<port>" when listening.
"""

import asyncio
import sys

from uniconn.tcp.listener import TcpListener
from uniconn.websocket.listener import WsListener


async def echo_handler(conn):
    """Echo data back until connection closes."""
    try:
        buf = bytearray(256 * 1024)  # 256KB buffer
        while True:
            n = await conn.read(buf)
            if n == 0:
                break
            await conn.write(bytes(buf[:n]))
    except Exception:
        pass
    finally:
        await conn.close()


async def main():
    protocol = sys.argv[1] if len(sys.argv) > 1 else "tcp"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    if protocol == "tcp":
        listener = await TcpListener.bind("127.0.0.1", port)
    elif protocol == "ws":
        listener = await WsListener.bind("127.0.0.1", port)
    else:
        print(f"Unknown protocol: {protocol}", file=sys.stderr)
        sys.exit(1)

    actual_port = int(listener.addr().address.split(":")[1])
    print(f"READY:{actual_port}", flush=True)

    # Accept connections and echo.
    while True:
        conn = await listener.accept()
        asyncio.create_task(echo_handler(conn))


if __name__ == "__main__":
    asyncio.run(main())

import argparse
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "uniconn-py"))

from uniconn.secure.identity import Identity
from uniconn.p2p.node import Node, DefaultNodeConfig
from uniconn.tcp.dialer import TcpDialer
from uniconn.websocket.dialer import WsDialer
# KCP not implemented natively in Python client yet, fallback to TCP/WS

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--relay", required=True)
    parser.add_argument("--relay-fp", default="")
    parser.add_argument("--proto", default="tcp")
    parser.add_argument("--role", default="responder")
    args = parser.parse_args()

    if args.proto == "ws":
        dialer = WsDialer()
        if not args.relay.startswith("ws"):
            args.relay = f"ws://{args.relay}"
    else:
        dialer = TcpDialer()

    identity = Identity.generate()
    node = Node(DefaultNodeConfig, identity, dialer)

    fp_bytes = bytes(64)
    if args.relay_fp:
        fp_bytes = bytes.fromhex(args.relay_fp)

    await node.connect_relay(args.relay, fp_bytes)

    info = {
        "event": "connected",
        "fingerprint": identity.fingerprint().hex()
    }
    print(json.dumps(info))
    sys.stdout.flush()

    if args.role == "responder":
        conn = await node.accept()
        buf = bytearray(1024)
        n = await conn.read(buf)
        msg = buf[:n].decode('utf-8')
        print(json.dumps({"event": "msg_received", "data": msg}))
        sys.stdout.flush()
        await conn.write(b"PONG_FROM_PY")
    else:
        loop = asyncio.get_event_loop()
        target_hex = await loop.run_in_executor(None, sys.stdin.readline)
        target_hex = target_hex.strip()

        target_bytes = bytes.fromhex(target_hex)
        conn = await node.dial_peer(target_bytes)
        await conn.write(b"PING_FROM_PY")
        
        buf = bytearray(1024)
        n = await conn.read(buf)
        msg = buf[:n].decode('utf-8')
        print(json.dumps({"event": "msg_received", "data": msg}))
        sys.stdout.flush()

if __name__ == "__main__":
    asyncio.run(main())

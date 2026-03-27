import asyncio
import json
from dataclasses import dataclass
from typing import Callable, Optional

from uniconn.conn import Conn, Dialer
from uniconn.secure.identity import Identity
from uniconn.secure.handshake import handshake_initiator, handshake_responder
from uniconn.secure.conn import SecureConn

from .protocol import (
    MsgType, Envelope, AnnouncePayload, RelayReqPayload, 
    RelayAckPayload, IncomingRelayPayload, AcceptRelayPayload
)

VerifyFn = Callable[[bytes, bytes, bytes], bool]

def bytes_to_hex(b: bytes) -> str:
    return b.hex()

def hex_to_bytes(h: str) -> bytes:
    return bytes.fromhex(h)

async def read_envelope(conn: Conn) -> Envelope:
    line = bytearray()
    buf = bytearray(1)
    while True:
        n = await conn.read(buf)
        if n == 0:
            raise ConnectionError("connection closed by peer")
        if buf[0] == ord(b'\n'):
            break
        line.append(buf[0])
    return json.loads(line.decode('utf-8'))

async def write_envelope(conn: Conn, msg_type: str, payload: dict) -> int:
    env = {"type": msg_type, "payload": payload}
    data = (json.dumps(env) + '\n').encode('utf-8')
    return await conn.write(data)

@dataclass
class NodeConfig:
    pass

DefaultNodeConfig = NodeConfig()

class Node:
    def __init__(self, config: NodeConfig, identity: Identity, dialer: Dialer, verify_fn: Optional[VerifyFn] = None):
        self.config = config
        self.identity = identity
        self.verify_fn = verify_fn
        self.dialer = dialer
        
        self.relay_addr: str = ""
        self.relay_fp: bytes = b""
        self.control_conn: Optional[SecureConn] = None
        self.incoming_queue: asyncio.Queue[SecureConn] = asyncio.Queue()

    async def connect_relay(self, relay_addr: str, relay_fp: bytes) -> None:
        """Connect to a Relay Server to establish a persistent control channel."""
        raw_conn = await self.dialer.dial(relay_addr)
        sec_conn = await handshake_initiator(raw_conn, self.identity, relay_fp, self.verify_fn)

        self.relay_addr = relay_addr
        self.relay_fp = relay_fp
        self.control_conn = sec_conn

        announce: AnnouncePayload = {
            "fingerprint": bytes_to_hex(self.identity.fingerprint()),
            "direct_addresses": []
        }
        await write_envelope(sec_conn, MsgType.ANNOUNCE, announce)

        # Start control loop in background
        asyncio.create_task(self._read_control_loop(sec_conn))

    async def _read_control_loop(self, sc: SecureConn) -> None:
        try:
            while True:
                env = await read_envelope(sc)
                if env["type"] == MsgType.INCOMING_RELAY:
                    payload: IncomingRelayPayload = env["payload"]
                    asyncio.create_task(
                        self._accept_relay_proxy(payload["session_token"], payload["requester_fingerprint"])
                    )
        except Exception as e:
            # Control connection lost
            pass

    async def _accept_relay_proxy(self, token: str, requester_hex: str) -> None:
        try:
            if not self.relay_addr or not self.relay_fp:
                return

            # 1. Dial Relay
            raw_conn = await self.dialer.dial(self.relay_addr)
            sc = await handshake_initiator(raw_conn, self.identity, self.relay_fp, self.verify_fn)

            # 2. Accept token
            accept_msg: AcceptRelayPayload = {"session_token": token}
            await write_envelope(sc, MsgType.ACCEPT_RELAY, accept_msg)

            # 3. Handle Nested E2EE (Responder)
            requester_fp = hex_to_bytes(requester_hex)
            final_conn = await handshake_responder(sc, self.identity, requester_fp, self.verify_fn)
            
            await self.incoming_queue.put(final_conn)
        except Exception:
            pass

    async def dial_peer(self, peer_fp: bytes) -> SecureConn:
        """Dial a remote peer through the Relay network."""
        if not self.relay_addr or not self.relay_fp:
            raise Exception("Must connect to relay before dialing peers")

        # 1. Dial Relay
        raw_conn = await self.dialer.dial(self.relay_addr)
        sc = await handshake_initiator(raw_conn, self.identity, self.relay_fp, self.verify_fn)

        # 2. Request Routing
        req_msg: RelayReqPayload = {"target_fingerprint": bytes_to_hex(peer_fp)}
        await write_envelope(sc, MsgType.RELAY_REQ, req_msg)

        # Wait for Ack
        ack_env = await read_envelope(sc)
        if ack_env["type"] != MsgType.RELAY_ACK:
            await sc.close()
            raise Exception(f"expected RELAY_ACK, got {ack_env['type']}")

        ack: RelayAckPayload = ack_env["payload"]
        if not ack.get("success", False):
            await sc.close()
            reason = ack.get("reason", "unknown")
            raise Exception(f"relay proxy failed: {reason}")

        # 3. Handle Nested E2EE (Initiator)
        final_conn = await handshake_initiator(sc, self.identity, peer_fp, self.verify_fn)
        return final_conn

    async def accept(self) -> SecureConn:
        """Wait for and accept incoming P2P connections."""
        return await self.incoming_queue.get()

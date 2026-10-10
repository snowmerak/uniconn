import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Callable

from uniconn.conn import Conn, Dialer
from uniconn.secure.identity import Identity
from uniconn.secure.handshake import handshake_initiator, handshake_responder
from uniconn.secure.conn import SecureConn
from .protocol import MsgType, Envelope

VerifyFn = Callable[[bytes, bytes, bytes], bool]

async def read_envelope(conn: Conn) -> Envelope:
    line = bytearray()
    buf = bytearray(1)
    while len(line) < 64 * 1024:
        n = await conn.read(buf)
        if n == 0:
            raise ConnectionError("connection closed by peer")
        if buf[0] == 10:
            return json.loads(line.decode("utf-8"))
        line.append(buf[0])
    raise ValueError("control message too large")

async def write_envelope(conn: Conn, msg_type: str, payload: dict) -> int:
    data = (json.dumps({"type": msg_type, "payload": payload}) + "\n").encode("utf-8")
    return await conn.write(data)

@dataclass
class NodeConfig:
    setup_timeout: float = 10.0

DefaultNodeConfig = NodeConfig()

@dataclass
class _Session:
    addr: str
    fp: bytes
    control: SecureConn | None = None
    error: Exception | None = None
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    pending: set[Conn] = field(default_factory=set)
    tasks: set[asyncio.Task] = field(default_factory=set)
    incoming: asyncio.Queue = field(default_factory=asyncio.Queue)

class Node:
    """Owns relay control, setup tasks and peers not yet returned by accept()."""
    def __init__(self, config: NodeConfig, identity: Identity, dialer: Dialer, verify_fn: VerifyFn | None = None):
        self.config = config
        self.identity = identity
        self.dialer = dialer
        self.verify_fn = verify_fn
        self._session: _Session | None = None
        self._closed = False
        self._connect_lock = asyncio.Lock()
        # Retain the existing public connection metadata.
        self.relay_addr = ""
        self.relay_fp = b""
        self.control_conn: SecureConn | None = None

    def _spawn(self, session: _Session, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        session.tasks.add(task)
        task.add_done_callback(session.tasks.discard)
        return task

    async def _stop_session(self, session: _Session, reason: Exception) -> None:
        if session.error is not None:
            return
        session.error = reason
        session.ended.set()
        current = asyncio.current_task()
        tasks = [task for task in session.tasks if task is not current]
        for task in tasks:
            task.cancel()
        connections = list(session.pending)
        session.pending.clear()
        await asyncio.gather(*(conn.close() for conn in connections), return_exceptions=True)
        await asyncio.gather(*tasks, return_exceptions=True)
        while not session.incoming.empty():
            session.incoming.get_nowait()
        if self._session is session:
            self.control_conn = None

    def _current_session(self) -> _Session:
        if self._closed:
            raise ConnectionError("node closed")
        session = self._session
        if session is not None and session.error is not None:
            raise ConnectionError(str(session.error)) from session.error
        if session is None or session.control is None:
            raise ConnectionError("must connect to relay before using peers")
        return session

    async def _setup(self, session: _Session, operation):
        async def run():
            raw = None
            try:
                if session.ended.is_set():
                    raise ConnectionError(str(session.error))
                raw = await self.dialer.dial(session.addr)
                session.pending.add(raw)
                if session.ended.is_set():
                    raise ConnectionError(str(session.error))
                result = await operation(raw)
                if session.ended.is_set():
                    raise ConnectionError(str(session.error))
                return raw, result
            except BaseException:
                if raw is not None:
                    session.pending.discard(raw)
                    await raw.close()
                raise
        task = self._spawn(session, run())
        try:
            return await asyncio.wait_for(task, timeout=self.config.setup_timeout)
        except asyncio.CancelledError:
            if session.error is not None:
                raise ConnectionError(str(session.error)) from session.error
            raise

    async def connect_relay(self, relay_addr: str, relay_fp: bytes) -> None:
        if len(relay_fp) != 64:
            raise ValueError("relay fingerprint must be 64 bytes")
        async with self._connect_lock:
            if self._closed:
                raise ConnectionError("node closed")
            if self._session is not None:
                await self._stop_session(self._session, ConnectionError("relay session replaced"))
            session = _Session(relay_addr, relay_fp)
            self._session = session
            async def connect(raw):
                sc = await handshake_initiator(raw, self.identity, relay_fp, self.verify_fn)
                await write_envelope(sc, MsgType.ANNOUNCE, {
                    "fingerprint": self.identity.fingerprint().hex(), "direct_addresses": []})
                return sc
            try:
                _, sc = await self._setup(session, connect)
            except BaseException:
                await self._stop_session(session, ConnectionError("relay setup failed"))
                raise
            session.control = sc
            self.relay_addr, self.relay_fp, self.control_conn = relay_addr, relay_fp, sc
            self._spawn(session, self._read_control_loop(session))

    async def _read_control_loop(self, session: _Session) -> None:
        try:
            while True:
                env = await read_envelope(session.control)
                if env["type"] == MsgType.INCOMING_RELAY:
                    payload = env["payload"]
                    self._spawn(session, self._accept_relay_proxy(session, payload))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._stop_session(session, ConnectionError(f"relay control connection lost: {error}"))

    async def _accept_relay_proxy(self, session: _Session, payload: dict) -> None:
        try:
            requester_fp = bytes.fromhex(payload["requester_fingerprint"])
            if len(requester_fp) != 64:
                raise ValueError("requester fingerprint must be 64 bytes")
            async def accept(raw):
                sc = await handshake_initiator(raw, self.identity, session.fp, self.verify_fn)
                await write_envelope(sc, MsgType.ACCEPT_RELAY, {"session_token": payload["session_token"]})
                return await handshake_responder(sc, self.identity, requester_fp, self.verify_fn)
            raw, conn = await self._setup(session, accept)
            session.incoming.put_nowait((raw, conn))
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).exception("failed to accept relay proxy")

    async def dial_peer(self, peer_fp: bytes) -> SecureConn:
        if len(peer_fp) != 64:
            raise ValueError("peer fingerprint must be 64 bytes")
        session = self._current_session()
        async def dial(raw):
            sc = await handshake_initiator(raw, self.identity, session.fp, self.verify_fn)
            await write_envelope(sc, MsgType.RELAY_REQ, {"target_fingerprint": peer_fp.hex()})
            ack = await read_envelope(sc)
            if ack["type"] != MsgType.RELAY_ACK:
                raise ConnectionError(f"expected RELAY_ACK, got {ack['type']}")
            if not ack["payload"].get("success", False):
                raise ConnectionError(f"relay proxy failed: {ack['payload'].get('reason', 'unknown')}")
            return await handshake_initiator(sc, self.identity, peer_fp, self.verify_fn)
        raw, conn = await self._setup(session, dial)
        if session.error is not None:
            await conn.close()
            raise ConnectionError(str(session.error)) from session.error
        session.pending.discard(raw)
        return conn

    async def accept(self) -> SecureConn:
        session = self._current_session()
        incoming = asyncio.create_task(session.incoming.get())
        ended = asyncio.create_task(session.ended.wait())
        try:
            try:
                await asyncio.wait([incoming, ended], return_when=asyncio.FIRST_COMPLETED)
            finally:
                incoming.cancel()
                ended.cancel()
                await asyncio.gather(incoming, ended, return_exceptions=True)
            if session.error is not None:
                raise ConnectionError(str(session.error)) from session.error
            raw, conn = incoming.result()
            session.pending.discard(raw)
            return conn
        except BaseException:
            if incoming.done() and not incoming.cancelled():
                raw, conn = incoming.result()
                session.pending.discard(raw)
                await conn.close()
            raise

    async def close(self) -> None:
        """Cancel owned work; peers already returned to callers stay caller-owned."""
        self._closed = True
        if self._session is not None:
            await self._stop_session(self._session, ConnectionError("node closed"))

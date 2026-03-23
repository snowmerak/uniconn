"""
Multi-protocol auto-selection with negotiate endpoint.

Matches the Go `multi` package wire format:
GET /negotiate → { "protocols": [{"name": "...", "address": "..."}, ...] }
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Literal

from ..conn import Conn, Dialer, Listener, Addr

# Protocol type.
Protocol = Literal["webtransport", "quic", "websocket", "kcp", "tcp"]

# Default protocol priority: higher-performance first.
DEFAULT_PRIORITY: list[Protocol] = [
    "webtransport",
    "quic",
    "websocket",
    "kcp",
    "tcp",
]

DEFAULT_DIAL_TIMEOUT = 5.0  # seconds


@dataclass
class ProtocolEntry:
    """A single protocol entry in the negotiate response."""
    name: Protocol
    address: str


@dataclass
class NegotiateResponse:
    """JSON response from the /negotiate endpoint."""
    protocols: list[ProtocolEntry]

    def to_json(self) -> str:
        return json.dumps({
            "protocols": [
                {"name": p.name, "address": p.address}
                for p in self.protocols
            ]
        })

    @classmethod
    def from_json(cls, data: str) -> "NegotiateResponse":
        obj = json.loads(data)
        return cls(
            protocols=[
                ProtocolEntry(name=p["name"], address=p["address"])
                for p in obj["protocols"]
            ]
        )


# ───── MultiDialer ──────────────────────────────────────────


@dataclass
class MultiDialerConfig:
    """Configuration for MultiDialer."""
    negotiate_url: str
    dialers: dict[Protocol, Dialer]
    priority: list[Protocol] = field(default_factory=lambda: list(DEFAULT_PRIORITY))
    dial_timeout: float = DEFAULT_DIAL_TIMEOUT


class MultiDialer:
    """Negotiate with the server and connect via the best available protocol."""

    def __init__(self, config: MultiDialerConfig) -> None:
        self._config = config

    async def dial(self) -> tuple[Conn, Protocol]:
        """Negotiate and dial the best available protocol.

        Returns:
            Tuple of (connection, protocol_used).

        Raises:
            RuntimeError: If no compatible protocol is found or all fail.
        """
        import aiohttp

        # 1. Fetch negotiate response.
        async with aiohttp.ClientSession() as session:
            async with session.get(self._config.negotiate_url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"negotiate: HTTP {resp.status}")
                body = await resp.text()

        neg = NegotiateResponse.from_json(body)
        server_map: dict[Protocol, str] = {
            p.name: p.address for p in neg.protocols
        }

        # 2. Try protocols in priority order.
        last_error: Exception | None = None

        for proto in self._config.priority:
            address = server_map.get(proto)
            if address is None:
                continue

            dialer = self._config.dialers.get(proto)
            if dialer is None:
                continue

            try:
                conn = await asyncio.wait_for(
                    dialer.dial(address),
                    timeout=self._config.dial_timeout,
                )
                return conn, proto
            except Exception as e:
                last_error = RuntimeError(f"[{proto}] {e}")

        if last_error:
            raise RuntimeError(f"all protocols failed, last: {last_error}")
        raise RuntimeError("no compatible protocol found")


# ───── MultiListener ────────────────────────────────────────


@dataclass
class TransportConfig:
    """Configuration for a single transport in MultiListener."""
    protocol: Protocol
    address: str
    listener: Listener


@dataclass
class AcceptResult:
    """A connection along with the protocol it arrived on."""
    conn: Conn
    protocol: Protocol


class MultiListener:
    """Fan-in connections from multiple protocol listeners."""

    def __init__(self, transports: list[TransportConfig]) -> None:
        if not transports:
            raise ValueError("multi: at least one transport is required")
        self._transports = transports
        self._queue: asyncio.Queue[AcceptResult] = asyncio.Queue()
        self._closed = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start accept loops for all transports."""
        for t in self._transports:
            task = asyncio.create_task(self._accept_loop(t))
            self._tasks.append(task)

    def get_negotiate_response(self) -> NegotiateResponse:
        """Build the negotiate response from configured transports."""
        return NegotiateResponse(
            protocols=[
                ProtocolEntry(name=t.protocol, address=t.address)
                for t in self._transports
            ]
        )

    async def accept(self) -> Conn:
        """Accept the next connection from any protocol."""
        result = await self.accept_with()
        return result.conn

    async def accept_with(self) -> AcceptResult:
        """Accept the next connection along with its protocol."""
        if self._closed:
            raise RuntimeError("listener closed")
        return await self._queue.get()

    async def close(self) -> None:
        """Close all underlying listeners."""
        self._closed = True
        for task in self._tasks:
            task.cancel()
        for t in self._transports:
            await t.listener.close()

    async def _accept_loop(self, t: TransportConfig) -> None:
        while not self._closed:
            try:
                conn = await t.listener.accept()
                await self._queue.put(AcceptResult(conn=conn, protocol=t.protocol))
            except asyncio.CancelledError:
                break
            except Exception:
                if not self._closed:
                    break

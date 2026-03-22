"""
Core connection interfaces for uniconn.

All protocol adapters implement these interfaces so that application code
can work with any transport transparently.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class Addr:
    """Network address descriptor."""
    network: str  # "tcp", "websocket", "kcp", etc.
    address: str


class Conn(abc.ABC):
    """
    Universal connection interface, modeled after Go's net.Conn.

    Each protocol adapter implements this so that application code can
    read, write, and close connections identically regardless of transport.
    """

    @abc.abstractmethod
    async def read(self, buf: bytearray) -> int:
        """Read data into buffer. Returns number of bytes read. 0 = EOF."""
        ...

    @abc.abstractmethod
    async def write(self, data: bytes) -> int:
        """Write data. Returns number of bytes written."""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the connection."""
        ...

    @abc.abstractmethod
    def local_addr(self) -> Addr | None:
        """Return local address, if available."""
        ...

    @abc.abstractmethod
    def remote_addr(self) -> Addr | None:
        """Return remote address, if available."""
        ...


class Listener(abc.ABC):
    """Server-side listener interface."""

    @abc.abstractmethod
    async def accept(self) -> Conn:
        """Accept and return the next incoming connection."""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Stop listening."""
        ...

    @abc.abstractmethod
    def addr(self) -> Addr:
        """Return bound address."""
        ...


class Dialer(abc.ABC):
    """Client-side dialer interface."""

    @abc.abstractmethod
    async def dial(self, address: str) -> Conn:
        """Establish a connection to the given address."""
        ...

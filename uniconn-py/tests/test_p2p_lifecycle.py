import asyncio

import pytest

import uniconn.p2p.node as node_module
from uniconn.p2p.node import Node, NodeConfig
from uniconn.secure.identity import Identity


class FakeConn:
    def __init__(self):
        self.ended = asyncio.Event()
        self.closed = False

    async def read(self, buf):
        await self.ended.wait()
        return 0

    async def write(self, data):
        return len(data)

    async def close(self):
        self.closed = True
        self.ended.set()


class FakeDialer:
    def __init__(self):
        self.connections = []

    async def dial(self, address):
        conn = FakeConn()
        self.connections.append(conn)
        return conn


async def passthrough(conn, *args):
    return conn


@pytest.mark.asyncio
async def test_relay_disconnect_wakes_every_accept_caller(monkeypatch):
    monkeypatch.setattr(node_module, "handshake_initiator", passthrough)
    dialer = FakeDialer()
    node = Node(NodeConfig(), Identity.generate(), dialer)
    await node.connect_relay("mock", bytes(64))
    waiters = [asyncio.create_task(node.accept()) for _ in range(3)]
    await asyncio.sleep(0)
    dialer.connections[0].ended.set()
    results = await asyncio.wait_for(asyncio.gather(*waiters, return_exceptions=True), 1)
    assert all(isinstance(result, ConnectionError) for result in results)
    assert dialer.connections[0].closed
    await node.close()


@pytest.mark.asyncio
async def test_stalled_setup_times_out_and_closes_socket(monkeypatch):
    async def stalled(*args):
        await asyncio.Future()
    monkeypatch.setattr(node_module, "handshake_initiator", stalled)
    dialer = FakeDialer()
    node = Node(NodeConfig(setup_timeout=0.02), Identity.generate(), dialer)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(node.connect_relay("mock", bytes(64)), 1)
    assert dialer.connections[0].closed
    await node.close()


@pytest.mark.asyncio
async def test_reconnect_closes_previous_control_connection(monkeypatch):
    monkeypatch.setattr(node_module, "handshake_initiator", passthrough)
    dialer = FakeDialer()
    node = Node(NodeConfig(), Identity.generate(), dialer)
    await node.connect_relay("first", bytes(64))
    pending = asyncio.create_task(node.accept())
    await asyncio.sleep(0)
    await node.connect_relay("second", bytes(64))
    with pytest.raises(ConnectionError):
        await pending
    assert dialer.connections[0].closed
    await node.close()
    await node.close()
    assert all(conn.closed for conn in dialer.connections)


@pytest.mark.asyncio
async def test_cancelling_setup_closes_socket(monkeypatch):
    entered = asyncio.Event()
    async def stalled(*args):
        entered.set()
        await asyncio.Future()
    monkeypatch.setattr(node_module, "handshake_initiator", stalled)
    dialer = FakeDialer()
    node = Node(NodeConfig(), Identity.generate(), dialer)
    task = asyncio.create_task(node.connect_relay("mock", bytes(64)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert dialer.connections[0].closed
    await node.close()


@pytest.mark.asyncio
async def test_cancelled_accept_closes_a_peer_already_taken_from_queue(monkeypatch):
    monkeypatch.setattr(node_module, "handshake_initiator", passthrough)
    node = Node(NodeConfig(), Identity.generate(), FakeDialer())
    await node.connect_relay("mock", bytes(64))
    peer = FakeConn()
    node._session.pending.add(peer)
    node._session.incoming.put_nowait((peer, peer))
    task = asyncio.create_task(node.accept())
    while not node._session.incoming.empty():
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert peer.closed
    assert peer not in node._session.pending
    await node.close()

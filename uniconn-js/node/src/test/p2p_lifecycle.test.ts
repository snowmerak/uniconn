import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as net from 'node:net';
import { Node, handshakeResponder, type IConn, type SecureConn } from '@uniconn/core';
import { NodeIdentity, nodeVerify } from '../secure/identity.js';
import { TcpConn } from '../tcp/conn.js';
import { TcpDialer } from '../tcp/dialer.js';
import { Node as PublicNode } from '@uniconn/node/p2p';
import { NodeIdentity as PublicIdentity } from '@uniconn/node/secure/identity';
import { TcpDialer as PublicTcpDialer } from '@uniconn/node/tcp/dialer';

test('documented TCP package exports load without the native KCP adapter', () => {
  assert.equal(PublicNode, Node);
  assert.equal(PublicIdentity, NodeIdentity);
  assert.equal(PublicTcpDialer, TcpDialer);
});

test('stalled relay setup times out and closes the raw transport', { timeout: 2000 }, async () => {
  let closed = false;
  let reader: ((n: number) => void) | undefined;
  const raw: IConn = {
    read: () => new Promise(resolve => { if (closed) resolve(0); else reader = resolve; }),
    write: async data => data.length,
    close: async () => { closed = true; reader?.(0); },
    localAddr: () => ({ network: 'mock', address: 'local' }),
    remoteAddr: () => ({ network: 'mock', address: 'remote' }),
    setDeadline() {}, setReadDeadline() {}, setWriteDeadline() {},
  };
  const node = new Node({ setupTimeoutMs: 20 }, NodeIdentity.generate(), nodeVerify, { dial: async () => raw });
  await assert.rejects(node.connectRelay('mock', new Uint8Array(64)), /timed out/);
  assert.equal(closed, true);
  await node.close();
});

test('relay disconnect rejects every accept caller', { timeout: 3000 }, async t => {
  const clientID = NodeIdentity.generate(), relayID = NodeIdentity.generate();
  let serverSocket: net.Socket | undefined;
  let ready!: (conn: SecureConn) => void;
  let fail!: (error: unknown) => void;
  const handshake = new Promise<SecureConn>((resolve, reject) => { ready = resolve; fail = reject; });
  const server = net.createServer(socket => {
    serverSocket = socket;
    void handshakeResponder(new TcpConn(socket), relayID, clientID.fingerprint(), nodeVerify).then(ready, fail);
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const node = new Node({}, clientID, nodeVerify, new TcpDialer());
  t.after(async () => { await node.close(); serverSocket?.destroy(); await new Promise<void>(resolve => server.close(() => resolve())); });
  await node.connectRelay(`127.0.0.1:${(server.address() as net.AddressInfo).port}`, relayID.fingerprint());
  await handshake;
  const waiters = [node.accept(), node.accept(), node.accept()].map(promise => assert.rejects(promise, /connection lost/));
  serverSocket!.destroy();
  await Promise.all(waiters);
});

test('caller abort cancels a handshake already in progress', { timeout: 2000 }, async () => {
  let closed = false;
  let entered!: () => void;
  let reader: ((n: number) => void) | undefined;
  const started = new Promise<void>(resolve => { entered = resolve; });
  const raw: IConn = {
    read: () => new Promise(resolve => { if (closed) resolve(0); else reader = resolve; }),
    write: async data => { entered(); return data.length; },
    close: async () => { closed = true; reader?.(0); },
    localAddr: () => ({ network: 'mock', address: 'local' }),
    remoteAddr: () => ({ network: 'mock', address: 'remote' }),
    setDeadline() {}, setReadDeadline() {}, setWriteDeadline() {},
  };
  const controller = new AbortController();
  const node = new Node({}, NodeIdentity.generate(), nodeVerify, { dial: async () => raw });
  const result = assert.rejects(node.connectRelay('mock', new Uint8Array(64), { signal: controller.signal }), /aborted/);
  await started; controller.abort(); await result;
  assert.equal(closed, true); await node.close();
});

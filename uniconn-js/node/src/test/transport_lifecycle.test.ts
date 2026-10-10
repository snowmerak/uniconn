import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { ReadQueue } from '@uniconn/core';
import { TcpConn } from '../tcp/conn.js';
import type { Socket } from 'node:net';
import { WsConn } from '../websocket/conn.js';

test('FIFO pending reads retain bytes and all finish at EOF', async () => {
  const queue = new ReadQueue();
  const a = new Uint8Array(2), b = new Uint8Array(2);
  const first = queue.read(a), second = queue.read(b), last = queue.read(new Uint8Array(1));
  queue.push(Uint8Array.of(1, 2, 3, 4)); queue.end();
  assert.deepEqual(await Promise.all([first, second, last]), [2, 2, 0]);
  assert.deepEqual([...a, ...b], [1, 2, 3, 4]);
});

test('transport failure rejects current and future reads', async () => {
  const queue = new ReadQueue();
  const pending = queue.read(new Uint8Array(1), 10);
  queue.fail(new Error('transport failed'));
  await assert.rejects(pending, /transport failed/);
  await assert.rejects(queue.read(new Uint8Array(1)), /transport failed/);
});

test('WebSocket local close rejects reads before a close event arrives', async () => {
  const ws = { binaryType: '', onmessage: null, onclose: null, onerror: null,
    send() {}, close() {} };
  const addr = { network: 'mock', address: 'local' };
  const conn = new WsConn(ws, addr, addr);
  const checked = assert.rejects(conn.read(new Uint8Array(1)), /closed/);
  await conn.close(); await checked;
});

test('timed out read does not discard data for the next reader', async () => {
  const queue = new ReadQueue();
  await assert.rejects(queue.read(new Uint8Array(1), 5), /timed out/);
  const buffer = new Uint8Array(1);
  const next = queue.read(buffer);
  queue.push(Uint8Array.of(42));
  assert.equal(await next, 1); assert.equal(buffer[0], 42);
});

test('TCP local close rejects every pending read', async () => {
  class FakeSocket extends EventEmitter { destroy() { this.emit('close'); } }
  const conn = new TcpConn(new FakeSocket() as unknown as Socket);
  const reads = [conn.read(new Uint8Array(1)), conn.read(new Uint8Array(1))];
  // Attach rejection observers before closing.
  const checked = reads.map(read => assert.rejects(read, /closed/));
  await conn.close(); await conn.close();
  await Promise.all(checked);
});

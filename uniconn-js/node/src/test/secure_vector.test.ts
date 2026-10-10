import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import type { IConn } from '@uniconn/core';
import { SecureConn } from '@uniconn/core';
import type { SessionKeys } from '@uniconn/core/secure/conn';

class MemoryConn implements IConn {
  data: number[] = [];
  closed = false;
  writes = 0;
  async read(buffer: Uint8Array): Promise<number> {
    await Promise.resolve();
    const n = Math.min(buffer.length, this.data.length, 3);
    buffer.set(this.data.splice(0, n));
    return n;
  }
  async write(data: Uint8Array): Promise<number> {
    this.writes++;
    const half = Math.floor(data.length / 2);
    this.data.push(...data.subarray(0, half));
    await Promise.resolve();
    this.data.push(...data.subarray(half));
    return data.length;
  }
  async close(): Promise<void> { this.closed = true; }
  localAddr() { return { network: 'mock', address: 'local' }; }
  remoteAddr() { return { network: 'mock', address: 'remote' }; }
  setDeadline() {} setReadDeadline() {} setWriteDeadline() {}
}

function vector() {
  const data = JSON.parse(readFileSync(new URL('../../../../uniconn-tests/vectors/secure-data-v1.json', import.meta.url), 'utf8'));
  const decode = (name: string) => Uint8Array.from(Buffer.from(data[name], 'hex'));
  const keys: SessionKeys = {
    initiatorKey: decode('initiator_key'), responderKey: decode('responder_key'),
    initiatorNoncePfx: decode('initiator_nonce_prefix'), responderNoncePfx: decode('responder_nonce_prefix'),
  };
  return { data, keys, frame: decode('frame'), plaintext: decode('plaintext') };
}

test('shared DATA vector and replay rejection', async () => {
  const { data, keys, frame, plaintext } = vector();
  const wire = new MemoryConn();
  const originalNow = Date.now;
  try {
    Date.now = () => data.timestamp * 1000;
    await new SecureConn(wire, keys, true).write(plaintext);
  } finally { Date.now = originalNow; }
  assert.deepEqual(Uint8Array.from(wire.data), frame);
  wire.data.push(...frame);
  const receiver = new SecureConn(wire, keys, false);
  const buf = new Uint8Array(128);
  const n = await receiver.read(buf);
  assert.deepEqual(buf.subarray(0, n), plaintext);
  await assert.rejects(receiver.read(buf), /counter/);
});

test('tampered tag does not advance receive counter', async () => {
  const { keys, frame } = vector();
  const tampered = frame.slice(); tampered[tampered.length - 1] ^= 1;
  const wire = new MemoryConn(); wire.data.push(...tampered, ...frame);
  const receiver = new SecureConn(wire, keys, false);
  await assert.rejects(receiver.read(new Uint8Array(128)), /tag mismatch/);
  assert.ok(await receiver.read(new Uint8Array(128)) > 0);
});

test('concurrent writes and reads preserve frame boundaries', async () => {
  const { keys } = vector();
  const wire = new MemoryConn();
  const sender = new SecureConn(wire, keys, true);
  await Promise.all([sender.write(Uint8Array.of(1)), sender.write(Uint8Array.of(2))]);
  const receiver = new SecureConn(wire, keys, false);
  const a = new Uint8Array(1), b = new Uint8Array(1);
  await Promise.all([receiver.read(a), receiver.read(b)]);
  assert.deepEqual([a[0], b[0]], [1, 2]);
});

test('secure close closes the transport without writing', async () => {
  const { keys } = vector();
  const wire = new MemoryConn();
  const conn = new SecureConn(wire, keys, true);
  await conn.close(); await conn.close();
  assert.equal(wire.closed, true); assert.equal(wire.writes, 0);
});

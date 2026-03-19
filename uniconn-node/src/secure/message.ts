import type { IConn } from "../conn.js";
import { MSG_HELLO, MSG_HELLO_REPLY, MSG_DATA, MSG_ERROR, MAX_MESSAGE_SIZE } from "./constants.js";

// ── Marshalling helpers (big-endian) ─────────────────────

function writeU32BE(buf: Uint8Array, offset: number, val: number): void {
  buf[offset] = (val >>> 24) & 0xff;
  buf[offset + 1] = (val >>> 16) & 0xff;
  buf[offset + 2] = (val >>> 8) & 0xff;
  buf[offset + 3] = val & 0xff;
}

function readU32BE(buf: Uint8Array, offset: number): number {
  return (
    ((buf[offset] << 24) |
      (buf[offset + 1] << 16) |
      (buf[offset + 2] << 8) |
      buf[offset + 3]) >>>
    0
  );
}

function writeU16BE(buf: Uint8Array, offset: number, val: number): void {
  buf[offset] = (val >>> 8) & 0xff;
  buf[offset + 1] = val & 0xff;
}

function readU16BE(buf: Uint8Array, offset: number): number {
  return (buf[offset] << 8) | buf[offset + 1];
}

function writeU64BE(buf: Uint8Array, offset: number, val: bigint): void {
  const hi = Number((val >> 32n) & 0xffffffffn);
  const lo = Number(val & 0xffffffffn);
  writeU32BE(buf, offset, hi);
  writeU32BE(buf, offset + 4, lo);
}

function readU64BE(buf: Uint8Array, offset: number): bigint {
  const hi = BigInt(readU32BE(buf, offset));
  const lo = BigInt(readU32BE(buf, offset + 4));
  return (hi << 32n) | lo;
}

// ── Frame I/O ────────────────────────────────────────────

/** Read exactly `n` bytes from an IConn. */
async function readExact(conn: IConn, n: number): Promise<Uint8Array> {
  const result = new Uint8Array(n);
  let offset = 0;
  while (offset < n) {
    const chunk = result.subarray(offset);
    const read = await conn.read(chunk);
    if (read === 0) throw new Error("unexpected EOF");
    offset += read;
  }
  return result;
}

/** Read a framed message: [4B len][body]. */
export async function readFrame(conn: IConn): Promise<Uint8Array> {
  const lenBuf = await readExact(conn, 4);
  const len = readU32BE(lenBuf, 0);
  if (len > MAX_MESSAGE_SIZE) throw new Error(`frame too large: ${len}`);
  return readExact(conn, len);
}

/** Write a framed message: [4B len][body]. */
export async function writeFrame(conn: IConn, body: Uint8Array): Promise<void> {
  const frame = new Uint8Array(4 + body.length);
  writeU32BE(frame, 0, body.length);
  frame.set(body, 4);
  await conn.write(frame);
}

// ── Hello message ────────────────────────────────────────

export interface HelloMsg {
  type: number;
  publicKey: Uint8Array;
  payload: Uint8Array; // ek (HELLO) or ct (HELLO_REPLY)
  signature: Uint8Array;
}

export function marshalHello(msg: HelloMsg): Uint8Array {
  const bodyLen =
    1 + 2 + msg.publicKey.length + 2 + msg.payload.length + 2 + msg.signature.length;
  const buf = new Uint8Array(bodyLen);
  let off = 0;
  buf[off++] = msg.type;

  writeU16BE(buf, off, msg.publicKey.length);
  off += 2;
  buf.set(msg.publicKey, off);
  off += msg.publicKey.length;

  writeU16BE(buf, off, msg.payload.length);
  off += 2;
  buf.set(msg.payload, off);
  off += msg.payload.length;

  writeU16BE(buf, off, msg.signature.length);
  off += 2;
  buf.set(msg.signature, off);

  return buf;
}

export function unmarshalHello(body: Uint8Array): HelloMsg {
  if (body.length < 1) throw new Error("empty message body");
  let off = 0;
  const type = body[off++];

  if (off + 2 > body.length) throw new Error("truncated pubkey length");
  const pkLen = readU16BE(body, off);
  off += 2;
  if (off + pkLen > body.length) throw new Error("truncated pubkey data");
  const publicKey = body.slice(off, off + pkLen);
  off += pkLen;

  if (off + 2 > body.length) throw new Error("truncated payload length");
  const plLen = readU16BE(body, off);
  off += 2;
  if (off + plLen > body.length) throw new Error("truncated payload data");
  const payload = body.slice(off, off + plLen);
  off += plLen;

  if (off + 2 > body.length) throw new Error("truncated sig length");
  const sigLen = readU16BE(body, off);
  off += 2;
  if (off + sigLen > body.length) throw new Error("truncated sig data");
  const signature = body.slice(off, off + sigLen);

  return { type, publicKey, payload, signature };
}

// ── Data message ─────────────────────────────────────────

export function marshalData(
  timestamp: number,
  counter: bigint,
  ciphertext: Uint8Array,
): Uint8Array {
  const bodyLen = 1 + 4 + 8 + ciphertext.length;
  const buf = new Uint8Array(bodyLen);
  buf[0] = MSG_DATA;
  writeU32BE(buf, 1, timestamp);
  writeU64BE(buf, 5, counter);
  buf.set(ciphertext, 13);
  return buf;
}

export interface DataMsg {
  timestamp: number;
  counter: bigint;
  ciphertext: Uint8Array;
}

export function unmarshalData(body: Uint8Array): DataMsg {
  if (body.length < 13) throw new Error("DATA message too short");
  return {
    timestamp: readU32BE(body, 1),
    counter: readU64BE(body, 5),
    ciphertext: body.slice(13),
  };
}

// ── Error message ────────────────────────────────────────

export function marshalError(reason: string): Uint8Array {
  const reasonBytes = new TextEncoder().encode(reason);
  const buf = new Uint8Array(1 + 2 + reasonBytes.length);
  buf[0] = MSG_ERROR;
  writeU16BE(buf, 1, reasonBytes.length);
  buf.set(reasonBytes, 3);
  return buf;
}

export { writeU32BE, readU32BE, writeU64BE, readU64BE };

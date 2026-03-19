import { XChaCha20Poly1305 } from "@stablelib/xchacha20poly1305";

import type { Addr, IConn } from "../conn.js";
import {
  NONCE_SIZE,
  NONCE_PREFIX_SIZE,
  TIMESTAMP_SIZE,
  TAG_SIZE,
  MSG_DATA,
  MSG_ERROR,
} from "./constants.js";
import { marshalData, marshalError, readFrame, writeFrame, writeU32BE, writeU64BE } from "./message.js";

export interface SessionKeys {
  initiatorKey: Uint8Array; // 32B
  responderKey: Uint8Array; // 32B
  initiatorNoncePfx: Uint8Array; // 12B
  responderNoncePfx: Uint8Array; // 12B
}

/**
 * SecureConn wraps an IConn with XChaCha20-Poly1305 encryption.
 * Implements IConn so it can be used transparently.
 */
export class SecureConn implements IConn {
  private inner: IConn;
  private sendCipher: XChaCha20Poly1305;
  private recvCipher: XChaCha20Poly1305;
  private sendNoncePfx: Uint8Array;
  private recvNoncePfx: Uint8Array;
  private sendCounter: bigint = 0n;
  private recvBuf: Uint8Array | null = null;
  private closed = false;

  constructor(inner: IConn, keys: SessionKeys, isInitiator: boolean) {
    this.inner = inner;

    if (isInitiator) {
      this.sendCipher = new XChaCha20Poly1305(keys.initiatorKey);
      this.recvCipher = new XChaCha20Poly1305(keys.responderKey);
      this.sendNoncePfx = keys.initiatorNoncePfx;
      this.recvNoncePfx = keys.responderNoncePfx;
    } else {
      this.sendCipher = new XChaCha20Poly1305(keys.responderKey);
      this.recvCipher = new XChaCha20Poly1305(keys.initiatorKey);
      this.sendNoncePfx = keys.responderNoncePfx;
      this.recvNoncePfx = keys.initiatorNoncePfx;
    }
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new Error("connection closed");
    if (data.length === 0) return 0;

    const counter = this.sendCounter;
    this.sendCounter++;

    const ts = Math.floor(Date.now() / 1000) >>> 0;

    // Build nonce: [12B prefix][4B timestamp][8B counter].
    const nonce = new Uint8Array(NONCE_SIZE);
    nonce.set(this.sendNoncePfx);
    writeU32BE(nonce, NONCE_PREFIX_SIZE, ts);
    writeU64BE(nonce, NONCE_PREFIX_SIZE + TIMESTAMP_SIZE, counter);

    const ciphertext = this.sendCipher.seal(nonce, data);
    const frame = marshalData(ts, counter, ciphertext);
    await writeFrame(this.inner, frame);

    return data.length;
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new Error("connection closed");

    // Return buffered data first.
    if (this.recvBuf && this.recvBuf.length > 0) {
      const n = Math.min(buffer.length, this.recvBuf.length);
      buffer.set(this.recvBuf.subarray(0, n));
      this.recvBuf =
        n < this.recvBuf.length ? this.recvBuf.subarray(n) : null;
      return n;
    }

    // Read next frame.
    const body = await readFrame(this.inner);
    if (body.length < 1) throw new Error("empty frame");

    const msgType = body[0];

    if (msgType === MSG_DATA) {
      return this.handleData(body, buffer);
    } else if (msgType === MSG_ERROR) {
      let reason = "unknown";
      if (body.length >= 3) {
        const rLen = (body[1] << 8) | body[2];
        if (3 + rLen <= body.length) {
          reason = new TextDecoder().decode(body.subarray(3, 3 + rLen));
        }
      }
      throw new Error(`peer error: ${reason}`);
    } else {
      throw new Error(`unexpected message type: 0x${msgType.toString(16)}`);
    }
  }

  private handleData(body: Uint8Array, buffer: Uint8Array): number {
    if (body.length < 13) throw new Error("DATA message too short");

    const ts = readU32BEFrom(body, 1);
    const counter = readU64BEFrom(body, 5);
    const ciphertext = body.subarray(13);

    // Reconstruct nonce.
    const nonce = new Uint8Array(NONCE_SIZE);
    nonce.set(this.recvNoncePfx);
    writeU32BE(nonce, NONCE_PREFIX_SIZE, ts);
    writeU64BE(nonce, NONCE_PREFIX_SIZE + TIMESTAMP_SIZE, counter);

    const plaintext = this.recvCipher.open(nonce, ciphertext);
    if (!plaintext) throw new Error("decrypt failed: AEAD tag mismatch");

    const n = Math.min(buffer.length, plaintext.length);
    buffer.set(plaintext.subarray(0, n));
    if (n < plaintext.length) {
      this.recvBuf = plaintext.subarray(n);
    }
    return n;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    try {
      await writeFrame(this.inner, marshalError("closed"));
    } catch {
      // best-effort
    }
    await this.inner.close();
  }

  localAddr(): Addr {
    return this.inner.localAddr();
  }

  remoteAddr(): Addr {
    return this.inner.remoteAddr();
  }

  setDeadline(ms: number): void {
    this.inner.setDeadline(ms);
  }

  setReadDeadline(ms: number): void {
    this.inner.setReadDeadline(ms);
  }

  setWriteDeadline(ms: number): void {
    this.inner.setWriteDeadline(ms);
  }
}

// Helper: inline read functions to avoid circular deps.
function readU32BEFrom(buf: Uint8Array, off: number): number {
  return (
    ((buf[off] << 24) |
      (buf[off + 1] << 16) |
      (buf[off + 2] << 8) |
      buf[off + 3]) >>>
    0
  );
}

function readU64BEFrom(buf: Uint8Array, off: number): bigint {
  const hi = BigInt(readU32BEFrom(buf, off));
  const lo = BigInt(readU32BEFrom(buf, off + 4));
  return (hi << 32n) | lo;
}

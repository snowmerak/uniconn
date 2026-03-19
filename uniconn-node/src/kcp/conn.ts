import type { Addr, IConn } from "../conn.js";
import { ConnectionClosedError, TimeoutError } from "../errors.js";

// Import kcpjs — a kcp-go compatible KCP implementation for Node.js
import { DialWithOptions, type UDPSession } from "kcpjs";

/**
 * KcpConn wraps a kcpjs UDPSession (real KCP protocol) into IConn.
 *
 * This uses the kcpjs library which is wire-compatible with Go's kcp-go,
 * providing reliable UDP transport with the KCP ARQ protocol.
 */
export class KcpConn implements IConn {
  private session: UDPSession;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private pendingData: Buffer[] = [];
  private readResolve: ((value: number) => void) | null = null;
  private readReject: ((reason: Error) => void) | null = null;
  private readBuffer: Uint8Array | null = null;
  private eofReached = false;

  constructor(session: UDPSession) {
    this.session = session;

    this.session.on("recv", (buf: Buffer) => {
      if (this.readResolve && this.readBuffer) {
        const n = Math.min(buf.length, this.readBuffer.length);
        buf.copy(this.readBuffer as Buffer, 0, 0, n);
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        if (n < buf.length) {
          this.pendingData.push(buf.subarray(n));
        }
        resolve(n);
      } else {
        this.pendingData.push(Buffer.from(buf));
      }
    });

    this.session.on("close", () => {
      this.eofReached = true;
      if (this.readResolve) {
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        resolve(0);
      }
    });
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    if (this.pendingData.length > 0) {
      const chunk = this.pendingData[0];
      const n = Math.min(chunk.length, buffer.length);
      chunk.copy(buffer as Buffer, 0, 0, n);
      if (n < chunk.length) {
        this.pendingData[0] = chunk.subarray(n);
      } else {
        this.pendingData.shift();
      }
      return n;
    }

    if (this.eofReached) return 0;

    return new Promise<number>((resolve, reject) => {
      this.readResolve = resolve;
      this.readReject = reject;
      this.readBuffer = buffer;

      if (this.readDeadlineMs > 0) {
        const timer = setTimeout(() => {
          this.readResolve = null;
          this.readReject = null;
          this.readBuffer = null;
          reject(new TimeoutError("read"));
        }, this.readDeadlineMs);
        const origResolve = resolve;
        this.readResolve = (n: number) => {
          clearTimeout(timer);
          origResolve(n);
        };
      }
    });
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();
    // kcpjs write is synchronous, returns number of bytes
    const n = this.session.write(Buffer.from(data));
    return n;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.session.removeAllListeners();
    this.session.close();
    // Null out the kcp instance so kcpjs's recursive check() timer
    // hits its guard `if (!this.kcp) return` and stops.
    (this.session as any).kcp = undefined;
  }

  localAddr(): Addr {
    return {
      network: "kcp",
      address: "0.0.0.0:0",
    };
  }

  remoteAddr(): Addr {
    return {
      network: "kcp",
      address: `${this.session.host}:${this.session.port}`,
    };
  }

  setDeadline(ms: number): void {
    this.readDeadlineMs = ms;
    this.writeDeadlineMs = ms;
  }

  setReadDeadline(ms: number): void {
    this.readDeadlineMs = ms;
  }

  setWriteDeadline(ms: number): void {
    this.writeDeadlineMs = ms;
  }
}

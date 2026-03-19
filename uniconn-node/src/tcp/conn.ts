import * as net from "node:net";
import type { Addr, IConn } from "../conn.js";
import { ConnectionClosedError, TimeoutError } from "../errors.js";

/**
 * TcpConn wraps a Node.js net.Socket into an IConn.
 */
export class TcpConn implements IConn {
  private socket: net.Socket;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private pendingData: Buffer[] = [];
  private readResolve: ((value: number) => void) | null = null;
  private readReject: ((reason: Error) => void) | null = null;
  private readBuffer: Uint8Array | null = null;
  private eofReached = false;

  constructor(socket: net.Socket) {
    this.socket = socket;
    this.socket.on("data", (chunk: Buffer) => {
      if (this.readResolve && this.readBuffer) {
        const n = Math.min(chunk.length, this.readBuffer.length);
        chunk.copy(this.readBuffer as Buffer, 0, 0, n);
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        if (n < chunk.length) {
          this.pendingData.push(chunk.subarray(n));
        }
        resolve(n);
      } else {
        this.pendingData.push(chunk);
      }
    });
    this.socket.on("end", () => {
      this.eofReached = true;
      if (this.readResolve) {
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        resolve(0);
      }
    });
    this.socket.on("error", (err) => {
      if (this.readReject) {
        const reject = this.readReject;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        reject(err);
      }
    });
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    // Consume from pending buffer first
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

    return new Promise<number>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      if (this.writeDeadlineMs > 0) {
        timer = setTimeout(() => {
          reject(new TimeoutError("write"));
        }, this.writeDeadlineMs);
      }

      this.socket.write(data, (err) => {
        if (timer) clearTimeout(timer);
        if (err) reject(err);
        else resolve(data.length);
      });
    });
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    return new Promise((resolve) => {
      this.socket.end(() => {
        this.socket.destroy();
        resolve();
      });
    });
  }

  localAddr(): Addr {
    return {
      network: "tcp",
      address: `${this.socket.localAddress ?? "0.0.0.0"}:${this.socket.localPort ?? 0}`,
    };
  }

  remoteAddr(): Addr {
    return {
      network: "tcp",
      address: `${this.socket.remoteAddress ?? "0.0.0.0"}:${this.socket.remotePort ?? 0}`,
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

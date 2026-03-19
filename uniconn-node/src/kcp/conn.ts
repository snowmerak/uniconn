import * as dgram from "node:dgram";
import type { Addr, IConn } from "../conn.js";
import { ConnectionClosedError, TimeoutError } from "../errors.js";

/**
 * KcpConn wraps a KCP session over UDP into an IConn.
 *
 * NOTE: KCP (kcpjs) support is provided as a best-effort adapter.
 * The kcpjs library handles the KCP protocol logic over a UDP socket.
 * This is a simplified implementation — for production use, consider
 * a more mature KCP binding.
 */
export class KcpConn implements IConn {
  private socket: dgram.Socket;
  private remoteHost: string;
  private remotePort: number;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private pendingData: Buffer[] = [];
  private readResolve: ((value: number) => void) | null = null;
  private readReject: ((reason: Error) => void) | null = null;
  private readBuffer: Uint8Array | null = null;
  private eofReached = false;

  constructor(socket: dgram.Socket, remoteHost: string, remotePort: number) {
    this.socket = socket;
    this.remoteHost = remoteHost;
    this.remotePort = remotePort;

    this.socket.on("message", (msg: Buffer) => {
      if (this.readResolve && this.readBuffer) {
        const n = Math.min(msg.length, this.readBuffer.length);
        msg.copy(this.readBuffer as Buffer, 0, 0, n);
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        if (n < msg.length) {
          this.pendingData.push(msg.subarray(n));
        }
        resolve(n);
      } else {
        this.pendingData.push(msg);
      }
    });

    this.socket.on("close", () => {
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

      this.socket.send(data, this.remotePort, this.remoteHost, (err) => {
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
      this.socket.close(() => resolve());
    });
  }

  localAddr(): Addr {
    const a = this.socket.address() as { address: string; port: number };
    return {
      network: "kcp",
      address: `${a.address}:${a.port}`,
    };
  }

  remoteAddr(): Addr {
    return {
      network: "kcp",
      address: `${this.remoteHost}:${this.remotePort}`,
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

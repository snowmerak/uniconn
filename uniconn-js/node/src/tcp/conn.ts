import * as net from "node:net";
import type { Addr, IConn } from "@uniconn/core";
import { ConnectionClosedError, TimeoutError, ReadQueue } from "@uniconn/core";

/**
 * TcpConn wraps a Node.js net.Socket into an IConn.
 */
export class TcpConn implements IConn {
  private socket: net.Socket;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private reads = new ReadQueue();

  constructor(socket: net.Socket) {
    this.socket = socket;
    this.socket.on("data", (chunk: Buffer) => this.reads.push(chunk));
    this.socket.on("end", () => this.reads.end());
    this.socket.on("close", () => this.reads.end());
    this.socket.on("error", (error: Error) => this.reads.fail(error));
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();
    return this.reads.read(buffer, this.readDeadlineMs);
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
    this.reads.fail(new ConnectionClosedError());
    this.socket.destroy();
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

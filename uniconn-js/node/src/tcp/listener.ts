import * as net from "node:net";
import type { Addr, IConn, IListener } from "@uniconn/core";
import { ListenerClosedError } from "@uniconn/core";
import { TcpConn } from "./conn.js";

/** Configuration for a TCP listener. */
export interface ListenConfig {
  /** Enable TCP keep-alive on accepted connections. */
  keepAlive?: boolean;
  /** Keep-alive initial delay in milliseconds. */
  keepAliveInitialDelay?: number;
}

/**
 * TcpListener implements IListener for TCP connections.
 */
export class TcpListener implements IListener {
  private server: net.Server;
  private connQueue: TcpConn[] = [];
  private waiters: Array<{
    resolve: (conn: IConn) => void;
    reject: (err: Error) => void;
  }> = [];
  private closed = false;
  private listenAddr: Addr;
  private config: ListenConfig;

  private constructor(server: net.Server, address: Addr, config: ListenConfig) {
    this.server = server;
    this.listenAddr = address;
    this.config = config;

    this.server.on("connection", (socket: net.Socket) => {
      if (this.config.keepAlive) {
        socket.setKeepAlive(true, this.config.keepAliveInitialDelay ?? 0);
      }

      const conn = new TcpConn(socket);
      if (this.waiters.length > 0) {
        const waiter = this.waiters.shift()!;
        waiter.resolve(conn);
      } else {
        this.connQueue.push(conn);
      }
    });
  }

  /**
   * Create a TCP listener on the given port and optional host.
   */
  static listen(port: number, host?: string, config?: ListenConfig): Promise<TcpListener> {
    const cfg = config ?? {};
    return new Promise((resolve, reject) => {
      const server = net.createServer();
      server.on("error", reject);
      server.listen(port, host ?? "0.0.0.0", () => {
        server.removeListener("error", reject);
        const a = server.address() as net.AddressInfo;
        const addr: Addr = {
          network: "tcp",
          address: `${a.address}:${a.port}`,
        };
        resolve(new TcpListener(server, addr, cfg));
      });
    });
  }

  async accept(): Promise<IConn> {
    if (this.closed) throw new ListenerClosedError();

    if (this.connQueue.length > 0) {
      return this.connQueue.shift()!;
    }

    return new Promise<IConn>((resolve, reject) => {
      this.waiters.push({ resolve, reject });
    });
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    // Reject all pending waiters
    for (const w of this.waiters) {
      w.reject(new ListenerClosedError());
    }
    this.waiters = [];
    return new Promise((resolve) => {
      this.server.close(() => resolve());
    });
  }

  addr(): Addr {
    return this.listenAddr;
  }
}

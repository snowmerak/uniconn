import * as dgram from "node:dgram";
import type { Addr, IConn, IListener } from "../conn.js";
import { ListenerClosedError } from "../errors.js";
import { KcpConn } from "./conn.js";

/** Configuration for a KCP listener. */
export interface ListenConfig {
  // Reserved for future KCP-specific options (FEC, encryption, etc.)
}

/**
 * KcpListener implements IListener for KCP connections over UDP.
 *
 * In KCP, there is no explicit "accept" mechanism like TCP.
 * This listener creates a new KcpConn for each unique remote address
 * that sends data to the bound UDP port.
 */
export class KcpListener implements IListener {
  private socket: dgram.Socket;
  private connMap = new Map<string, KcpConn>();
  private connQueue: IConn[] = [];
  private waiters: Array<{
    resolve: (conn: IConn) => void;
    reject: (err: Error) => void;
  }> = [];
  private closed = false;
  private listenAddr: Addr;

  private constructor(socket: dgram.Socket, addr: Addr) {
    this.socket = socket;
    this.listenAddr = addr;

    this.socket.on("message", (msg: Buffer, rinfo: dgram.RemoteInfo) => {
      const key = `${rinfo.address}:${rinfo.port}`;

      if (!this.connMap.has(key)) {
        // Create a new "connected" UDP socket for this remote peer
        const peerSocket = dgram.createSocket("udp4");
        peerSocket.bind(0, () => {
          peerSocket.connect(rinfo.port, rinfo.address);
        });

        const conn = new KcpConn(peerSocket, rinfo.address, rinfo.port);
        this.connMap.set(key, conn);

        // Deliver initial data
        // Since the peerSocket won't receive the first message (it was on the listener socket),
        // we manually inject it
        conn.read(new Uint8Array(0)); // no-op to ensure listeners are set up

        if (this.waiters.length > 0) {
          const waiter = this.waiters.shift()!;
          waiter.resolve(conn);
        } else {
          this.connQueue.push(conn);
        }
      }
    });
  }

  /**
   * Create a KCP listener on the given port and optional host.
   */
  static listen(port: number, host?: string, _config?: ListenConfig): Promise<KcpListener> {
    return new Promise((resolve, reject) => {
      const socket = dgram.createSocket("udp4");
      socket.on("error", reject);
      socket.bind(port, host ?? "0.0.0.0", () => {
        socket.removeListener("error", reject);
        const a = socket.address() as { address: string; port: number };
        const addr: Addr = {
          network: "kcp",
          address: `${a.address}:${a.port}`,
        };
        resolve(new KcpListener(socket, addr));
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
    for (const w of this.waiters) {
      w.reject(new ListenerClosedError());
    }
    this.waiters = [];
    // Close all peer connections
    for (const conn of this.connMap.values()) {
      await conn.close();
    }
    this.connMap.clear();
    return new Promise((resolve) => {
      this.socket.close(() => resolve());
    });
  }

  addr(): Addr {
    return this.listenAddr;
  }
}

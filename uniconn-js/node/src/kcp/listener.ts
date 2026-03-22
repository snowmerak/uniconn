import type { Addr, IConn, IListener } from "@uniconn/core";
import { ListenerClosedError } from "@uniconn/core";
import { KcpConn } from "./conn.js";

import { ListenWithOptions, type Listener as KcpListener_, type UDPSession } from "kcpjs";

/** Configuration for a KCP listener. */
export interface ListenConfig {
  /** Data shards for FEC. 0 = no FEC. */
  dataShards?: number;
  /** Parity shards for FEC. 0 = no FEC. */
  parityShards?: number;
}

/**
 * KcpListener implements IListener for KCP connections.
 * Uses the kcpjs library which is wire-compatible with Go's kcp-go.
 */
export class KcpListener implements IListener {
  private inner: KcpListener_;
  private connQueue: IConn[] = [];
  private waiters: Array<{
    resolve: (conn: IConn) => void;
    reject: (err: Error) => void;
  }> = [];
  private closed = false;
  private listenAddr: Addr;

  private constructor(inner: KcpListener_, addr: Addr) {
    this.inner = inner;
    this.listenAddr = addr;
  }

  /**
   * Create a KCP listener on the given port.
   */
  static listen(port: number, config?: ListenConfig): KcpListener {
    const cfg = config ?? {};
    let listener: KcpListener;
    const inner = ListenWithOptions({
      port,
      dataShards: cfg.dataShards ?? 0,
      parityShards: cfg.parityShards ?? 0,
      callback: (session: UDPSession) => {
        const conn = new KcpConn(session);
        if (listener.waiters.length > 0) {
          const waiter = listener.waiters.shift()!;
          waiter.resolve(conn);
        } else {
          listener.connQueue.push(conn);
        }
      },
    });
    const addr: Addr = {
      network: "kcp",
      address: `0.0.0.0:${port}`,
    };
    listener = new KcpListener(inner, addr);
    return listener;
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
    this.inner.close();
  }

  addr(): Addr {
    return this.listenAddr;
  }
}

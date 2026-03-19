import { WebSocketServer } from "ws";
import type { Addr, IConn, IListener } from "../conn.js";
import { ListenerClosedError } from "../errors.js";
import { WsConn } from "./conn.js";

/** Configuration for a WebSocket listener. */
export interface ListenConfig {
  /** HTTP path for WebSocket upgrades. Defaults to "/". */
  path?: string;
  /** Maximum payload size in bytes. */
  maxPayload?: number;
}

/**
 * WsListener implements IListener for WebSocket connections (server-side).
 * Uses the `ws` library's WebSocketServer.
 */
export class WsListener implements IListener {
  private wss: WebSocketServer;
  private connQueue: IConn[] = [];
  private waiters: Array<{
    resolve: (conn: IConn) => void;
    reject: (err: Error) => void;
  }> = [];
  private closed = false;
  private listenAddr: Addr;

  private constructor(wss: WebSocketServer, addr: Addr) {
    this.wss = wss;
    this.listenAddr = addr;

    this.wss.on("connection", (ws, req) => {
      const remoteAddr: Addr = {
        network: "websocket",
        address: `${req.socket.remoteAddress ?? "0.0.0.0"}:${req.socket.remotePort ?? 0}`,
      };
      const conn = new WsConn(ws as any, addr, remoteAddr);

      if (this.waiters.length > 0) {
        const waiter = this.waiters.shift()!;
        waiter.resolve(conn);
      } else {
        this.connQueue.push(conn);
      }
    });
  }

  /**
   * Create a WebSocket listener on the given port and optional host.
   */
  static listen(port: number, host?: string, config?: ListenConfig): Promise<WsListener> {
    const cfg = config ?? {};
    return new Promise((resolve, reject) => {
      const wss = new WebSocketServer({
        port,
        host: host ?? "0.0.0.0",
        path: cfg.path ?? "/",
        maxPayload: cfg.maxPayload,
      });

      wss.on("error", reject);
      wss.on("listening", () => {
        wss.removeListener("error", reject);
        const a = wss.address() as { address: string; port: number };
        const addr: Addr = {
          network: "websocket",
          address: `${a.address}:${a.port}`,
        };
        resolve(new WsListener(wss, addr));
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
    return new Promise((resolve) => {
      this.wss.close(() => resolve());
    });
  }

  addr(): Addr {
    return this.listenAddr;
  }
}

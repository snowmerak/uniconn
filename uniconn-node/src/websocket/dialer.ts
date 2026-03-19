import WebSocket from "ws";
import type { Addr, IConn, IDialer, DialOptions } from "../conn.js";
import { WsConn } from "./conn.js";

/** Configuration for WebSocket dialing. */
export interface DialConfig {
  /** Additional HTTP headers for the handshake. */
  headers?: Record<string, string>;
}

/**
 * WsDialer implements IDialer for WebSocket connections.
 * Works with the `ws` library on Node.js.
 * For browser usage, use WsConn directly with the native WebSocket.
 */
export class WsDialer implements IDialer {
  private config: DialConfig;

  constructor(config?: DialConfig) {
    this.config = config ?? {};
  }

  async dial(address: string, options?: DialOptions): Promise<IConn> {
    return new Promise<IConn>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const cleanup = () => {
        if (timer) clearTimeout(timer);
        options?.signal?.removeEventListener("abort", onAbort);
      };

      const onAbort = () => {
        cleanup();
        ws.close();
        reject(new Error("dial aborted"));
      };

      if (options?.timeout) {
        timer = setTimeout(() => {
          ws.close();
          reject(new Error("dial timed out"));
        }, options.timeout);
      }

      if (options?.signal) {
        if (options.signal.aborted) {
          reject(new Error("dial aborted"));
          return;
        }
        options.signal.addEventListener("abort", onAbort, { once: true });
      }

      const ws = new WebSocket(address, {
        headers: this.config.headers,
      });

      ws.binaryType = "arraybuffer";

      ws.on("open", () => {
        cleanup();
        const url = new URL(address);
        const localAddr: Addr = {
          network: "websocket",
          address: "0.0.0.0:0",
        };
        const remoteAddr: Addr = {
          network: "websocket",
          address: `${url.hostname}:${url.port || (url.protocol === "wss:" ? "443" : "80")}`,
        };
        resolve(new WsConn(ws as any, localAddr, remoteAddr));
      });

      ws.on("error", (err) => {
        cleanup();
        reject(err);
      });
    });
  }
}

import * as net from "node:net";
import type { IConn, IDialer, DialOptions } from "../conn.js";
import { TcpConn } from "./conn.js";

/** Configuration for TCP dialing. */
export interface DialConfig {
  /** Enable TCP keep-alive. */
  keepAlive?: boolean;
  /** Keep-alive initial delay in milliseconds. */
  keepAliveInitialDelay?: number;
  /** Local address to bind to (host:port). */
  localAddr?: string;
}

/**
 * TcpDialer implements IDialer for TCP connections.
 */
export class TcpDialer implements IDialer {
  private config: DialConfig;

  constructor(config?: DialConfig) {
    this.config = config ?? {};
  }

  async dial(address: string, options?: DialOptions): Promise<IConn> {
    const [host, portStr] = splitHostPort(address);
    const port = parseInt(portStr, 10);

    return new Promise<IConn>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const cleanup = () => {
        if (timer) clearTimeout(timer);
        options?.signal?.removeEventListener("abort", onAbort);
      };

      const onAbort = () => {
        cleanup();
        socket.destroy();
        reject(new Error("dial aborted"));
      };

      if (options?.timeout) {
        timer = setTimeout(() => {
          socket.destroy();
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

      const connectOptions: net.NetConnectOpts = { host, port };
      if (this.config.localAddr) {
        const [lHost, lPort] = splitHostPort(this.config.localAddr);
        connectOptions.localAddress = lHost;
        connectOptions.localPort = parseInt(lPort, 10);
      }

      const socket = net.connect(connectOptions, () => {
        cleanup();
        if (this.config.keepAlive) {
          socket.setKeepAlive(true, this.config.keepAliveInitialDelay ?? 0);
        }
        resolve(new TcpConn(socket));
      });

      socket.on("error", (err) => {
        cleanup();
        reject(err);
      });
    });
  }
}

/** Split "host:port" into [host, port]. */
function splitHostPort(address: string): [string, string] {
  const lastColon = address.lastIndexOf(":");
  if (lastColon === -1) {
    return [address, "0"];
  }
  return [address.substring(0, lastColon), address.substring(lastColon + 1)];
}

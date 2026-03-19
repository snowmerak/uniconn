import * as dgram from "node:dgram";
import type { IConn, IDialer, DialOptions } from "../conn.js";
import { KcpConn } from "./conn.js";

/** Configuration for KCP dialing. */
export interface DialConfig {
  /** Local address to bind to. */
  localAddr?: string;
}

/**
 * KcpDialer implements IDialer for KCP connections over UDP.
 */
export class KcpDialer implements IDialer {
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
        socket.close();
        reject(new Error("dial aborted"));
      };

      if (options?.timeout) {
        timer = setTimeout(() => {
          socket.close();
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

      const socket = dgram.createSocket("udp4");

      const bindPort = 0;
      const bindHost = this.config.localAddr
        ? splitHostPort(this.config.localAddr)[0]
        : "0.0.0.0";

      socket.bind(bindPort, bindHost, () => {
        socket.connect(port, host, () => {
          cleanup();
          resolve(new KcpConn(socket, host, port));
        });
      });

      socket.on("error", (err) => {
        cleanup();
        reject(err);
      });
    });
  }
}

function splitHostPort(address: string): [string, string] {
  const lastColon = address.lastIndexOf(":");
  if (lastColon === -1) return [address, "0"];
  return [address.substring(0, lastColon), address.substring(lastColon + 1)];
}

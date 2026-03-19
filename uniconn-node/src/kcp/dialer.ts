import type { IConn, IDialer, DialOptions } from "../conn.js";
import { KcpConn } from "./conn.js";

import { DialWithOptions } from "kcpjs";

/** Configuration for KCP dialing. */
export interface DialConfig {
  /** Conversation ID. Defaults to 1. */
  conv?: number;
  /** Data shards for FEC. 0 = no FEC. */
  dataShards?: number;
  /** Parity shards for FEC. 0 = no FEC. */
  parityShards?: number;
}

/**
 * KcpDialer implements IDialer for KCP connections.
 * Uses the kcpjs library which is wire-compatible with Go's kcp-go.
 */
export class KcpDialer implements IDialer {
  private config: DialConfig;

  constructor(config?: DialConfig) {
    this.config = config ?? {};
  }

  async dial(address: string, _options?: DialOptions): Promise<IConn> {
    const [host, portStr] = splitHostPort(address);
    const port = parseInt(portStr, 10);

    const session = DialWithOptions({
      conv: this.config.conv ?? 1,
      port,
      host,
      dataShards: this.config.dataShards ?? 0,
      parityShards: this.config.parityShards ?? 0,
    });

    return new KcpConn(session);
  }
}

function splitHostPort(address: string): [string, string] {
  const lastColon = address.lastIndexOf(":");
  if (lastColon === -1) return [address, "0"];
  return [address.substring(0, lastColon), address.substring(lastColon + 1)];
}

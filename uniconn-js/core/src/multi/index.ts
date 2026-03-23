/**
 * Multi-protocol negotiate types and helpers.
 *
 * Matches the Go `multi` package wire format:
 * GET /negotiate → { protocols: [{name, address}, ...] }
 */

import type { IDialer, IListener, IConn, DialOptions, Addr } from "../conn.js";

/** Protocol identifiers — must match Go constants. */
export type Protocol =
  | "webtransport"
  | "quic"
  | "websocket"
  | "kcp"
  | "tcp";

/** Default protocol priority: higher-performance first. */
export const DEFAULT_PRIORITY: Protocol[] = [
  "webtransport",
  "quic",
  "websocket",
  "kcp",
  "tcp",
];

/** A single protocol entry in the negotiate response. */
export interface ProtocolEntry {
  name: Protocol;
  address: string;
}

/** JSON response from the /negotiate endpoint. */
export interface NegotiateResponse {
  protocols: ProtocolEntry[];
}

/** Default per-protocol dial timeout in ms. */
export const DEFAULT_DIAL_TIMEOUT = 5000;

// ───── MultiDialer ──────────────────────────────────────────

export interface MultiDialerConfig {
  /** Full URL of the negotiate endpoint (e.g. "http://server:19000/negotiate"). */
  negotiateURL: string;
  /** Protocol priority. Defaults to DEFAULT_PRIORITY. */
  priority?: Protocol[];
  /** Maps Protocol → IDialer. Only registered protocols will be attempted. */
  dialers: Partial<Record<Protocol, IDialer>>;
  /** Per-protocol dial timeout in ms. Defaults to DEFAULT_DIAL_TIMEOUT. */
  dialTimeout?: number;
}

export interface DialResult {
  conn: IConn;
  protocol: Protocol;
}

/**
 * MultiDialer — negotiates with the server and connects via the best protocol.
 */
export class MultiDialer {
  private config: Required<Pick<MultiDialerConfig, "negotiateURL" | "dialTimeout">> &
    MultiDialerConfig;

  constructor(config: MultiDialerConfig) {
    this.config = {
      ...config,
      priority: config.priority ?? DEFAULT_PRIORITY,
      dialTimeout: config.dialTimeout ?? DEFAULT_DIAL_TIMEOUT,
    };
  }

  /**
   * Negotiate and dial the best available protocol.
   * @param signal Optional AbortSignal to cancel the entire operation.
   */
  async dial(signal?: AbortSignal): Promise<DialResult> {
    // 1. Fetch negotiate response.
    const serverProtos = await this.negotiate(signal);

    // Build lookup: protocol → address.
    const serverMap = new Map<Protocol, string>();
    for (const p of serverProtos) {
      serverMap.set(p.name, p.address);
    }

    // 2. Try protocols in priority order.
    let lastError: Error | undefined;

    for (const proto of this.config.priority!) {
      const address = serverMap.get(proto);
      if (!address) continue;

      const dialer = this.config.dialers[proto];
      if (!dialer) continue;

      try {
        const conn = await dialer.dial(address, {
          timeout: this.config.dialTimeout,
          signal,
        });
        return { conn, protocol: proto };
      } catch (err) {
        lastError = new Error(`[${proto}] ${err}`);
      }
    }

    if (lastError) {
      throw new Error(`all protocols failed, last: ${lastError.message}`);
    }
    throw new Error("no compatible protocol found");
  }

  private async negotiate(signal?: AbortSignal): Promise<ProtocolEntry[]> {
    const resp = await fetch(this.config.negotiateURL, { signal });
    if (!resp.ok) {
      throw new Error(`negotiate: HTTP ${resp.status}`);
    }
    const body = (await resp.json()) as NegotiateResponse;
    return body.protocols;
  }
}

// ───── MultiListener ────────────────────────────────────────

export interface TransportConfig {
  protocol: Protocol;
  /** Externally-reachable address advertised to clients. */
  address: string;
  /** An already-started IListener for this protocol. */
  listener: IListener;
}

export interface AcceptResult {
  conn: IConn;
  protocol: Protocol;
}

/**
 * MultiListener — fans-in connections from multiple protocol listeners.
 *
 * Note: The negotiate HTTP endpoint must be served separately
 * (e.g. via Express or Node.js http.createServer) using getNegotiateEntries().
 * This keeps the core package platform-agnostic.
 */
export class MultiListener {
  private transports: TransportConfig[];
  private connQueue: AcceptResult[] = [];
  private waiters: Array<(result: AcceptResult | Error) => void> = [];
  private closed = false;

  constructor(transports: TransportConfig[]) {
    if (transports.length === 0) {
      throw new Error("multi: at least one transport is required");
    }
    this.transports = transports;

    // Start accept loops for each transport.
    for (const t of transports) {
      this.acceptLoop(t);
    }
  }

  /** Get the protocol entries for a negotiate HTTP response. */
  getNegotiateEntries(): ProtocolEntry[] {
    return this.transports.map((t) => ({
      name: t.protocol,
      address: t.address,
    }));
  }

  /** Get the full NegotiateResponse JSON object. */
  getNegotiateResponse(): NegotiateResponse {
    return { protocols: this.getNegotiateEntries() };
  }

  /** Accept the next connection from any protocol. */
  async accept(): Promise<IConn> {
    const result = await this.acceptWith();
    return result.conn;
  }

  /** Accept the next connection along with the protocol it came from. */
  acceptWith(): Promise<AcceptResult> {
    if (this.closed) {
      return Promise.reject(new Error("listener closed"));
    }

    // If we have a queued connection, return it immediately.
    const queued = this.connQueue.shift();
    if (queued) {
      return Promise.resolve(queued);
    }

    // Otherwise wait.
    return new Promise<AcceptResult>((resolve, reject) => {
      this.waiters.push((result) => {
        if (result instanceof Error) {
          reject(result);
        } else {
          resolve(result);
        }
      });
    });
  }

  /** Close all underlying listeners. */
  async close(): Promise<void> {
    this.closed = true;
    for (const w of this.waiters) {
      w(new Error("listener closed"));
    }
    this.waiters = [];

    for (const t of this.transports) {
      await t.listener.close();
    }
  }

  private async acceptLoop(t: TransportConfig): Promise<void> {
    while (!this.closed) {
      try {
        const conn = await t.listener.accept();
        const result: AcceptResult = { conn, protocol: t.protocol };

        const waiter = this.waiters.shift();
        if (waiter) {
          waiter(result);
        } else {
          this.connQueue.push(result);
        }
      } catch {
        if (!this.closed) {
          break;
        }
      }
    }
  }
}

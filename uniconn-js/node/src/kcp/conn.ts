import type { Addr, IConn } from "@uniconn/core";
import { ConnectionClosedError, TimeoutError, ReadQueue } from "@uniconn/core";

// Import kcpjs ??a kcp-go compatible KCP implementation for Node.js
import { DialWithOptions, type UDPSession } from "kcpjs";

/**
 * KcpConn wraps a kcpjs UDPSession (real KCP protocol) into IConn.
 *
 * This uses the kcpjs library which is wire-compatible with Go's kcp-go,
 * providing reliable UDP transport with the KCP ARQ protocol.
 */
export class KcpConn implements IConn {
  private session: UDPSession;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private reads = new ReadQueue();

  constructor(session: UDPSession) {
    this.session = session;

    this.session.on("recv", (chunk: Buffer) => this.reads.push(Buffer.from(chunk)));
    this.session.on("close", () => this.reads.end());
    this.session.on("error", (error: Error) => this.reads.fail(error));
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();
    return this.reads.read(buffer, this.readDeadlineMs);
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();
    // kcpjs write is synchronous, returns number of bytes
    const n = this.session.write(Buffer.from(data));
    return n;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.reads.fail(new ConnectionClosedError());
    this.session.removeAllListeners();
    this.session.close();
    // Null out the kcp instance so kcpjs's recursive check() timer
    // hits its guard `if (!this.kcp) return` and stops.
    (this.session as any).kcp = undefined;
  }

  localAddr(): Addr {
    return {
      network: "kcp",
      address: "0.0.0.0:0",
    };
  }

  remoteAddr(): Addr {
    return {
      network: "kcp",
      address: `${this.session.host}:${this.session.port}`,
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

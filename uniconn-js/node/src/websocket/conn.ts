import type { Addr, IConn } from "@uniconn/core";
import { ConnectionClosedError, TimeoutError, ReadQueue } from "@uniconn/core";

/**
 * WebSocket IConn implementation.
 *
 * Works with both the `ws` library (Node.js) and the browser's native
 * WebSocket API by accepting a common minimal interface.
 */
export class WsConn implements IConn {
  private ws: WebSocketLike;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private reads = new ReadQueue();
  private localAddress: Addr;
  private remoteAddress: Addr;

  constructor(ws: WebSocketLike, localAddr: Addr, remoteAddr: Addr) {
    this.ws = ws;
    this.localAddress = localAddr;
    this.remoteAddress = remoteAddr;

    ws.binaryType = "arraybuffer";

    ws.onmessage = (event: MessageEvent | { data: ArrayBuffer | Buffer }) => {
      const data = event.data;
      const chunk = data instanceof ArrayBuffer ? new Uint8Array(data)
        : Buffer.isBuffer(data) ? new Uint8Array(data) : new TextEncoder().encode(data as string);
      this.reads.push(chunk);
    };
    ws.onclose = () => this.reads.end();
    ws.onerror = (error: Event | Error) => this.reads.fail(
      error instanceof Error ? error : new Error("websocket error"));
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();
    return this.reads.read(buffer, this.readDeadlineMs);
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    return new Promise<number>((resolve, reject) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      if (this.writeDeadlineMs > 0) {
        timer = setTimeout(() => {
          reject(new TimeoutError("write"));
        }, this.writeDeadlineMs);
      }

      try {
        this.ws.send(data);
        if (timer) clearTimeout(timer);
        resolve(data.length);
      } catch (err) {
        if (timer) clearTimeout(timer);
        reject(err);
      }
    });
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.reads.fail(new ConnectionClosedError());
    this.ws.close(1000, "closed");
  }

  localAddr(): Addr {
    return this.localAddress;
  }

  remoteAddr(): Addr {
    return this.remoteAddress;
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

/**
 * Minimal WebSocket-like interface that works with both
 * the `ws` library and the browser's native WebSocket.
 */
export interface WebSocketLike {
  binaryType: string;
  onmessage: ((event: any) => void) | null;
  onclose: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  send(data: Uint8Array | string): void;
  close(code?: number, reason?: string): void;
}

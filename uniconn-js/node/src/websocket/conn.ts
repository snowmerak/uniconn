import type { Addr, IConn } from "@uniconn/core";
import { ConnectionClosedError, TimeoutError } from "@uniconn/core";

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
  private pendingData: Uint8Array[] = [];
  private readResolve: ((value: number) => void) | null = null;
  private readReject: ((reason: Error) => void) | null = null;
  private readBuffer: Uint8Array | null = null;
  private eofReached = false;
  private localAddress: Addr;
  private remoteAddress: Addr;

  constructor(ws: WebSocketLike, localAddr: Addr, remoteAddr: Addr) {
    this.ws = ws;
    this.localAddress = localAddr;
    this.remoteAddress = remoteAddr;

    ws.binaryType = "arraybuffer";

    ws.onmessage = (event: MessageEvent | { data: ArrayBuffer | Buffer }) => {
      const data = event.data;
      let chunk: Uint8Array;
      if (data instanceof ArrayBuffer) {
        chunk = new Uint8Array(data);
      } else if (Buffer.isBuffer(data)) {
        chunk = new Uint8Array(data);
      } else {
        // Text message ??encode to bytes
        chunk = new TextEncoder().encode(data as string);
      }

      if (this.readResolve && this.readBuffer) {
        const n = Math.min(chunk.length, this.readBuffer.length);
        this.readBuffer.set(chunk.subarray(0, n));
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        if (n < chunk.length) {
          this.pendingData.push(chunk.subarray(n));
        }
        resolve(n);
      } else {
        this.pendingData.push(chunk);
      }
    };

    ws.onclose = () => {
      this.eofReached = true;
      if (this.readResolve) {
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        resolve(0);
      }
    };

    ws.onerror = (err: Event | Error) => {
      if (this.readReject) {
        const reject = this.readReject;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        reject(err instanceof Error ? err : new Error("websocket error"));
      }
    };
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    if (this.pendingData.length > 0) {
      const chunk = this.pendingData[0];
      const n = Math.min(chunk.length, buffer.length);
      buffer.set(chunk.subarray(0, n));
      if (n < chunk.length) {
        this.pendingData[0] = chunk.subarray(n);
      } else {
        this.pendingData.shift();
      }
      return n;
    }

    if (this.eofReached) return 0;

    return new Promise<number>((resolve, reject) => {
      this.readResolve = resolve;
      this.readReject = reject;
      this.readBuffer = buffer;

      if (this.readDeadlineMs > 0) {
        const timer = setTimeout(() => {
          this.readResolve = null;
          this.readReject = null;
          this.readBuffer = null;
          reject(new TimeoutError("read"));
        }, this.readDeadlineMs);
        const origResolve = resolve;
        this.readResolve = (n: number) => {
          clearTimeout(timer);
          origResolve(n);
        };
      }
    });
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

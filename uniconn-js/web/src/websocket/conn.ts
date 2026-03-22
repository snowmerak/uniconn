import type { Addr, IConn } from "@uniconn/core";

/**
 * WebSocketConn ??IConn adapter for browser WebSocket API.
 *
 * Wraps the browser-native WebSocket into the uniconn IConn interface,
 * treating the WebSocket as a bidirectional binary stream.
 */
export class WebSocketConn implements IConn {
  private ws: WebSocket;
  private closed = false;
  private pendingData: Uint8Array[] = [];
  private readResolve: ((value: number) => void) | null = null;
  private readReject: ((reason: Error) => void) | null = null;
  private readBuffer: Uint8Array | null = null;
  private eofReached = false;
  private url: string;

  constructor(ws: WebSocket) {
    this.ws = ws;
    this.url = ws.url;
    ws.binaryType = "arraybuffer";

    ws.addEventListener("message", (ev: MessageEvent) => {
      const data = new Uint8Array(ev.data as ArrayBuffer);
      if (this.readResolve && this.readBuffer) {
        const n = Math.min(data.length, this.readBuffer.length);
        this.readBuffer.set(data.subarray(0, n));
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        if (n < data.length) {
          this.pendingData.push(data.subarray(n));
        }
        resolve(n);
      } else {
        this.pendingData.push(data);
      }
    });

    ws.addEventListener("close", () => {
      this.eofReached = true;
      if (this.readResolve) {
        const resolve = this.readResolve;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        resolve(0);
      }
    });

    ws.addEventListener("error", () => {
      const err = new Error("WebSocket error");
      if (this.readReject) {
        const reject = this.readReject;
        this.readResolve = null;
        this.readReject = null;
        this.readBuffer = null;
        reject(err);
      }
    });
  }

  /** Wait for the WebSocket to be open. */
  static connect(url: string): Promise<WebSocketConn> {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      ws.addEventListener("open", () => resolve(new WebSocketConn(ws)));
      ws.addEventListener("error", () => reject(new Error(`WS connect failed: ${url}`)));
    });
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new Error("connection closed");

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
    });
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new Error("connection closed");
    this.ws.send(data);
    return data.length;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.ws.close();
  }

  localAddr(): Addr {
    return { network: "websocket", address: "browser" };
  }

  remoteAddr(): Addr {
    return { network: "websocket", address: this.url };
  }

  setDeadline(_ms: number): void {}
  setReadDeadline(_ms: number): void {}
  setWriteDeadline(_ms: number): void {}
}

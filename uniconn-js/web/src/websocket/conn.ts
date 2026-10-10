import { ReadQueue, ConnectionClosedError } from "@uniconn/core";
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
  private reads = new ReadQueue();
  private readDeadlineMs = 0;
  private url: string;

  constructor(ws: WebSocket) {
    this.ws = ws;
    this.url = ws.url;
    ws.binaryType = "arraybuffer";

    ws.addEventListener("message", (ev: MessageEvent) => {
      this.reads.push(new Uint8Array(ev.data as ArrayBuffer));
    });
    ws.addEventListener("close", () => this.reads.end());
    ws.addEventListener("error", () => this.reads.fail(new Error("WebSocket error")));
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
    if (this.closed) throw new ConnectionClosedError();
    return this.reads.read(buffer, this.readDeadlineMs);
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new Error("connection closed");
    this.ws.send(data);
    return data.length;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    this.reads.fail(new ConnectionClosedError());
    this.ws.close();
  }

  localAddr(): Addr {
    return { network: "websocket", address: "browser" };
  }

  remoteAddr(): Addr {
    return { network: "websocket", address: this.url };
  }

  setDeadline(ms: number): void { this.readDeadlineMs = ms; }
  setReadDeadline(ms: number): void { this.readDeadlineMs = ms; }
  setWriteDeadline(_ms: number): void {}
}

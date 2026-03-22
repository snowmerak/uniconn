/**
 * WebTransport browser client adapter.
 *
 * This module provides an IConn implementation using the browser's
 * native WebTransport API. It wraps a single bidirectional stream
 * from a WebTransport session into the IConn interface.
 *
 * NOTE: This module only works in browser environments that support
 * the WebTransport API (Chrome 97+, Edge 97+).
 * Server-side WebTransport for Node.js is marked as TODO.
 */

import type { Addr, IConn, IDialer, DialOptions } from "@uniconn/core";
import { ConnectionClosedError, TimeoutError } from "@uniconn/core";

/**
 * WebTransportConn wraps a WebTransport bidirectional stream into IConn.
 */
export class WebTransportConn implements IConn {
  private session: WebTransport;
  private reader: ReadableStreamDefaultReader<Uint8Array>;
  private writer: WritableStreamDefaultWriter<Uint8Array>;
  private closed = false;
  private readDeadlineMs = 0;
  private writeDeadlineMs = 0;
  private pendingData: Uint8Array | null = null;
  private pendingOffset = 0;
  private url: string;

  constructor(
    session: WebTransport,
    reader: ReadableStreamDefaultReader<Uint8Array>,
    writer: WritableStreamDefaultWriter<Uint8Array>,
    url: string,
  ) {
    this.session = session;
    this.reader = reader;
    this.writer = writer;
    this.url = url;
  }

  async read(buffer: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    // Consume leftover from previous read
    if (this.pendingData) {
      const remaining = this.pendingData.length - this.pendingOffset;
      const n = Math.min(remaining, buffer.length);
      buffer.set(
        this.pendingData.subarray(this.pendingOffset, this.pendingOffset + n),
      );
      this.pendingOffset += n;
      if (this.pendingOffset >= this.pendingData.length) {
        this.pendingData = null;
        this.pendingOffset = 0;
      }
      return n;
    }

    const readPromise = this.reader.read().then(({ done, value }) => {
      if (done || !value) return 0;
      const n = Math.min(value.length, buffer.length);
      buffer.set(value.subarray(0, n));
      if (n < value.length) {
        this.pendingData = value;
        this.pendingOffset = n;
      }
      return n;
    });

    if (this.readDeadlineMs > 0) {
      return Promise.race([
        readPromise,
        new Promise<number>((_, reject) =>
          setTimeout(() => reject(new TimeoutError("read")), this.readDeadlineMs),
        ),
      ]);
    }

    return readPromise;
  }

  async write(data: Uint8Array): Promise<number> {
    if (this.closed) throw new ConnectionClosedError();

    const writePromise = this.writer.write(data).then(() => data.length);

    if (this.writeDeadlineMs > 0) {
      return Promise.race([
        writePromise,
        new Promise<number>((_, reject) =>
          setTimeout(
            () => reject(new TimeoutError("write")),
            this.writeDeadlineMs,
          ),
        ),
      ]);
    }

    return writePromise;
  }

  async close(): Promise<void> {
    if (this.closed) return;
    this.closed = true;
    try {
      this.reader.releaseLock();
    } catch { /* ignore */ }
    try {
      await this.writer.close();
    } catch { /* ignore */ }
    this.session.close();
  }

  localAddr(): Addr {
    return { network: "webtransport", address: "browser" };
  }

  remoteAddr(): Addr {
    return { network: "webtransport", address: this.url };
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
 * WebTransportDialer implements IDialer for browser WebTransport connections.
 *
 * This creates a WebTransport session and opens a single bidirectional stream,
 * following the "one connection = one session = one stream" model.
 */
export class WebTransportDialer implements IDialer {
  async dial(address: string, options?: DialOptions): Promise<IConn> {
    const transport = new WebTransport(address);

    if (options?.timeout) {
      const timer = setTimeout(() => transport.close(), options.timeout);
      transport.ready.then(() => clearTimeout(timer));
    }

    if (options?.signal) {
      if (options.signal.aborted) {
        transport.close();
        throw new Error("dial aborted");
      }
      options.signal.addEventListener(
        "abort",
        () => transport.close(),
        { once: true },
      );
    }

    await transport.ready;

    const stream = await transport.createBidirectionalStream();
    const reader = stream.readable.getReader();
    const writer = stream.writable.getWriter();

    return new WebTransportConn(transport, reader, writer, address);
  }
}

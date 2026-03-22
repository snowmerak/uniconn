/**
 * uniconn — Universal Connection Interface for Node.js
 *
 * This module defines the core IConn, IListener, and IDialer interfaces
 * that abstract various network protocols (TCP, WebSocket, QUIC,
 * WebTransport, KCP) behind a unified, net.Conn-inspired API.
 */

/** A network address descriptor. */
export interface Addr {
  /** Protocol name: "tcp", "websocket", "quic", "webtransport", "kcp" */
  readonly network: string;
  /** Address string: "127.0.0.1:8080", "wss://example.com/ws", etc. */
  readonly address: string;
}

/**
 * IConn — Universal connection interface, modeled after Go's net.Conn.
 *
 * Each protocol adapter implements this interface so that application
 * code can read, write, and close connections identically regardless
 * of the underlying transport.
 */
export interface IConn {
  /**
   * Read data into the provided buffer.
   * Resolves with the number of bytes read.
   * Resolves with 0 at EOF (peer closed the connection).
   */
  read(buffer: Uint8Array): Promise<number>;

  /**
   * Write data to the connection.
   * Resolves with the number of bytes written.
   */
  write(data: Uint8Array): Promise<number>;

  /** Close the connection. */
  close(): Promise<void>;

  /** Returns the local address. */
  localAddr(): Addr;

  /** Returns the remote address. */
  remoteAddr(): Addr;

  /**
   * Set both read and write timeout in milliseconds.
   * 0 means no timeout.
   */
  setDeadline(ms: number): void;

  /** Set read timeout in milliseconds. 0 means no timeout. */
  setReadDeadline(ms: number): void;

  /** Set write timeout in milliseconds. 0 means no timeout. */
  setWriteDeadline(ms: number): void;
}

/** IListener — Server-side listener interface. */
export interface IListener {
  /** Accept and return the next incoming connection. */
  accept(): Promise<IConn>;

  /** Stop listening and close the listener. */
  close(): Promise<void>;

  /** Returns the address the listener is bound to. */
  addr(): Addr;
}

/** Options for dialing a connection. */
export interface DialOptions {
  /** An AbortSignal to cancel the dial operation. */
  signal?: AbortSignal;
  /** Dial timeout in milliseconds. */
  timeout?: number;
}

/** IDialer — Client-side dialer interface. */
export interface IDialer {
  /** Establish a connection to the given address. */
  dial(address: string, options?: DialOptions): Promise<IConn>;
}

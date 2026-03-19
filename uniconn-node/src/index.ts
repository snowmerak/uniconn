// uniconn — Universal Connection Interface for Node.js
export type { Addr, IConn, IListener, IDialer, DialOptions } from "./conn.js";
export { TimeoutError, ConnectionClosedError, ListenerClosedError } from "./errors.js";

// Protocol adapters
export * as tcp from "./tcp/index.js";
export * as websocket from "./websocket/index.js";
// export * as quic from "./quic/index.js";       // TODO: node:quic is experimental
export * as webtransport from "./webtransport/index.js";
export * as kcp from "./kcp/index.js";

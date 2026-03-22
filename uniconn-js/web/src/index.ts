// @uniconn/web — Browser protocol adapters
export type { Addr, IConn, IDialer, DialOptions } from "@uniconn/core";
export { TimeoutError, ConnectionClosedError } from "@uniconn/core";
export { secure } from "@uniconn/core";

// Browser WebSocket
export { WebSocketConn } from "./websocket/conn.js";

// WebTransport
export * as webtransport from "./webtransport/index.js";

// Browser identity
export { BrowserIdentity, browserVerify } from "./secure/identity.js";

// @uniconn/node — Node.js protocol adapters
export type { Addr, IConn, IListener, IDialer, DialOptions } from "@uniconn/core";
export { TimeoutError, ConnectionClosedError, ListenerClosedError } from "@uniconn/core";
export { secure } from "@uniconn/core";

// Protocol adapters
export * as tcp from "./tcp/index.js";
export * as websocket from "./websocket/index.js";
export * as kcp from "./kcp/index.js";

// Node.js identity
export { NodeIdentity, nodeVerify } from "./secure/identity.js";

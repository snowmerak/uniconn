// @uniconn/core — shared interfaces and secure protocol
export type { Addr, IConn, IListener, IDialer, DialOptions } from "./conn.js";
export { TimeoutError, ConnectionClosedError, ListenerClosedError } from "./errors.js";

// Secure protocol — namespace
export * as secure from "./secure/index.js";

// Secure protocol — direct re-exports for convenience
export type { IIdentity, Fingerprint, VerifyFn } from "./secure/identity.js";
export { computeFingerprint } from "./secure/identity.js";
export { SecureConn } from "./secure/conn.js";
export { handshakeInitiator, handshakeResponder } from "./secure/handshake.js";

/**
 * USCP v1 — uniconn Secure Channel Protocol
 *
 * Platform-agnostic exports (work in both Node.js and browsers).
 *
 * Platform-specific identity modules should be imported directly:
 *   - Node.js:  import { NodeIdentity, nodeVerify } from "./secure/identity.node.js"
 *   - Browser:  import { BrowserIdentity, browserVerify } from "./secure/identity.browser.js"
 */
export type { IIdentity, Fingerprint, VerifyFn } from "./identity.js";
export { computeFingerprint } from "./identity.js";
export { SecureConn } from "./conn.js";
export { handshakeInitiator, handshakeResponder } from "./handshake.js";
export {
  FINGERPRINT_SIZE,
  KDF_OUTPUT_SIZE,
  KDF_CONTEXT,
  NONCE_SIZE,
  NONCE_PREFIX_SIZE,
  MSG_HELLO,
  MSG_HELLO_REPLY,
  MSG_DATA,
  MSG_ERROR,
} from "./constants.js";

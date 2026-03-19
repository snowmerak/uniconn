/**
 * USCP v1 — uniconn Secure Channel Protocol (Node.js implementation)
 *
 * E2EE using post-quantum cryptography:
 *   - ML-DSA-87 for identity/signing
 *   - ML-KEM-1024 for ephemeral key exchange
 *   - BLAKE3 for fingerprints and KDF
 *   - XChaCha20-Poly1305 for payload encryption
 */

export { Identity, Fingerprint, computeFingerprint } from "./identity.js";
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

import { blake3 } from "@noble/hashes/blake3.js";
import { FINGERPRINT_SIZE, MLDSA_CONTEXT } from "./constants.js";

/** 64-byte BLAKE3 fingerprint of an ML-DSA-87 public key. */
export type Fingerprint = Uint8Array; // 64 bytes

/**
 * Platform-agnostic identity interface.
 * Implemented by both Node.js (node:crypto) and browser (@noble/post-quantum) backends.
 */
export interface IIdentity {
  /** Raw ML-DSA-87 public key bytes (2592 bytes). */
  readonly publicKeyRaw: Uint8Array;
  /** Compute 64-byte BLAKE3 fingerprint. */
  fingerprint(): Fingerprint;
  /** Sign data with ML-DSA-87. */
  sign(data: Uint8Array): Uint8Array;
}

/**
 * Platform-agnostic verify interface.
 * Verifies ML-DSA-87 signature against raw public key bytes.
 */
export type VerifyFn = (sig: Uint8Array, data: Uint8Array, rawPublicKey: Uint8Array) => boolean;

/** Compute BLAKE3(raw_publicKey, 64). */
export function computeFingerprint(rawPublicKey: Uint8Array): Fingerprint {
  return blake3(rawPublicKey, { dkLen: FINGERPRINT_SIZE });
}

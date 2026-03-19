import { ml_dsa87 } from "@noble/post-quantum/ml-dsa.js";
import { computeFingerprint, type Fingerprint, type IIdentity } from "./identity.js";
import { MLDSA_CONTEXT } from "./constants.js";

/**
 * ML-DSA-87 identity using @noble/post-quantum (pure JavaScript).
 *
 * Works in any JavaScript runtime including web browsers.
 *
 * ⚠️ Performance note:
 *   - `generate()` is SLOW (~30-120s) because ML-DSA-87 keygen is computationally
 *     intensive in pure JS. Call it once and persist the keys.
 *   - `sign()` and `verify()` are fast (~10-50ms).
 *
 * For Node.js ≥ 25, prefer `NodeIdentity` from `identity.node.ts` for instant keygen.
 */
export class BrowserIdentity implements IIdentity {
  readonly publicKeyRaw: Uint8Array;
  private readonly secretKey: Uint8Array;

  constructor(publicKey: Uint8Array, secretKey: Uint8Array) {
    this.publicKeyRaw = publicKey;
    this.secretKey = secretKey;
  }

  /**
   * Generate a new ML-DSA-87 key pair.
   * ⚠️ This is SLOW in browser (~30-120 seconds). Generate once and persist.
   */
  static generate(): BrowserIdentity {
    const { publicKey, secretKey } = ml_dsa87.keygen();
    return new BrowserIdentity(publicKey, secretKey);
  }

  /**
   * Restore identity from previously exported keys.
   * Use this to avoid repeated slow keygen.
   */
  static fromKeys(publicKey: Uint8Array, secretKey: Uint8Array): BrowserIdentity {
    return new BrowserIdentity(publicKey, secretKey);
  }

  fingerprint(): Fingerprint {
    return computeFingerprint(this.publicKeyRaw);
  }

  sign(data: Uint8Array): Uint8Array {
    return ml_dsa87.sign(data, this.secretKey, { context: MLDSA_CONTEXT });
  }

  /** Export the secret key bytes for persistence (e.g. IndexedDB). */
  exportSecretKey(): Uint8Array {
    return this.secretKey.slice();
  }
}

/** Verify ML-DSA-87 signature using @noble/post-quantum (pure JS, browser-safe). */
export function browserVerify(sig: Uint8Array, data: Uint8Array, rawPublicKey: Uint8Array): boolean {
  return ml_dsa87.verify(sig, data, rawPublicKey, { context: MLDSA_CONTEXT });
}

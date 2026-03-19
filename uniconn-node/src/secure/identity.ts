import * as crypto from "node:crypto";
import { blake3 } from "@noble/hashes/blake3.js";
import { FINGERPRINT_SIZE } from "./constants.js";

/** 64-byte BLAKE3 fingerprint of an ML-DSA-87 public key. */
export type Fingerprint = Uint8Array; // 64 bytes

/**
 * Pre-computed SPKI DER header for ML-DSA-87 public keys.
 * This is the ASN.1 prefix before the raw 2592-byte key.
 * Extracted from Node.js crypto: `generateKeyPairSync('ml-dsa-87').publicKey.export()`.
 */
const MLDSA87_SPKI_HEADER = Buffer.from(
  "30820a32300b060960864801650304031303820a2100",
  "hex",
);
const MLDSA87_RAW_PUBKEY_SIZE = 2592;

/**
 * ML-DSA-87 identity using Node.js native crypto.
 *
 * Uses node:crypto generateKeyPairSync('ml-dsa-87') which is backed
 * by OpenSSL — orders of magnitude faster than pure-JS implementations.
 */
export class Identity {
  readonly publicKeyObj: crypto.KeyObject;
  readonly privateKeyObj: crypto.KeyObject;
  /** Raw ML-DSA-87 public key bytes (2592 bytes). */
  readonly publicKeyRaw: Uint8Array;

  constructor(publicKeyObj: crypto.KeyObject, privateKeyObj: crypto.KeyObject) {
    this.publicKeyObj = publicKeyObj;
    this.privateKeyObj = privateKeyObj;
    const spki = publicKeyObj.export({ type: "spki", format: "der" });
    this.publicKeyRaw = new Uint8Array(
      spki.subarray(spki.length - MLDSA87_RAW_PUBKEY_SIZE),
    );
  }

  /** Generate a new ML-DSA-87 identity. */
  static generate(): Identity {
    const kp = crypto.generateKeyPairSync("ml-dsa-87" as any);
    return new Identity(kp.publicKey, kp.privateKey);
  }

  /** Compute the 64-byte BLAKE3 fingerprint. */
  fingerprint(): Fingerprint {
    return computeFingerprint(this.publicKeyRaw);
  }

  /** Sign data with ML-DSA-87. */
  sign(data: Uint8Array): Uint8Array {
    return crypto.sign(null, data, this.privateKeyObj);
  }
}

/** Compute BLAKE3(raw_publicKey, 64). */
export function computeFingerprint(rawPublicKey: Uint8Array): Fingerprint {
  return blake3(rawPublicKey, { dkLen: FINGERPRINT_SIZE });
}

/** Verify an ML-DSA-87 signature using a KeyObject. */
export function verifyWithKey(
  sig: Uint8Array,
  data: Uint8Array,
  publicKeyObj: crypto.KeyObject,
): boolean {
  return crypto.verify(null, data, publicKeyObj, sig);
}

/** Import raw ML-DSA-87 public key (2592 bytes) → crypto.KeyObject. */
export function importRawPublicKey(raw: Uint8Array): crypto.KeyObject {
  const spki = Buffer.concat([MLDSA87_SPKI_HEADER, Buffer.from(raw)]);
  return crypto.createPublicKey({ key: spki, format: "der", type: "spki" });
}

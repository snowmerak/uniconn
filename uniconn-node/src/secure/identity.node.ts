import * as crypto from "node:crypto";
import { blake3 } from "@noble/hashes/blake3.js";
import { FINGERPRINT_SIZE } from "./constants.js";
import { computeFingerprint, type Fingerprint, type IIdentity } from "./identity.js";

/**
 * Pre-computed SPKI DER header for ML-DSA-87 public keys (22 bytes).
 * Extracted from Node.js crypto `generateKeyPairSync('ml-dsa-87')`.
 */
const MLDSA87_SPKI_HEADER = Buffer.from(
  "30820a32300b060960864801650304031303820a2100",
  "hex",
);
const MLDSA87_RAW_PUBKEY_SIZE = 2592;

/**
 * ML-DSA-87 identity using Node.js native crypto (OpenSSL-backed).
 * Instant keygen/sign/verify. Requires Node.js ≥ 25.
 */
export class NodeIdentity implements IIdentity {
  readonly publicKeyObj: crypto.KeyObject;
  readonly privateKeyObj: crypto.KeyObject;
  readonly publicKeyRaw: Uint8Array;

  constructor(publicKeyObj: crypto.KeyObject, privateKeyObj: crypto.KeyObject) {
    this.publicKeyObj = publicKeyObj;
    this.privateKeyObj = privateKeyObj;
    const spki = publicKeyObj.export({ type: "spki", format: "der" });
    this.publicKeyRaw = new Uint8Array(
      spki.subarray(spki.length - MLDSA87_RAW_PUBKEY_SIZE),
    );
  }

  static generate(): NodeIdentity {
    const kp = crypto.generateKeyPairSync("ml-dsa-87" as any);
    return new NodeIdentity(kp.publicKey, kp.privateKey);
  }

  fingerprint(): Fingerprint {
    return computeFingerprint(this.publicKeyRaw);
  }

  sign(data: Uint8Array): Uint8Array {
    return crypto.sign(null, data, this.privateKeyObj);
  }
}

/** Import raw ML-DSA-87 public key (2592 bytes) → crypto.KeyObject. */
function importRawPublicKey(raw: Uint8Array): crypto.KeyObject {
  const spki = Buffer.concat([MLDSA87_SPKI_HEADER, Buffer.from(raw)]);
  return crypto.createPublicKey({ key: spki, format: "der", type: "spki" });
}

/** Verify ML-DSA-87 signature using node:crypto (fast, OpenSSL-backed). */
export function nodeVerify(sig: Uint8Array, data: Uint8Array, rawPublicKey: Uint8Array): boolean {
  const pubKeyObj = importRawPublicKey(rawPublicKey);
  return crypto.verify(null, data, pubKeyObj, sig);
}

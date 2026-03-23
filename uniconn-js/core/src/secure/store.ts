/**
 * Identity store — encrypt/decrypt ML-DSA-87 keys with a master password.
 *
 * File format (cross-language compatible):
 *   [4B magic "UCID"] [1B version=0x01] [32B salt] [24B nonce]
 *   [encrypted(secretKey || publicKey) + 16B tag]
 *
 * KDF: Argon2id (t=3, m=64MB, p=4) → 32-byte symmetric key
 * AEAD: XChaCha20-Poly1305
 *
 * This module is platform-agnostic (no file I/O). It works with raw
 * bytes so both Node.js and browser can use it.
 */

import { argon2id } from "@noble/hashes/argon2.js";
import { XChaCha20Poly1305 } from "@stablelib/xchacha20poly1305";

const MAGIC = new TextEncoder().encode("UCID");
const VERSION = 0x01;
const SALT_SIZE = 32;
const NONCE_SIZE = 24;
const HEADER_SIZE = 4 + 1 + SALT_SIZE + NONCE_SIZE; // 61

// Argon2id parameters (must match Go and Python).
const ARGON_TIME = 3;
const ARGON_MEMORY = 64 * 1024; // 64 MB (in KiB)
const ARGON_PARALLELISM = 4;
const ARGON_KEY_LEN = 32;

// ML-DSA-87 key sizes.
const MLDSA87_SK_SIZE = 4896;
const MLDSA87_PK_SIZE = 2592;

/**
 * Encrypt identity keys into the UCID binary format.
 *
 * @param secretKey - Raw ML-DSA-87 secret key bytes (4896B).
 * @param publicKey - Raw ML-DSA-87 public key bytes (2592B).
 * @param password - Master password bytes.
 * @param randomBytes - Function to generate random bytes (platform-specific).
 * @returns Encrypted UCID binary data.
 */
export function encryptIdentity(
  secretKey: Uint8Array,
  publicKey: Uint8Array,
  password: Uint8Array,
  randomBytes: (size: number) => Uint8Array,
): Uint8Array {
  const plaintext = new Uint8Array(secretKey.length + publicKey.length);
  plaintext.set(secretKey);
  plaintext.set(publicKey, secretKey.length);

  const salt = randomBytes(SALT_SIZE);
  const nonce = randomBytes(NONCE_SIZE);

  const key = argon2id(password, salt, {
    t: ARGON_TIME,
    m: ARGON_MEMORY,
    p: ARGON_PARALLELISM,
    dkLen: ARGON_KEY_LEN,
  });

  const aead = new XChaCha20Poly1305(key);
  const ciphertext = aead.seal(nonce, plaintext);

  const out = new Uint8Array(HEADER_SIZE + ciphertext.length);
  out.set(MAGIC, 0);
  out[4] = VERSION;
  out.set(salt, 5);
  out.set(nonce, 5 + SALT_SIZE);
  out.set(ciphertext, HEADER_SIZE);

  return out;
}

/**
 * Decrypt identity keys from UCID binary data.
 *
 * @param data - UCID binary data.
 * @param password - Master password bytes.
 * @returns Object with secretKey and publicKey Uint8Array fields.
 */
export function decryptIdentity(
  data: Uint8Array,
  password: Uint8Array,
): { secretKey: Uint8Array; publicKey: Uint8Array } {
  if (data.length < HEADER_SIZE) {
    throw new Error(`file too short: ${data.length} bytes`);
  }

  // Validate magic.
  for (let i = 0; i < 4; i++) {
    if (data[i] !== MAGIC[i]) {
      throw new Error("invalid magic");
    }
  }
  if (data[4] !== VERSION) {
    throw new Error(`unsupported version: ${data[4]}`);
  }

  const salt = data.subarray(5, 5 + SALT_SIZE);
  const nonce = data.subarray(5 + SALT_SIZE, HEADER_SIZE);
  const ciphertext = data.subarray(HEADER_SIZE);

  const key = argon2id(password, salt, {
    t: ARGON_TIME,
    m: ARGON_MEMORY,
    p: ARGON_PARALLELISM,
    dkLen: ARGON_KEY_LEN,
  });

  const aead = new XChaCha20Poly1305(key);
  const plaintext = aead.open(nonce, ciphertext);
  if (!plaintext) {
    throw new Error("decrypt failed: wrong password or corrupted file");
  }

  const expectedSize = MLDSA87_SK_SIZE + MLDSA87_PK_SIZE;
  if (plaintext.length !== expectedSize) {
    throw new Error(
      `unexpected plaintext size: got ${plaintext.length}, want ${expectedSize}`,
    );
  }

  return {
    secretKey: plaintext.slice(0, MLDSA87_SK_SIZE),
    publicKey: plaintext.slice(MLDSA87_SK_SIZE),
  };
}

/** USCP v1 protocol constants. */

export const FINGERPRINT_SIZE = 64;
export const KDF_OUTPUT_SIZE = 88;
export const KDF_CONTEXT = "uniconn-e2ee-v1";
export const NONCE_SIZE = 24;
export const NONCE_PREFIX_SIZE = 12;
export const TIMESTAMP_SIZE = 4;
export const COUNTER_SIZE = 8;
export const TAG_SIZE = 16;
export const MAX_MESSAGE_SIZE = 16_777_216;

export const MSG_HELLO = 0x01;
export const MSG_HELLO_REPLY = 0x02;
export const MSG_DATA = 0x03;
export const MSG_ERROR = 0xff;

/** ML-DSA-87 context string for USCP signatures. Empty for cross-platform compat. */
export const MLDSA_CONTEXT = new Uint8Array(0);

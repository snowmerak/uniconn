import { MlKem1024 } from "mlkem";
import { blake3 } from "@noble/hashes/blake3.js";

import type { IConn } from "../conn.js";
import {
  computeFingerprint,
  type Fingerprint,
  type IIdentity,
  type VerifyFn,
} from "./identity.js";
import {
  MSG_HELLO,
  MSG_HELLO_REPLY,
  KDF_CONTEXT,
  KDF_OUTPUT_SIZE,
  NONCE_PREFIX_SIZE,
} from "./constants.js";
import {
  marshalHello,
  unmarshalHello,
  readFrame,
  writeFrame,
  type HelloMsg,
} from "./message.js";
import { SecureConn, type SessionKeys } from "./conn.js";

/** Derive session keys from ML-KEM shared secret using BLAKE3. */
function deriveKeys(sharedSecret: Uint8Array): SessionKeys {
  const ctxBytes = new TextEncoder().encode(KDF_CONTEXT);
  const combined = new Uint8Array(ctxBytes.length + sharedSecret.length);
  combined.set(ctxBytes);
  combined.set(sharedSecret, ctxBytes.length);
  const out = blake3(combined, { dkLen: KDF_OUTPUT_SIZE });

  return {
    initiatorKey: out.slice(0, 32),
    responderKey: out.slice(32, 64),
    initiatorNoncePfx: out.slice(64, 64 + NONCE_PREFIX_SIZE),
    responderNoncePfx: out.slice(64 + NONCE_PREFIX_SIZE, KDF_OUTPUT_SIZE),
  };
}

const kem = new MlKem1024();

/**
 * Perform the initiator side of the USCP handshake.
 *
 * @param conn  - Transport connection (TCP, WebSocket, WebTransport, etc.)
 * @param id    - Local identity (NodeIdentity or BrowserIdentity)
 * @param peerFP - Expected 64-byte fingerprint of the peer
 * @param verify - Platform-specific verify function (nodeVerify or browserVerify)
 */
export async function handshakeInitiator(
  conn: IConn,
  id: IIdentity,
  peerFP: Fingerprint,
  verify: VerifyFn,
): Promise<SecureConn> {
  // 1. Ephemeral ML-KEM-1024.
  const [ek, dk] = await kem.generateKeyPair();

  // 2. Sign raw ek.
  const sig = id.sign(ek);

  // 3. Send HELLO.
  const hello: HelloMsg = {
    type: MSG_HELLO,
    publicKey: id.publicKeyRaw,
    payload: ek,
    signature: sig,
  };
  await writeFrame(conn, marshalHello(hello));

  // 4. Receive HELLO_REPLY.
  const replyBody = await readFrame(conn);
  const reply = unmarshalHello(replyBody);
  if (reply.type !== MSG_HELLO_REPLY) {
    throw new Error(
      `expected HELLO_REPLY (0x${MSG_HELLO_REPLY.toString(16)}), got 0x${reply.type.toString(16)}`,
    );
  }

  // 5. Verify peer.
  const gotFP = computeFingerprint(reply.publicKey);
  if (!equalBytes(gotFP, peerFP)) {
    throw new Error("fingerprint mismatch");
  }
  if (!verify(reply.signature, reply.payload, reply.publicKey)) {
    throw new Error("signature verification failed");
  }

  // 6. Decapsulate.
  const sharedSecret = await kem.decap(reply.payload, dk);

  // 7. Derive keys.
  const keys = deriveKeys(sharedSecret);
  return new SecureConn(conn, keys, true);
}

/**
 * Perform the responder side of the USCP handshake.
 *
 * @param conn   - Transport connection
 * @param id     - Local identity
 * @param peerFP - Expected peer fingerprint
 * @param verify - Platform-specific verify function
 */
export async function handshakeResponder(
  conn: IConn,
  id: IIdentity,
  peerFP: Fingerprint,
  verify: VerifyFn,
): Promise<SecureConn> {
  // 1. Receive HELLO.
  const helloBody = await readFrame(conn);
  const hello = unmarshalHello(helloBody);
  if (hello.type !== MSG_HELLO) {
    throw new Error(
      `expected HELLO (0x${MSG_HELLO.toString(16)}), got 0x${hello.type.toString(16)}`,
    );
  }

  // 2. Verify peer.
  const gotFP = computeFingerprint(hello.publicKey);
  if (!equalBytes(gotFP, peerFP)) {
    throw new Error("fingerprint mismatch");
  }
  if (!verify(hello.signature, hello.payload, hello.publicKey)) {
    throw new Error("signature verification failed");
  }

  // 3. Encapsulate.
  const [ct, sharedSecret] = await kem.encap(hello.payload);

  // 4. Sign ct.
  const sig = id.sign(ct);

  // 5. Send HELLO_REPLY.
  const reply: HelloMsg = {
    type: MSG_HELLO_REPLY,
    publicKey: id.publicKeyRaw,
    payload: ct,
    signature: sig,
  };
  await writeFrame(conn, marshalHello(reply));

  // 6. Derive keys.
  const keys = deriveKeys(sharedSecret);
  return new SecureConn(conn, keys, false);
}

/** Constant-time byte comparison. */
function equalBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a[i] ^ b[i];
  }
  return diff === 0;
}

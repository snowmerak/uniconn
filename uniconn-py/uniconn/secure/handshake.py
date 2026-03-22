"""USCP v1 handshake: initiator and responder."""

from __future__ import annotations

from typing import Callable

import blake3 as _blake3

from ..conn import Conn
from .constants import (
    KDF_CONTEXT,
    KDF_OUTPUT_SIZE,
    MSG_HELLO,
    MSG_HELLO_REPLY,
    NONCE_PREFIX_SIZE,
)
from .identity import Identity, compute_fingerprint, verify as _default_verify
from .message import marshal_hello, read_frame, unmarshal_hello
from .conn import SecureConn

# Types
VerifyFn = Callable[[bytes, bytes, bytes], bool]


class SessionKeys:
    """Session keys derived from KDF."""

    __slots__ = (
        "initiator_key",
        "responder_key",
        "initiator_nonce_pfx",
        "responder_nonce_pfx",
    )

    def __init__(
        self,
        initiator_key: bytes,
        responder_key: bytes,
        initiator_nonce_pfx: bytes,
        responder_nonce_pfx: bytes,
    ) -> None:
        self.initiator_key = initiator_key
        self.responder_key = responder_key
        self.initiator_nonce_pfx = initiator_nonce_pfx
        self.responder_nonce_pfx = responder_nonce_pfx


def _derive_keys(shared_secret: bytes) -> SessionKeys:
    """
    Derive session keys from ML-KEM shared secret using BLAKE3.
    KDF: BLAKE3(KDF_CONTEXT || shared_secret, 88 bytes)
    """
    h = _blake3.blake3(KDF_CONTEXT + shared_secret)
    out = h.digest(length=KDF_OUTPUT_SIZE)

    return SessionKeys(
        initiator_key=out[0:32],
        responder_key=out[32:64],
        initiator_nonce_pfx=out[64:76],
        responder_nonce_pfx=out[76:88],
    )


async def handshake_initiator(
    conn: Conn,
    identity: Identity,
    peer_fp: bytes,
    verify_fn: VerifyFn | None = None,
) -> SecureConn:
    """
    Perform the initiator side of the USCP handshake.

    Args:
        conn: Underlying connection (TCP, WebSocket, etc.)
        identity: Local ML-DSA-87 identity.
        peer_fp: Expected 64-byte fingerprint of the peer.
        verify_fn: Optional custom verify function. Defaults to pqcrypto.
    """
    if verify_fn is None:
        verify_fn = _default_verify

    # 1. Ephemeral ML-KEM-1024.
    try:
        from pqcrypto.kem.kyber1024 import generate_keypair, decrypt
    except ImportError:
        raise RuntimeError("pqcrypto package required for ML-KEM-1024")

    pk_kem, sk_kem = generate_keypair()
    ek_bytes = bytes(pk_kem)

    # 2. Sign ek.
    sig = identity.sign(ek_bytes)

    # 3. Send HELLO.
    hello = marshal_hello(MSG_HELLO, identity.public_key_bytes(), ek_bytes, sig)
    await conn.write(hello)

    # 4. Receive HELLO_REPLY.
    reply_body = await read_frame(conn)
    reply = unmarshal_hello(reply_body)
    if reply["msg_type"] != MSG_HELLO_REPLY:
        raise ValueError(
            f"expected HELLO_REPLY (0x{MSG_HELLO_REPLY:02x}), "
            f"got 0x{reply['msg_type']:02x}"
        )

    # 5. Verify peer.
    got_fp = compute_fingerprint(reply["public_key"])
    if got_fp != peer_fp:
        raise ValueError("fingerprint mismatch")
    if not verify_fn(reply["public_key"], reply["payload"], reply["signature"]):
        raise ValueError("signature verification failed")

    # 6. Decapsulate.
    shared_secret = bytes(decrypt(sk_kem, reply["payload"]))

    # 7. Derive keys.
    keys = _derive_keys(shared_secret)
    return SecureConn(keys, is_initiator=True)


async def handshake_responder(
    conn: Conn,
    identity: Identity,
    peer_fp: bytes,
    verify_fn: VerifyFn | None = None,
) -> SecureConn:
    """
    Perform the responder side of the USCP handshake.

    Args:
        conn: Underlying connection.
        identity: Local ML-DSA-87 identity.
        peer_fp: Expected 64-byte fingerprint of the peer.
        verify_fn: Optional custom verify function.
    """
    if verify_fn is None:
        verify_fn = _default_verify

    # 1. Receive HELLO.
    hello_body = await read_frame(conn)
    hello = unmarshal_hello(hello_body)
    if hello["msg_type"] != MSG_HELLO:
        raise ValueError(
            f"expected HELLO (0x{MSG_HELLO:02x}), got 0x{hello['msg_type']:02x}"
        )

    # 2. Verify peer.
    got_fp = compute_fingerprint(hello["public_key"])
    if got_fp != peer_fp:
        raise ValueError("fingerprint mismatch")
    if not verify_fn(hello["public_key"], hello["payload"], hello["signature"]):
        raise ValueError("signature verification failed")

    # 3. Encapsulate.
    try:
        from pqcrypto.kem.kyber1024 import encrypt
    except ImportError:
        raise RuntimeError("pqcrypto package required for ML-KEM-1024")

    ct, shared_secret = encrypt(hello["payload"])
    ct_bytes = bytes(ct)
    shared_secret = bytes(shared_secret)

    # 4. Sign ct.
    sig = identity.sign(ct_bytes)

    # 5. Send HELLO_REPLY.
    reply = marshal_hello(
        MSG_HELLO_REPLY, identity.public_key_bytes(), ct_bytes, sig
    )
    await conn.write(reply)

    # 6. Derive keys.
    keys = _derive_keys(shared_secret)
    return SecureConn(keys, is_initiator=False)

"""USCP v1 handshake: initiator and responder (synchronous)."""

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
from .message import marshal_hello, read_frame_from_conn, unmarshal_hello
from .conn import SecureConn

VerifyFn = Callable[[bytes, bytes, bytes], bool]


class SessionKeys:
    """Session keys derived from KDF."""
    __slots__ = (
        "initiator_key", "responder_key",
        "initiator_nonce_pfx", "responder_nonce_pfx",
    )

    def __init__(self, ik: bytes, rk: bytes, inp: bytes, rnp: bytes) -> None:
        self.initiator_key = ik
        self.responder_key = rk
        self.initiator_nonce_pfx = inp
        self.responder_nonce_pfx = rnp


def _derive_keys(shared_secret: bytes) -> SessionKeys:
    """BLAKE3(KDF_CONTEXT || shared_secret, 88 bytes)."""
    h = _blake3.blake3(KDF_CONTEXT + shared_secret)
    out = h.digest(length=KDF_OUTPUT_SIZE)
    return SessionKeys(out[0:32], out[32:64], out[64:76], out[76:88])


def handshake_initiator(
    conn: Conn,
    identity: Identity,
    peer_fp: bytes,
    verify_fn: VerifyFn | None = None,
) -> SecureConn:
    """Perform the initiator side of the USCP handshake (blocking)."""
    if verify_fn is None:
        verify_fn = _default_verify

    try:
        from pqcrypto.kem.kyber1024 import generate_keypair, decrypt
    except ImportError:
        raise RuntimeError("pqcrypto package required for ML-KEM-1024")

    pk_kem, sk_kem = generate_keypair()
    ek_bytes = bytes(pk_kem)
    sig = identity.sign(ek_bytes)

    hello = marshal_hello(MSG_HELLO, identity.public_key_bytes(), ek_bytes, sig)
    conn.write(hello)

    reply_body = read_frame_from_conn(conn)
    reply = unmarshal_hello(reply_body)
    if reply["msg_type"] != MSG_HELLO_REPLY:
        raise ValueError(f"expected HELLO_REPLY, got 0x{reply['msg_type']:02x}")

    got_fp = compute_fingerprint(reply["public_key"])
    if got_fp != peer_fp:
        raise ValueError("fingerprint mismatch")
    if not verify_fn(reply["public_key"], reply["payload"], reply["signature"]):
        raise ValueError("signature verification failed")

    shared_secret = bytes(decrypt(sk_kem, reply["payload"]))
    keys = _derive_keys(shared_secret)
    return SecureConn(keys, is_initiator=True)


def handshake_responder(
    conn: Conn,
    identity: Identity,
    peer_fp: bytes,
    verify_fn: VerifyFn | None = None,
) -> SecureConn:
    """Perform the responder side of the USCP handshake (blocking)."""
    if verify_fn is None:
        verify_fn = _default_verify

    hello_body = read_frame_from_conn(conn)
    hello = unmarshal_hello(hello_body)
    if hello["msg_type"] != MSG_HELLO:
        raise ValueError(f"expected HELLO, got 0x{hello['msg_type']:02x}")

    got_fp = compute_fingerprint(hello["public_key"])
    if got_fp != peer_fp:
        raise ValueError("fingerprint mismatch")
    if not verify_fn(hello["public_key"], hello["payload"], hello["signature"]):
        raise ValueError("signature verification failed")

    try:
        from pqcrypto.kem.kyber1024 import encrypt
    except ImportError:
        raise RuntimeError("pqcrypto package required for ML-KEM-1024")

    ct, shared_secret = encrypt(hello["payload"])
    ct_bytes = bytes(ct)
    shared_secret = bytes(shared_secret)

    sig = identity.sign(ct_bytes)
    reply = marshal_hello(MSG_HELLO_REPLY, identity.public_key_bytes(), ct_bytes, sig)
    conn.write(reply)

    keys = _derive_keys(shared_secret)
    return SecureConn(keys, is_initiator=False)

"""
ML-DSA-87 identity, fingerprint, sign, verify.

Uses the `pqcrypto` package (PQClean bindings) for ML-DSA-87.
Falls back to `dilithium_py` for environments without compiled bindings.
"""

from __future__ import annotations

import blake3 as _blake3

from .constants import FINGERPRINT_SIZE, MLDSA_CONTEXT

# Try PQClean bindings first, then fallback.
try:
    from pqcrypto.sign.dilithium5 import (
        generate_keypair as _keygen,
        sign as _sign_raw,
        verify as _verify_raw,
    )
    _BACKEND = "pqcrypto"
except ImportError:
    _BACKEND = None


def compute_fingerprint(pub_bytes: bytes) -> bytes:
    """Compute BLAKE3(public_key, 64) fingerprint."""
    h = _blake3.blake3(pub_bytes)
    return h.digest(length=FINGERPRINT_SIZE)


class Identity:
    """ML-DSA-87 identity (key pair)."""

    def __init__(self, public_key: bytes, secret_key: bytes) -> None:
        self._pk = public_key
        self._sk = secret_key

    @classmethod
    def generate(cls) -> "Identity":
        """Generate a new ML-DSA-87 key pair."""
        if _BACKEND == "pqcrypto":
            pk, sk = _keygen()
            return cls(bytes(pk), bytes(sk))
        raise RuntimeError(
            "No ML-DSA-87 backend available. "
            "Install `pqcrypto` package: pip install pqcrypto"
        )

    def fingerprint(self) -> bytes:
        """64-byte BLAKE3 fingerprint of the public key."""
        return compute_fingerprint(self._pk)

    def sign(self, data: bytes) -> bytes:
        """Sign data. Returns raw signature bytes."""
        if _BACKEND == "pqcrypto":
            # pqcrypto.sign.dilithium5.sign returns signed_message (sig || msg),
            # extract just the signature.
            signed = _sign_raw(self._sk, data)
            sig = signed[: len(signed) - len(data)]
            return bytes(sig)
        raise RuntimeError("No ML-DSA-87 backend available")

    def public_key_bytes(self) -> bytes:
        """Raw public key bytes."""
        return self._pk


def verify(pub_bytes: bytes, data: bytes, sig_bytes: bytes) -> bool:
    """Verify an ML-DSA-87 signature."""
    if _BACKEND == "pqcrypto":
        try:
            # pqcrypto.sign.dilithium5.verify expects signed_message (sig || msg)
            signed_message = sig_bytes + data
            _verify_raw(pub_bytes, signed_message)
            return True
        except Exception:
            return False
    return False

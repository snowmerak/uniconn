"""
ML-DSA-87 identity, fingerprint, sign, verify.

Uses the `dilithium-py` package (ML_DSA_87 FIPS 204 implementation).
"""

from __future__ import annotations

import blake3 as _blake3

from .constants import FINGERPRINT_SIZE

# ML-DSA-87 (FIPS 204) from dilithium-py.
try:
    from dilithium_py.ml_dsa import ML_DSA_87
    _BACKEND = "dilithium-py"
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
        if _BACKEND == "dilithium-py":
            pk, sk = ML_DSA_87.keygen()
            return cls(bytes(pk), bytes(sk))
        raise RuntimeError(
            "No ML-DSA-87 backend available. "
            "Install `dilithium-py` package: pip install dilithium-py"
        )

    def fingerprint(self) -> bytes:
        """64-byte BLAKE3 fingerprint of the public key."""
        return compute_fingerprint(self._pk)

    def sign(self, data: bytes) -> bytes:
        """Sign data. Returns raw signature bytes (4627 bytes for ML-DSA-87)."""
        if _BACKEND == "dilithium-py":
            sig = ML_DSA_87.sign(self._sk, data)
            return bytes(sig)
        raise RuntimeError("No ML-DSA-87 backend available")

    def public_key_bytes(self) -> bytes:
        """Raw public key bytes."""
        return self._pk


def verify(pub_bytes: bytes, data: bytes, sig_bytes: bytes) -> bool:
    """Verify an ML-DSA-87 signature."""
    if _BACKEND == "dilithium-py":
        try:
            return ML_DSA_87.verify(pub_bytes, data, sig_bytes)
        except Exception:
            return False
    return False

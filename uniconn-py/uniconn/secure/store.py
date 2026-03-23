"""
Identity file store — save/load ML-DSA-87 keys encrypted with a master password.

File format (cross-language compatible):
    [4B magic "UCID"] [1B version=0x01] [32B salt] [24B nonce]
    [encrypted(secretKey || publicKey) + 16B tag]

KDF: Argon2id (t=3, m=64MB, p=4) -> 32-byte symmetric key
AEAD: XChaCha20-Poly1305
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

from Crypto.Cipher import ChaCha20_Poly1305
from argon2.low_level import Type, hash_secret_raw

from .identity import Identity

# File format constants.
_MAGIC = b"UCID"
_VERSION = 0x01
_SALT_SIZE = 32
_NONCE_SIZE = 24
_TAG_SIZE = 16
_HEADER_SIZE = 4 + 1 + _SALT_SIZE + _NONCE_SIZE  # 61

# Argon2id parameters (must match Go and Node.js).
_ARGON_TIME = 3
_ARGON_MEMORY = 64 * 1024  # 64 MB (in KiB)
_ARGON_PARALLELISM = 4
_ARGON_KEY_LEN = 32

# ML-DSA-87 key sizes.
_MLDSA87_SK_SIZE = 4896
_MLDSA87_PK_SIZE = 2592


def save_identity(path: str | Path, identity: Identity, password: bytes) -> None:
    """Encrypt and save an Identity to a file.

    Args:
        path: File path to write.
        identity: ML-DSA-87 identity to save.
        password: Master password bytes.
    """
    sk = identity._sk
    pk = identity._pk
    plaintext = sk + pk

    salt = os.urandom(_SALT_SIZE)
    nonce = os.urandom(_NONCE_SIZE)

    key = hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=_ARGON_TIME,
        memory_cost=_ARGON_MEMORY,
        parallelism=_ARGON_PARALLELISM,
        hash_len=_ARGON_KEY_LEN,
        type=Type.ID,
    )

    cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    header = _MAGIC + struct.pack("B", _VERSION) + salt + nonce
    data = header + ciphertext + tag

    Path(path).write_bytes(data)


def load_identity(path: str | Path, password: bytes) -> Identity:
    """Load and decrypt an Identity from a file.

    Args:
        path: File path to read.
        password: Master password bytes.

    Returns:
        Restored Identity.

    Raises:
        ValueError: If the file is corrupted or the password is wrong.
    """
    data = Path(path).read_bytes()

    if len(data) < _HEADER_SIZE:
        raise ValueError(f"file too short: {len(data)} bytes")

    if data[:4] != _MAGIC:
        raise ValueError(f"invalid magic: {data[:4]!r}")

    version = data[4]
    if version != _VERSION:
        raise ValueError(f"unsupported version: {version}")

    salt = data[5 : 5 + _SALT_SIZE]
    nonce = data[5 + _SALT_SIZE : _HEADER_SIZE]
    payload = data[_HEADER_SIZE:]

    if len(payload) < _TAG_SIZE:
        raise ValueError("file too short: no tag")

    ciphertext = payload[:-_TAG_SIZE]
    tag = payload[-_TAG_SIZE:]

    key = hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=_ARGON_TIME,
        memory_cost=_ARGON_MEMORY,
        parallelism=_ARGON_PARALLELISM,
        hash_len=_ARGON_KEY_LEN,
        type=Type.ID,
    )

    cipher = ChaCha20_Poly1305.new(key=key, nonce=nonce)
    try:
        plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError:
        raise ValueError("decrypt failed: wrong password or corrupted file")

    expected_size = _MLDSA87_SK_SIZE + _MLDSA87_PK_SIZE
    if len(plaintext) != expected_size:
        raise ValueError(
            f"unexpected plaintext size: got {len(plaintext)}, want {expected_size}"
        )

    sk = plaintext[:_MLDSA87_SK_SIZE]
    pk = plaintext[_MLDSA87_SK_SIZE:]

    return Identity(bytes(pk), bytes(sk))

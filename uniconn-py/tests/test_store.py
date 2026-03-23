"""Tests for identity store (save/load with password encryption)."""

import os
import tempfile

import pytest

from uniconn.secure.identity import Identity
from uniconn.secure.store import save_identity, load_identity


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_save_load_roundtrip(tmp_dir):
    """Save and load an identity, verify fingerprint and sign/verify."""
    identity = Identity.generate()
    path = os.path.join(tmp_dir, "test.ucid")
    password = b"super-secret-password"

    save_identity(path, identity, password)

    # File should exist.
    assert os.path.getsize(path) > 0

    loaded = load_identity(path, password)

    # Fingerprints must match.
    assert identity.fingerprint() == loaded.fingerprint()

    # Public keys must match.
    assert identity.public_key_bytes() == loaded.public_key_bytes()

    # Sign with loaded key, verify with original.
    msg = b"test message for signing"
    sig = loaded.sign(msg)

    from uniconn.secure.identity import verify
    assert verify(loaded.public_key_bytes(), msg, sig)
    assert verify(identity.public_key_bytes(), msg, sig)


def test_wrong_password(tmp_dir):
    """Reject decryption with wrong password."""
    identity = Identity.generate()
    path = os.path.join(tmp_dir, "test.ucid")

    save_identity(path, identity, b"correct")

    with pytest.raises(ValueError, match="decrypt failed"):
        load_identity(path, b"wrong")


def test_corrupted_file(tmp_dir):
    """Reject corrupted or truncated files."""
    path = os.path.join(tmp_dir, "test.ucid")

    # Truncated.
    with open(path, "wb") as f:
        f.write(b"UCID")
    with pytest.raises(ValueError, match="file too short"):
        load_identity(path, b"pw")

    # Invalid magic.
    with open(path, "wb") as f:
        f.write(b"\x00" * 200)
    with pytest.raises(ValueError, match="invalid magic"):
        load_identity(path, b"pw")

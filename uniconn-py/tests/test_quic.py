"""Unit tests for uniconn QUIC adapter (async)."""

import asyncio
import pytest
import tempfile
import os

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
import datetime


@pytest.fixture(scope="module")
def tls_certs():
    """Generate self-signed TLS certificate and key for QUIC tests."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        cert_path = os.path.join(tmpdir, "cert.pem")
        key_path = os.path.join(tmpdir, "key.pem")

        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))

        yield cert_path, key_path


import ipaddress

from uniconn.quic import QuicListener, QuicDialer


@pytest.mark.asyncio
async def test_quic_echo(tls_certs):
    """QUIC: dialer sends data, listener echoes back."""
    cert_path, key_path = tls_certs

    listener = await QuicListener.bind(
        "127.0.0.1", 0,
        certificate_chain=cert_path,
        private_key=key_path,
    )
    port = int(listener.addr().address.split(":")[-1])

    async def server():
        conn = await listener.accept()
        buf = bytearray(1024)
        n = await conn.read(buf)
        await conn.write(bytes(buf[:n]))
        await conn.close()

    task = asyncio.create_task(server())

    dialer = QuicDialer(verify_mode=False)
    conn = await dialer.dial(f"127.0.0.1:{port}")

    test_data = b"hello, uniconn Python QUIC!"
    await conn.write(test_data)

    buf = bytearray(1024)
    n = await conn.read(buf)
    assert buf[:n] == test_data

    await conn.close()
    await task
    await listener.close()

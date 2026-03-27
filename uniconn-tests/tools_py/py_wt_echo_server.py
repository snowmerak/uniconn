"""Standalone Python WebTransport echo server for browser testing.

Usage:
    python py_wt_echo_server.py [port]

Generates a self-signed cert, starts WT echo server, prints JSON to stdout:
    {"port": <int>, "cert_hash": "<hex>"}

Then echoes all data received on WT bidi streams.
"""

import asyncio
import datetime
import hashlib
import ipaddress
import json
import os
import sys
import tempfile

# Add uniconn-py to path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "uniconn-py"))

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def generate_cert():
    """Generate self-signed cert, return (cert_path, key_path, sha256_hex)."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
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
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_hash = hashlib.sha256(cert_der).hexdigest()

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )

    td = tempfile.gettempdir()
    cert_path = os.path.join(td, "py_wt_cert.pem")
    key_path = os.path.join(td, "py_wt_key.pem")
    open(cert_path, "wb").write(cert_pem)
    open(key_path, "wb").write(key_pem)
    return cert_path, key_path, cert_hash


async def echo_handler(conn):
    """Echo all data back."""
    try:
        buf = bytearray(65536)
        while True:
            n = await conn.read(buf)
            if n == 0:
                break
            await conn.write(bytes(buf[:n]))
    except Exception:
        pass
    finally:
        await conn.close()


async def main():
    from uniconn.webtransport import WebTransportListener

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    cert_path, key_path, cert_hash = generate_cert()

    listener = await WebTransportListener.bind(
        "127.0.0.1", port,
        certificate_chain=cert_path,
        private_key=key_path,
    )

    actual_port = int(listener.addr().address.split(":")[-1])
    info = {"port": actual_port, "cert_hash": cert_hash}
    print(json.dumps(info), flush=True)

    while True:
        conn = await listener.accept()
        asyncio.create_task(echo_handler(conn))


if __name__ == "__main__":
    asyncio.run(main())

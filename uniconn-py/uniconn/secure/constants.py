"""USCP v1 protocol constants."""

# Message types.
MSG_HELLO = 0x01
MSG_HELLO_REPLY = 0x02
MSG_DATA = 0x03
MSG_ERROR = 0xFF

# Sizes.
FINGERPRINT_SIZE = 64
KDF_OUTPUT_SIZE = 88
NONCE_SIZE = 24
NONCE_PREFIX_SIZE = 12
TIMESTAMP_SIZE = 4
COUNTER_SIZE = 8
TAG_SIZE = 16
MAX_MESSAGE_SIZE = 16_777_216

# KDF context string.
KDF_CONTEXT = b"uniconn-e2ee-v1"

# ML-DSA context — empty (&[]) for Go cross-platform compat.
MLDSA_CONTEXT = b""

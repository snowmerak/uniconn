// Package secure implements the uniconn Secure Channel Protocol (USCP) v1.
//
// It provides end-to-end encryption using post-quantum cryptography:
//   - ML-DSA-87 for identity and signing
//   - ML-KEM-1024 for ephemeral key exchange
//   - BLAKE3 for fingerprints and key derivation
//   - XChaCha20-Poly1305 for payload encryption
package secure

import (
	"crypto/rand"
	"fmt"

	"github.com/cloudflare/circl/sign/mldsa/mldsa87"
	"lukechampine.com/blake3"
)

// ML-DSA-87 context: nil (empty) for cross-platform compat with Node.js node:crypto.

// Fingerprint is a 64-byte BLAKE3 hash of an ML-DSA-87 public key.
type Fingerprint [FingerprintSize]byte

// AnyFingerprint is an all-zero fingerprint used by public servers to accept any peer.
var AnyFingerprint Fingerprint

// Identity holds an ML-DSA-87 key pair for signing and authentication.
type Identity struct {
	PublicKey  *mldsa87.PublicKey
	PrivateKey *mldsa87.PrivateKey
}

// GenerateIdentity creates a new ML-DSA-87 key pair.
func GenerateIdentity() (*Identity, error) {
	pub, priv, err := mldsa87.GenerateKey(rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("mldsa87 keygen: %w", err)
	}
	return &Identity{PublicKey: pub, PrivateKey: priv}, nil
}

// Fingerprint computes BLAKE3(public_key, 64) as the identity fingerprint.
func (id *Identity) Fingerprint() Fingerprint {
	return ComputeFingerprint(id.PublicKey)
}

// ComputeFingerprint computes BLAKE3(public_key, 64).
func ComputeFingerprint(pub *mldsa87.PublicKey) Fingerprint {
	raw, _ := pub.MarshalBinary()
	return computeFingerprintBytes(raw)
}

func computeFingerprintBytes(pubBytes []byte) Fingerprint {
	h := blake3.New(FingerprintSize, nil)
	h.Write(pubBytes)
	var fp Fingerprint
	copy(fp[:], h.Sum(nil))
	return fp
}

// Sign signs the given data with the identity's private key.
func (id *Identity) Sign(data []byte) ([]byte, error) {
	sig := make([]byte, mldsa87.SignatureSize)
	if err := mldsa87.SignTo(id.PrivateKey, data, nil, false, sig); err != nil {
		return nil, fmt.Errorf("mldsa87 sign: %w", err)
	}
	return sig, nil
}

// Verify verifies a signature against a public key and data.
func Verify(pub *mldsa87.PublicKey, data, sig []byte) bool {
	return mldsa87.Verify(pub, data, nil, sig)
}

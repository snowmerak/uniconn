package secure

import (
	"crypto/rand"
	"fmt"
	"os"

	"github.com/cloudflare/circl/sign/mldsa/mldsa87"
	"golang.org/x/crypto/argon2"
	"golang.org/x/crypto/chacha20poly1305"
)

// Store file format constants.
const (
	storeMagic   = "UCID"
	storeVersion = 0x01

	// Header: magic(4) + version(1) + salt(32) + nonce(24) = 61 bytes.
	storeSaltSize   = 32
	storeNonceSize  = 24
	storeHeaderSize = 4 + 1 + storeSaltSize + storeNonceSize

	// Argon2id parameters.
	argonTime    = 3
	argonMemory  = 64 * 1024 // 64 MB
	argonThreads = 4
	argonKeyLen  = 32
)

// SaveIdentity encrypts an Identity with a master password and writes it to path.
//
// File format: [4B "UCID"] [1B version] [32B salt] [24B nonce] [ciphertext + 16B tag]
// where plaintext = privateKey || publicKey (ML-DSA-87).
func SaveIdentity(path string, id *Identity, password []byte) error {
	privBytes, err := id.PrivateKey.MarshalBinary()
	if err != nil {
		return fmt.Errorf("marshal private key: %w", err)
	}
	pubBytes, err := id.PublicKey.MarshalBinary()
	if err != nil {
		return fmt.Errorf("marshal public key: %w", err)
	}

	plaintext := make([]byte, len(privBytes)+len(pubBytes))
	copy(plaintext, privBytes)
	copy(plaintext[len(privBytes):], pubBytes)

	// Generate salt and nonce.
	var salt [storeSaltSize]byte
	if _, err := rand.Read(salt[:]); err != nil {
		return fmt.Errorf("gen salt: %w", err)
	}
	var nonce [storeNonceSize]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return fmt.Errorf("gen nonce: %w", err)
	}

	// Derive key with Argon2id.
	key := argon2.IDKey(password, salt[:], argonTime, argonMemory, argonThreads, argonKeyLen)

	aead, err := chacha20poly1305.NewX(key)
	if err != nil {
		return fmt.Errorf("xchacha20: %w", err)
	}

	ciphertext := aead.Seal(nil, nonce[:], plaintext, nil)

	// Write file: header + ciphertext.
	out := make([]byte, storeHeaderSize+len(ciphertext))
	copy(out[0:4], storeMagic)
	out[4] = storeVersion
	copy(out[5:5+storeSaltSize], salt[:])
	copy(out[5+storeSaltSize:storeHeaderSize], nonce[:])
	copy(out[storeHeaderSize:], ciphertext)

	if err := os.WriteFile(path, out, 0600); err != nil {
		return fmt.Errorf("write file: %w", err)
	}
	return nil
}

// LoadIdentity reads an encrypted identity file and decrypts it with the password.
func LoadIdentity(path string, password []byte) (*Identity, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read file: %w", err)
	}

	if len(data) < storeHeaderSize {
		return nil, fmt.Errorf("file too short: %d bytes", len(data))
	}

	// Validate magic and version.
	if string(data[0:4]) != storeMagic {
		return nil, fmt.Errorf("invalid magic: %q", string(data[0:4]))
	}
	if data[4] != storeVersion {
		return nil, fmt.Errorf("unsupported version: %d", data[4])
	}

	salt := data[5 : 5+storeSaltSize]
	nonce := data[5+storeSaltSize : storeHeaderSize]
	ciphertext := data[storeHeaderSize:]

	// Derive key.
	key := argon2.IDKey(password, salt, argonTime, argonMemory, argonThreads, argonKeyLen)

	aead, err := chacha20poly1305.NewX(key)
	if err != nil {
		return nil, fmt.Errorf("xchacha20: %w", err)
	}

	plaintext, err := aead.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("decrypt: %w", err)
	}

	// Parse: privateKey || publicKey.
	privSize := mldsa87.PrivateKeySize
	pubSize := mldsa87.PublicKeySize

	if len(plaintext) != privSize+pubSize {
		return nil, fmt.Errorf("unexpected plaintext size: got %d, want %d", len(plaintext), privSize+pubSize)
	}

	var priv mldsa87.PrivateKey
	if err := priv.UnmarshalBinary(plaintext[:privSize]); err != nil {
		return nil, fmt.Errorf("unmarshal private key: %w", err)
	}

	var pub mldsa87.PublicKey
	if err := pub.UnmarshalBinary(plaintext[privSize:]); err != nil {
		return nil, fmt.Errorf("unmarshal public key: %w", err)
	}

	return &Identity{PublicKey: &pub, PrivateKey: &priv}, nil
}

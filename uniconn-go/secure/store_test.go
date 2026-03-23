package secure_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

func TestSaveLoadIdentity(t *testing.T) {
	id, err := secure.GenerateIdentity()
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}

	dir := t.TempDir()
	path := filepath.Join(dir, "test.ucid")
	password := []byte("super-secret-password")

	if err := secure.SaveIdentity(path, id, password); err != nil {
		t.Fatalf("save: %v", err)
	}

	// Verify file exists and has expected size.
	info, err := os.Stat(path)
	if err != nil {
		t.Fatalf("stat: %v", err)
	}
	t.Logf("file size: %d bytes", info.Size())

	loaded, err := secure.LoadIdentity(path, password)
	if err != nil {
		t.Fatalf("load: %v", err)
	}

	// Compare fingerprints.
	origFP := id.Fingerprint()
	loadedFP := loaded.Fingerprint()
	if origFP != loadedFP {
		t.Fatalf("fingerprint mismatch:\n  orig:   %x\n  loaded: %x", origFP, loadedFP)
	}

	// Verify sign/verify roundtrip with loaded key.
	msg := []byte("test message for signing")
	sig, err := loaded.Sign(msg)
	if err != nil {
		t.Fatalf("sign with loaded key: %v", err)
	}
	if !secure.Verify(loaded.PublicKey, msg, sig) {
		t.Fatal("verify failed with loaded key")
	}
	// Also verify with original public key.
	if !secure.Verify(id.PublicKey, msg, sig) {
		t.Fatal("verify with original pubkey failed")
	}

	t.Logf("save/load roundtrip OK, fingerprint: %x…", origFP[:8])
}

func TestLoadIdentityWrongPassword(t *testing.T) {
	id, _ := secure.GenerateIdentity()

	dir := t.TempDir()
	path := filepath.Join(dir, "test.ucid")

	if err := secure.SaveIdentity(path, id, []byte("correct")); err != nil {
		t.Fatalf("save: %v", err)
	}

	_, err := secure.LoadIdentity(path, []byte("wrong"))
	if err == nil {
		t.Fatal("expected error with wrong password, got nil")
	}
	t.Logf("correctly rejected wrong password: %v", err)
}

func TestLoadIdentityCorruptedFile(t *testing.T) {
	id, _ := secure.GenerateIdentity()

	dir := t.TempDir()
	path := filepath.Join(dir, "test.ucid")
	password := []byte("password")

	if err := secure.SaveIdentity(path, id, password); err != nil {
		t.Fatalf("save: %v", err)
	}

	// Truncate file.
	if err := os.WriteFile(path, []byte("UCID"), 0600); err != nil {
		t.Fatal(err)
	}
	_, err := secure.LoadIdentity(path, password)
	if err == nil {
		t.Fatal("expected error with truncated file, got nil")
	}
	t.Logf("correctly rejected truncated: %v", err)

	// Invalid magic.
	if err := os.WriteFile(path, make([]byte, 200), 0600); err != nil {
		t.Fatal(err)
	}
	_, err = secure.LoadIdentity(path, password)
	if err == nil {
		t.Fatal("expected error with invalid magic, got nil")
	}
	t.Logf("correctly rejected invalid magic: %v", err)
}

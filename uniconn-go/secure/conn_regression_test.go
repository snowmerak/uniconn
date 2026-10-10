package secure

import (
	"bytes"
	"encoding/hex"
	"encoding/json"
	"io"
	"net"
	"os"
	"sync"
	"testing"
	"time"
)

func dataVector(t *testing.T) (*sessionKeys, []byte, []byte) {
	t.Helper()
	data, err := os.ReadFile("../../uniconn-tests/vectors/secure-data-v1.json")
	if err != nil {
		t.Fatal(err)
	}
	var vector map[string]json.RawMessage
	if err := json.Unmarshal(data, &vector); err != nil {
		t.Fatal(err)
	}
	decode := func(name string) []byte {
		var value string
		if err := json.Unmarshal(vector[name], &value); err != nil {
			t.Fatal(err)
		}
		data, err := hex.DecodeString(value)
		if err != nil {
			t.Fatal(err)
		}
		return data
	}
	keys := &sessionKeys{}
	copy(keys.InitiatorKey[:], decode("initiator_key"))
	copy(keys.ResponderKey[:], decode("responder_key"))
	copy(keys.InitiatorNoncePfx[:], decode("initiator_nonce_prefix"))
	copy(keys.ResponderNoncePfx[:], decode("responder_nonce_prefix"))
	return keys, decode("frame"), decode("plaintext")
}

func TestSharedDataVectorAndReplay(t *testing.T) {
	keys, frame, plaintext := dataVector(t)
	wire := bytes.NewBuffer(append(append([]byte{}, frame...), frame...))
	conn := newSecureConn(wire, keys, false, AnyFingerprint)
	buf := make([]byte, 128)
	n, err := conn.Read(buf)
	if err != nil || !bytes.Equal(buf[:n], plaintext) {
		t.Fatalf("vector: %q, %v", buf[:n], err)
	}
	if _, err := conn.Read(buf); err == nil {
		t.Fatal("replayed frame accepted")
	}
}

func TestTamperedFrameDoesNotAdvanceCounter(t *testing.T) {
	keys, frame, _ := dataVector(t)
	tampered := append([]byte{}, frame...)
	tampered[len(tampered)-1] ^= 1
	wire := bytes.NewBuffer(append(tampered, frame...))
	conn := newSecureConn(wire, keys, false, AnyFingerprint)
	if _, err := conn.Read(make([]byte, 128)); err == nil {
		t.Fatal("tampered frame accepted")
	}
	if _, err := conn.Read(make([]byte, 128)); err != nil {
		t.Fatalf("counter advanced on authentication failure: %v", err)
	}
}

func TestConcurrentWritesPreserveCounterOrder(t *testing.T) {
	keys, _, _ := dataVector(t)
	wire := &bytes.Buffer{}
	sender := newSecureConn(wire, keys, true, AnyFingerprint)
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := sender.Write([]byte("x")); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	receiver := newSecureConn(wire, keys, false, AnyFingerprint)
	for i := 0; i < 100; i++ {
		buf := make([]byte, 1)
		if n, err := receiver.Read(buf); err != nil || n != 1 || buf[0] != 'x' {
			t.Fatalf("frame %d: %v", i, err)
		}
	}
}

func TestSecureCloseInterruptsReadWithoutWriting(t *testing.T) {
	a, b := net.Pipe()
	defer b.Close()
	conn := newSecureConn(a, &sessionKeys{}, true, AnyFingerprint)
	read := make(chan error, 1)
	go func() { _, err := conn.Read(make([]byte, 1)); read <- err }()
	closed := make(chan struct{})
	go func() { conn.Close(); conn.Close(); close(closed) }()
	select {
	case <-closed:
	case <-time.After(time.Second):
		t.Fatal("Close blocked on a non-reading peer")
	}
	select {
	case err := <-read:
		if err == nil {
			t.Fatal("read succeeded after close")
		}
	case <-time.After(time.Second):
		t.Fatal("read was not interrupted")
	}
}

func TestDataCounterGapRejected(t *testing.T) {
	wire := &bytes.Buffer{}
	sender := newSecureConn(wire, &sessionKeys{}, true, AnyFingerprint)
	sender.Write([]byte("first"))
	io.Copy(io.Discard, wire)
	sender.Write([]byte("second"))
	receiver := newSecureConn(wire, &sessionKeys{}, false, AnyFingerprint)
	if _, err := receiver.Read(make([]byte, 128)); err == nil {
		t.Fatal("counter gap accepted")
	}
}

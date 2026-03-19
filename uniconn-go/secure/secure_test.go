package secure_test

import (
	"bytes"
	"io"
	"net"
	"sync"
	"testing"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

func TestHandshakeAndEcho(t *testing.T) {
	// Generate identities.
	alice, err := secure.GenerateIdentity()
	if err != nil {
		t.Fatalf("alice keygen: %v", err)
	}
	bob, err := secure.GenerateIdentity()
	if err != nil {
		t.Fatalf("bob keygen: %v", err)
	}
	aliceFP := alice.Fingerprint()
	bobFP := bob.Fingerprint()

	// TCP pipe.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	var wg sync.WaitGroup
	var bobConn *secure.SecureConn
	var bobErr error

	// Bob (responder).
	wg.Add(1)
	go func() {
		defer wg.Done()
		rawConn, err := ln.Accept()
		if err != nil {
			bobErr = err
			return
		}
		bobConn, bobErr = secure.HandshakeResponder(rawConn, bob, aliceFP)
	}()

	// Alice (initiator).
	rawConn, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	aliceConn, err := secure.HandshakeInitiator(rawConn, alice, bobFP)
	if err != nil {
		t.Fatalf("alice handshake: %v", err)
	}

	wg.Wait()
	if bobErr != nil {
		t.Fatalf("bob handshake: %v", bobErr)
	}

	// Echo test: Alice sends, Bob receives and echoes back.
	testData := []byte("hello, uniconn E2EE!")

	// Alice writes.
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, err := aliceConn.Write(testData); err != nil {
			t.Errorf("alice write: %v", err)
		}
	}()

	// Bob reads and echoes.
	buf := make([]byte, 1024)
	n, err := bobConn.Read(buf)
	if err != nil {
		t.Fatalf("bob read: %v", err)
	}
	wg.Wait()

	if !bytes.Equal(buf[:n], testData) {
		t.Fatalf("echo mismatch: got %q, want %q", buf[:n], testData)
	}

	// Bob echoes back.
	wg.Add(1)
	go func() {
		defer wg.Done()
		if _, err := bobConn.Write(buf[:n]); err != nil {
			t.Errorf("bob write: %v", err)
		}
	}()

	buf2 := make([]byte, 1024)
	n2, err := aliceConn.Read(buf2)
	if err != nil {
		t.Fatalf("alice read: %v", err)
	}
	wg.Wait()

	if !bytes.Equal(buf2[:n2], testData) {
		t.Fatalf("echo back mismatch: got %q, want %q", buf2[:n2], testData)
	}

	t.Logf("E2EE echo OK: %q (len=%d)", testData, len(testData))

	aliceConn.Close()
	bobConn.Close()
}

func TestHandshakeFingerprintMismatch(t *testing.T) {
	alice, _ := secure.GenerateIdentity()
	bob, _ := secure.GenerateIdentity()
	eve, _ := secure.GenerateIdentity() // attacker

	// Alice expects Bob, but will receive Eve's handshake.
	aliceFP := alice.Fingerprint()
	eveFP := eve.Fingerprint() // Alice will present Eve's FP (wrong)

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()

	var wg sync.WaitGroup

	wg.Add(1)
	go func() {
		defer wg.Done()
		rawConn, err := ln.Accept()
		if err != nil {
			return
		}
		// Bob handshake may succeed or fail depending on timing.
		sc, _ := secure.HandshakeResponder(rawConn, bob, aliceFP)
		if sc != nil {
			sc.Close()
		}
	}()

	rawConn, err := net.Dial("tcp", ln.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	// Alice expects Eve's fingerprint, but gets Bob's → should fail.
	_, aliceErr := secure.HandshakeInitiator(rawConn, alice, eveFP)
	wg.Wait()

	if aliceErr == nil {
		t.Fatal("expected fingerprint mismatch error from alice, got nil")
	}
	t.Logf("correctly rejected: %v", aliceErr)
}

func TestLargePayload(t *testing.T) {
	alice, _ := secure.GenerateIdentity()
	bob, _ := secure.GenerateIdentity()
	aliceFP := alice.Fingerprint()
	bobFP := bob.Fingerprint()

	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	defer ln.Close()

	var wg sync.WaitGroup
	var bobConn *secure.SecureConn

	wg.Add(1)
	go func() {
		defer wg.Done()
		rawConn, _ := ln.Accept()
		bobConn, _ = secure.HandshakeResponder(rawConn, bob, aliceFP)
	}()

	rawConn, _ := net.Dial("tcp", ln.Addr().String())
	aliceConn, err := secure.HandshakeInitiator(rawConn, alice, bobFP)
	if err != nil {
		t.Fatal(err)
	}
	wg.Wait()

	// 64KB payload.
	data := make([]byte, 65536)
	for i := range data {
		data[i] = byte(i % 256)
	}

	wg.Add(1)
	go func() {
		defer wg.Done()
		aliceConn.Write(data)
	}()

	received := make([]byte, 0, len(data))
	buf := make([]byte, 4096)
	for len(received) < len(data) {
		n, err := bobConn.Read(buf)
		if err != nil {
			if err == io.EOF {
				break
			}
			t.Fatalf("read: %v", err)
		}
		received = append(received, buf[:n]...)
	}
	wg.Wait()

	if !bytes.Equal(received, data) {
		t.Fatalf("64KB payload mismatch")
	}
	t.Logf("64KB E2EE echo OK")

	aliceConn.Close()
	bobConn.Close()
}

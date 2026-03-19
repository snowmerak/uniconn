package integration_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"encoding/pem"
	"fmt"
	"io"
	"math/big"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/kcp"
	"github.com/snowmerak/uniconn/uniconn-go/quic"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
	"github.com/snowmerak/uniconn/uniconn-go/websocket"
	"github.com/snowmerak/uniconn/uniconn-go/webtransport"
)

// ─── TLS helper ──────────────────────────────────────────

func selfSignedTLS(t *testing.T) *tls.Config {
	t.Helper()

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}

	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     []string{"localhost"},
	}

	certDER, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("cert: %v", err)
	}

	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatalf("key: %v", err)
	}

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})

	tlsCert, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		t.Fatalf("keypair: %v", err)
	}

	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(certPEM)

	return &tls.Config{
		Certificates: []tls.Certificate{tlsCert},
		RootCAs:      pool,
		ServerName:   "localhost",
	}
}

// ─── echo helpers ────────────────────────────────────────

func startEcho(t *testing.T, ln uniconn.Listener) {
	t.Helper()
	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func() {
				defer conn.Close()
				io.Copy(conn, conn)
			}()
		}
	}()
}

func echoRoundTrip(t *testing.T, conn net.Conn, payload []byte) {
	t.Helper()

	// Write
	n, err := conn.Write(payload)
	if err != nil {
		t.Fatalf("write: %v", err)
	}
	if n != len(payload) {
		t.Fatalf("write: got %d, want %d", n, len(payload))
	}

	// Read
	conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	buf := make([]byte, len(payload)+1024)
	total := 0
	for total < len(payload) {
		n, err := conn.Read(buf[total:])
		if err != nil {
			t.Fatalf("read after %d/%d bytes: %v", total, len(payload), err)
		}
		total += n
	}

	if total != len(payload) {
		t.Fatalf("read: got %d bytes, want %d", total, len(payload))
	}

	for i := range payload {
		if buf[i] != payload[i] {
			t.Fatalf("mismatch at byte %d: got %d, want %d", i, buf[i], payload[i])
		}
	}
}

// ─── payloads ────────────────────────────────────────────

func shortText() []byte  { return []byte("hello uniconn!") }
func binary256() []byte  { b := make([]byte, 256); for i := range b { b[i] = byte(i) }; return b }
func large64KB() []byte  { b := make([]byte, 65536); for i := range b { b[i] = byte(i % 256) }; return b }

type payloadCase struct {
	name    string
	payload func() []byte
}

var payloads = []payloadCase{
	{"short_text", shortText},
	{"binary_256B", binary256},
	{"large_64KB", large64KB},
}

// ─── TCP ─────────────────────────────────────────────────

func TestTCPEcho(t *testing.T) {
	ln, err := tcp.Listen("127.0.0.1:0", nil)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	startEcho(t, ln)

	for _, tc := range payloads {
		t.Run(tc.name, func(t *testing.T) {
			dialer := tcp.NewDialer(nil)
			conn, err := dialer.Dial(context.Background(), ln.Addr().String())
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer conn.Close()
			echoRoundTrip(t, conn, tc.payload())
		})
	}
}

// ─── WebSocket ───────────────────────────────────────────

func TestWebSocketEcho(t *testing.T) {
	ln, err := websocket.Listen("127.0.0.1:0", &websocket.ListenConfig{Path: "/echo"})
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	startEcho(t, ln)

	addr := ln.Addr().String()
	for _, tc := range payloads {
		t.Run(tc.name, func(t *testing.T) {
			dialer := websocket.NewDialer(nil)
			conn, err := dialer.Dial(context.Background(), fmt.Sprintf("ws://%s/echo", addr))
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer conn.Close()
			echoRoundTrip(t, conn, tc.payload())
		})
	}
}

// ─── QUIC ────────────────────────────────────────────────

func TestQUICEcho(t *testing.T) {
	tlsCfg := selfSignedTLS(t)

	serverCfg := tlsCfg.Clone()
	ln, err := quic.Listen("127.0.0.1:0", &quic.ListenConfig{TLSConfig: serverCfg})
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	startEcho(t, ln)

	for _, tc := range payloads {
		t.Run(tc.name, func(t *testing.T) {
			clientCfg := &tls.Config{
				RootCAs:            tlsCfg.RootCAs,
				ServerName:         "localhost",
				InsecureSkipVerify: true,
			}
			dialer := quic.NewDialer(&quic.DialConfig{TLSConfig: clientCfg})
			conn, err := dialer.Dial(context.Background(), ln.Addr().String())
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer conn.Close()
			echoRoundTrip(t, conn, tc.payload())
		})
	}
}

// ─── KCP ─────────────────────────────────────────────────

func TestKCPEcho(t *testing.T) {
	ln, err := kcp.Listen("127.0.0.1:0", nil)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	startEcho(t, ln)

	for _, tc := range payloads {
		t.Run(tc.name, func(t *testing.T) {
			dialer := kcp.NewDialer(nil)
			conn, err := dialer.Dial(context.Background(), ln.Addr().String())
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer conn.Close()
			echoRoundTrip(t, conn, tc.payload())
		})
	}
}

// ─── WebTransport ────────────────────────────────────────

func TestWebTransportEcho(t *testing.T) {
	tlsCfg := selfSignedTLS(t)

	serverCfg := tlsCfg.Clone()
	ln, err := webtransport.Listen("127.0.0.1:0", &webtransport.ListenConfig{
		TLSConfig: serverCfg,
		Path:      "/wt",
	})
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	startEcho(t, ln)

	// Wait for server to start listening
	time.Sleep(200 * time.Millisecond)

	for _, tc := range payloads {
		t.Run(tc.name, func(t *testing.T) {
			clientCfg := &tls.Config{
				RootCAs:            tlsCfg.RootCAs,
				ServerName:         "localhost",
				InsecureSkipVerify: true,
			}
			dialer := webtransport.NewDialer(&webtransport.DialConfig{
				TLSConfig: clientCfg,
			})
			conn, err := dialer.Dial(context.Background(),
				fmt.Sprintf("https://localhost:%s/wt", portFromAddr(ln.Addr())))
			if err != nil {
				t.Fatalf("dial: %v", err)
			}
			defer conn.Close()
			echoRoundTrip(t, conn, tc.payload())
		})
	}
}

// ─── Concurrent multi-protocol ───────────────────────────

func TestAllProtocolsConcurrent(t *testing.T) {
	tlsCfg := selfSignedTLS(t)

	// Start all listeners
	tcpLn, _ := tcp.Listen("127.0.0.1:0", nil)
	wsLn, _ := websocket.Listen("127.0.0.1:0", &websocket.ListenConfig{Path: "/"})
	quicLn, _ := quic.Listen("127.0.0.1:0", &quic.ListenConfig{TLSConfig: tlsCfg.Clone()})
	kcpLn, _ := kcp.Listen("127.0.0.1:0", nil)

	defer tcpLn.Close()
	defer wsLn.Close()
	defer quicLn.Close()
	defer kcpLn.Close()

	startEcho(t, tcpLn)
	startEcho(t, wsLn)
	startEcho(t, quicLn)
	startEcho(t, kcpLn)

	payload := large64KB()
	var wg sync.WaitGroup
	errs := make(chan error, 4)

	dial := func(name string, d uniconn.Dialer, addr string) {
		defer wg.Done()
		conn, err := d.Dial(context.Background(), addr)
		if err != nil {
			errs <- fmt.Errorf("[%s] dial: %w", name, err)
			return
		}
		defer conn.Close()

		conn.SetReadDeadline(time.Now().Add(5 * time.Second))

		n, err := conn.Write(payload)
		if err != nil || n != len(payload) {
			errs <- fmt.Errorf("[%s] write: n=%d, err=%v", name, n, err)
			return
		}

		buf := make([]byte, len(payload))
		total := 0
		for total < len(payload) {
			n, err := conn.Read(buf[total:])
			if err != nil {
				errs <- fmt.Errorf("[%s] read after %d/%d: %v", name, total, len(payload), err)
				return
			}
			total += n
		}

		for i := range payload {
			if buf[i] != payload[i] {
				errs <- fmt.Errorf("[%s] mismatch at %d", name, i)
				return
			}
		}
	}

	clientTLS := &tls.Config{
		RootCAs:            tlsCfg.RootCAs,
		ServerName:         "localhost",
		InsecureSkipVerify: true,
	}

	wg.Add(4)
	go dial("TCP", tcp.NewDialer(nil), tcpLn.Addr().String())
	go dial("WS", websocket.NewDialer(nil), fmt.Sprintf("ws://%s/", wsLn.Addr()))
	go dial("QUIC", quic.NewDialer(&quic.DialConfig{TLSConfig: clientTLS.Clone()}), quicLn.Addr().String())
	go dial("KCP", kcp.NewDialer(nil), kcpLn.Addr().String())

	wg.Wait()
	close(errs)

	for err := range errs {
		t.Error(err)
	}
}

func portFromAddr(addr net.Addr) string {
	_, port, _ := net.SplitHostPort(addr.String())
	return port
}

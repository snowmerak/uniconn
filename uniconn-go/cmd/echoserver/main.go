// Package main provides an echo server that supports ALL protocols
// for cross-platform integration testing.
//
// Ports:
//   - TCP:          :19001
//   - WebSocket:    :19002  (path /echo)
//   - QUIC:         :19003  (TLS self-signed)
//   - WebTransport: :19004  (TLS self-signed, path /)
//   - KCP:          :19005
package main

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
	"log"
	"math/big"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/kcp"
	"github.com/snowmerak/uniconn/uniconn-go/quic"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
	"github.com/snowmerak/uniconn/uniconn-go/websocket"
	"github.com/snowmerak/uniconn/uniconn-go/webtransport"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	tlsCfg := generateSelfSignedTLS()

	var wg sync.WaitGroup
	var listeners []uniconn.Listener

	// ── TCP :19001 ───────────────────────────────────────
	tcpLn, err := tcp.Listen(":19001", nil)
	must("tcp", err)
	listeners = append(listeners, tcpLn)
	fmt.Fprintf(os.Stdout, "TCP       %s\n", tcpLn.Addr())
	wg.Add(1)
	go func() { defer wg.Done(); runEcho(ctx, tcpLn, "TCP") }()

	// ── WebSocket :19002 ─────────────────────────────────
	wsLn, err := websocket.Listen(":19002", &websocket.ListenConfig{Path: "/echo"})
	must("ws", err)
	listeners = append(listeners, wsLn)
	fmt.Fprintf(os.Stdout, "WebSocket %s\n", wsLn.Addr())
	wg.Add(1)
	go func() { defer wg.Done(); runEcho(ctx, wsLn, "WS") }()

	// ── QUIC :19003 ──────────────────────────────────────
	quicLn, err := quic.Listen(":19003", &quic.ListenConfig{TLSConfig: tlsCfg.Clone()})
	must("quic", err)
	listeners = append(listeners, quicLn)
	fmt.Fprintf(os.Stdout, "QUIC      %s\n", quicLn.Addr())
	wg.Add(1)
	go func() { defer wg.Done(); runEcho(ctx, quicLn, "QUIC") }()

	// ── WebTransport :19004 ──────────────────────────────
	wtLn, err := webtransport.Listen(":19004", &webtransport.ListenConfig{
		TLSConfig: tlsCfg.Clone(),
		CertFile:  "", // in-memory cert via TLSConfig
		KeyFile:   "",
		Path:      "/",
	})
	must("wt", err)
	listeners = append(listeners, wtLn)
	fmt.Fprintf(os.Stdout, "WebTrans  %s\n", wtLn.Addr())
	wg.Add(1)
	go func() { defer wg.Done(); runEcho(ctx, wtLn, "WT") }()

	// ── KCP :19005 ───────────────────────────────────────
	kcpLn, err := kcp.Listen(":19005", nil)
	must("kcp", err)
	listeners = append(listeners, kcpLn)
	fmt.Fprintf(os.Stdout, "KCP       %s\n", kcpLn.Addr())
	wg.Add(1)
	go func() { defer wg.Done(); runEcho(ctx, kcpLn, "KCP") }()

	// Signal readiness
	fmt.Fprintln(os.Stdout, "READY")

	<-ctx.Done()
	for _, ln := range listeners {
		ln.Close()
	}
	wg.Wait()
	fmt.Fprintln(os.Stdout, "shutdown complete")
}

// ─── helpers ─────────────────────────────────────────────

func must(tag string, err error) {
	if err != nil {
		log.Fatalf("[%s] listen: %v", tag, err)
	}
}

func runEcho(ctx context.Context, ln uniconn.Listener, tag string) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
				log.Printf("[%s] accept: %v", tag, err)
				return
			}
		}
		go handleConn(conn, tag)
	}
}

func handleConn(conn net.Conn, tag string) {
	defer conn.Close()
	log.Printf("[%s] ← %s", tag, conn.RemoteAddr())
	n, err := io.Copy(conn, conn)
	if err != nil {
		log.Printf("[%s] echo err after %dB: %v", tag, n, err)
	}
}

// generateSelfSignedTLS creates an in-memory self-signed TLS certificate.
func generateSelfSignedTLS() *tls.Config {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		log.Fatalf("tls keygen: %v", err)
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
		log.Fatalf("tls cert: %v", err)
	}

	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		log.Fatalf("tls key marshal: %v", err)
	}

	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})

	tlsCert, err := tls.X509KeyPair(certPEM, keyPEM)
	if err != nil {
		log.Fatalf("tls keypair: %v", err)
	}

	return &tls.Config{
		Certificates: []tls.Certificate{tlsCert},
	}
}

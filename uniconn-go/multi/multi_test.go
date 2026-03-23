package multi_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	uniconn "github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/multi"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
	"github.com/snowmerak/uniconn/uniconn-go/websocket"
)

// ─── Negotiate ──────────────────────────────────────────────

func TestNegotiateHandler(t *testing.T) {
	entries := []multi.ProtocolEntry{
		{Name: multi.ProtoTCP, Address: "server:8001"},
		{Name: multi.ProtoWebSocket, Address: "ws://server:8002/ws"},
	}

	handler := multi.NegotiateHandler(entries, "")
	req := httptest.NewRequest(http.MethodGet, "/negotiate", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status: %d", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Fatalf("content-type: %s", ct)
	}

	var resp multi.NegotiateResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &resp); err != nil {
		t.Fatalf("parse: %v", err)
	}
	if len(resp.Protocols) != 2 {
		t.Fatalf("got %d protocols, want 2", len(resp.Protocols))
	}
	if resp.Protocols[0].Name != multi.ProtoTCP {
		t.Fatalf("first protocol: %s", resp.Protocols[0].Name)
	}
	t.Logf("negotiate OK: %+v", resp)
}

func TestNegotiateHandlerRejectsPost(t *testing.T) {
	handler := multi.NegotiateHandler(nil, "")
	req := httptest.NewRequest(http.MethodPost, "/negotiate", nil)
	rec := httptest.NewRecorder()
	handler(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("expected 405, got %d", rec.Code)
	}
}

// ─── MultiListener + MultiDialer Integration ────────────────

func TestMultiDialerSelectsBestProtocol(t *testing.T) {
	// Start a TCP listener.
	tcpLn, err := tcp.Listen("127.0.0.1:0", nil)
	if err != nil {
		t.Fatal(err)
	}

	// Start a WS listener.
	wsLn, err := websocket.Listen("127.0.0.1:0", &websocket.ListenConfig{Path: "/ws"})
	if err != nil {
		t.Fatal(err)
	}

	// Create MultiListener with negotiate endpoint.
	ml, err := multi.NewMultiListener("127.0.0.1:0",
		multi.TransportConfig{
			Protocol: multi.ProtoWebSocket,
			Address:  "ws://127.0.0.1:" + portFromAddr(wsLn.Addr()) + "/ws",
			Listener: tcpToUniconn(wsLn),
		},
		multi.TransportConfig{
			Protocol: multi.ProtoTCP,
			Address:  tcpLn.Addr().String(),
			Listener: tcpToUniconn(tcpLn),
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	defer ml.Close()

	// Server: accept one connection and echo.
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		conn, proto, err := ml.AcceptWith()
		if err != nil {
			t.Errorf("accept: %v", err)
			return
		}
		t.Logf("accepted via %s", proto)
		defer conn.Close()
		io.Copy(conn, conn) // echo
	}()

	// Client: MultiDialer with only TCP dialer registered.
	// Should select TCP even though WS is higher priority,
	// because client has no WS dialer.
	negotiateURL := "http://" + ml.NegotiateAddr().String() + "/negotiate"

	md := multi.NewMultiDialer(multi.DialerConfig{
		NegotiateURL: negotiateURL,
		Dialers: map[multi.Protocol]uniconn.Dialer{
			multi.ProtoTCP: tcp.NewDialer(nil),
		},
		DialTimeout: 3 * time.Second,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	conn, proto, err := md.Dial(ctx)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	if proto != multi.ProtoTCP {
		t.Fatalf("expected TCP, got %s", proto)
	}

	// Echo test.
	testMsg := []byte("hello multi-protocol!")
	if _, err := conn.Write(testMsg); err != nil {
		t.Fatalf("write: %v", err)
	}

	buf := make([]byte, 1024)
	n, err := conn.Read(buf)
	if err != nil {
		t.Fatalf("read: %v", err)
	}

	if !bytes.Equal(buf[:n], testMsg) {
		t.Fatalf("echo mismatch: got %q, want %q", buf[:n], testMsg)
	}

	t.Logf("multi-dialer echo via %s OK: %q", proto, testMsg)

	conn.Close()
	ml.Close()
	wg.Wait()
}

func TestMultiDialerFallback(t *testing.T) {
	// Start only a TCP listener.
	tcpLn, err := tcp.Listen("127.0.0.1:0", nil)
	if err != nil {
		t.Fatal(err)
	}

	// Negotiate advertises WebSocket AND TCP, but only TCP is actually listening.
	// Client has both dialers registered but WS address points to a closed port.
	closedPort := findFreePort(t)

	ml, err := multi.NewMultiListener("127.0.0.1:0",
		multi.TransportConfig{
			Protocol: multi.ProtoTCP,
			Address:  tcpLn.Addr().String(),
			Listener: tcpToUniconn(tcpLn),
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	defer ml.Close()

	// server: echo
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		conn, _, err := ml.AcceptWith()
		if err != nil {
			return
		}
		defer conn.Close()
		io.Copy(conn, conn)
	}()

	// Manually build negotiate server with WS entry pointing to dead port.
	fakeNeg := httptest.NewServer(multi.NegotiateHandler([]multi.ProtocolEntry{
		{Name: multi.ProtoWebSocket, Address: "ws://127.0.0.1:" + closedPort + "/ws"},
		{Name: multi.ProtoTCP, Address: tcpLn.Addr().String()},
	}, ""))
	defer fakeNeg.Close()

	md := multi.NewMultiDialer(multi.DialerConfig{
		NegotiateURL: fakeNeg.URL + "/negotiate",
		Dialers: map[multi.Protocol]uniconn.Dialer{
			multi.ProtoWebSocket: websocket.NewDialer(nil),
			multi.ProtoTCP:       tcp.NewDialer(nil),
		},
		DialTimeout: 1 * time.Second,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	conn, proto, err := md.Dial(ctx)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer conn.Close()

	// Should have fallen back to TCP.
	if proto != multi.ProtoTCP {
		t.Fatalf("expected TCP fallback, got %s", proto)
	}

	t.Logf("fallback to %s OK", proto)

	conn.Close()
	ml.Close()
	wg.Wait()
}

// ─── Helpers ────────────────────────────────────────────────

// tcpToUniconn is a no-op adapter since our listeners already implement uniconn.Listener.
func tcpToUniconn(l uniconn.Listener) uniconn.Listener {
	return l
}

func portFromAddr(addr net.Addr) string {
	_, port, _ := net.SplitHostPort(addr.String())
	return port
}

func findFreePort(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := portFromAddr(ln.Addr())
	ln.Close()
	return port
}

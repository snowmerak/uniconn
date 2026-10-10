package p2p

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
)

type pipeDialer struct{ conn net.Conn }

func (d pipeDialer) Dial(context.Context, string) (net.Conn, error) { return d.conn, nil }

func TestConnectRelayHonorsContextDuringHandshake(t *testing.T) {
	a, b := net.Pipe()
	defer b.Close()
	id, _ := secure.GenerateIdentity()
	node := NewNode(DefaultNodeConfig, id, pipeDialer{a})
	defer node.Close()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- node.ConnectRelay(ctx, "mock", secure.AnyFingerprint) }()
	// The peer consumes nothing; cancelling must interrupt the HELLO write.
	b.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := b.Read(make([]byte, 1)); err != nil {
		t.Fatal(err)
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("got %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("handshake ignored cancellation")
	}
}

func TestConnectRelaySetupTimeout(t *testing.T) {
	a, b := net.Pipe()
	defer b.Close()
	id, _ := secure.GenerateIdentity()
	node := NewNode(NodeConfig{SetupTimeout: 20 * time.Millisecond}, id, pipeDialer{a})
	defer node.Close()
	done := make(chan error, 1)
	go func() { done <- node.ConnectRelay(context.Background(), "mock", secure.AnyFingerprint) }()
	select {
	case err := <-done:
		if !errors.Is(err, context.DeadlineExceeded) {
			t.Fatalf("got %v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("setup did not time out")
	}
}

func startRelay(t *testing.T, timeout ...time.Duration) (*RelayServer, *secure.Identity) {
	t.Helper()
	id, err := secure.GenerateIdentity()
	if err != nil {
		t.Fatal(err)
	}
	ln, err := tcp.Listen("127.0.0.1:0", nil)
	if err != nil {
		t.Fatal(err)
	}
	setup := time.Second
	if len(timeout) > 0 {
		setup = timeout[0]
	}
	r := NewRelayServer(RelayConfig{SetupTimeout: setup}, ln, tcp.NewDialer(nil), id)
	go r.Serve()
	t.Cleanup(func() { r.Close() })
	return r, id
}

func TestIdleRelayHandshakeTimesOut(t *testing.T) {
	r, _ := startRelay(t, 20*time.Millisecond)
	raw, err := net.Dial("tcp", r.listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer raw.Close()
	raw.SetReadDeadline(time.Now().Add(time.Second))
	if _, err := raw.Read(make([]byte, 1)); err == nil {
		t.Fatal("idle handshake stayed open")
	} else if timeout, ok := err.(net.Error); ok && timeout.Timeout() {
		t.Fatal("relay did not close the idle handshake")
	}
}

func TestProxyEndsWhenEitherPeerCloses(t *testing.T) {
	a, peerA := net.Pipe()
	b, peerB := net.Pipe()
	defer peerA.Close()
	defer peerB.Close()
	done := make(chan struct{})
	go func() { proxyConnections(a, b); close(done) }()
	peerB.Close()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("proxy retained the other direction after EOF")
	}
}

func TestRelayRejectsInvalidFingerprintAndStillServes(t *testing.T) {
	r, relayID := startRelay(t)
	id, _ := secure.GenerateIdentity()
	for _, fp := range []string{"", "x", strings.Repeat("z", 128), strings.Repeat("0", 128)} {
		raw, err := net.Dial("tcp", r.listener.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		raw.SetDeadline(time.Now().Add(time.Second))
		sc, err := secure.HandshakeInitiator(raw, id, relayID.Fingerprint())
		if err != nil {
			t.Fatal(err)
		}
		if err := writeEnvelope(sc, MsgRelayReq, RelayReqPayload{TargetFingerprint: fp}); err != nil {
			t.Fatal(err)
		}
		env, err := readEnvelope(sc)
		if err != nil {
			t.Fatal(err)
		}
		var ack RelayAckPayload
		if err := json.Unmarshal(env.Payload, &ack); err != nil {
			t.Fatal(err)
		}
		if env.Type != MsgRelayAck || ack.Success {
			t.Fatalf("invalid acknowledgement: %+v", env)
		}
		sc.Close()
	}
	for _, fp := range []string{"", "x", strings.Repeat("z", 128)} {
		r.processGossipMessage("mock", Envelope{Type: MsgGossipUpdate, Payload: marshal(GossipUpdatePayload{Fingerprint: fp, Timestamp: 1})}, nil)
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	if len(r.globalRouting) != 0 {
		t.Fatal("invalid gossip mutated routes")
	}
}

func TestDisconnectWakesAllAcceptCallers(t *testing.T) {
	r, relayID := startRelay(t)
	id, _ := secure.GenerateIdentity()
	node := NewNode(DefaultNodeConfig, id, tcp.NewDialer(nil))
	t.Cleanup(func() { node.Close() })
	if err := node.ConnectRelay(context.Background(), r.listener.Addr().String(), relayID.Fingerprint()); err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 3)
	for i := 0; i < 3; i++ {
		go func() { _, err := node.Accept(); done <- err }()
	}
	r.Close()
	for i := 0; i < 3; i++ {
		select {
		case err := <-done:
			if err == nil {
				t.Fatal("accept succeeded after disconnect")
			}
		case <-time.After(time.Second):
			t.Fatal("accept blocked after disconnect")
		}
	}
}

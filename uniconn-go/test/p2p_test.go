package integration

import (
	"context"
	"testing"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go/p2p"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
	"github.com/snowmerak/uniconn/uniconn-go/tcp"
)

func TestP2PFederatedMesh(t *testing.T) {
	// 1. Setup Relay 1 (Seed Node)
	r1ID, _ := secure.GenerateIdentity()
	r1Ln, _ := tcp.Listen("127.0.0.1:0", nil)
	
	r1Cfg := p2p.DefaultRelayConfig
	r1Dialer := tcp.NewDialer(nil)
	r1 := p2p.NewRelayServer(r1Cfg, r1Ln, r1Dialer, r1ID)
	go r1.Serve()

	// 2. Setup Relay 2 (Joins Mesh via R1)
	r2ID, _ := secure.GenerateIdentity()
	r2Ln, _ := tcp.Listen("127.0.0.1:0", nil)
	
	r2Cfg := p2p.DefaultRelayConfig
	r2Cfg.SeedRelays = []string{r1Ln.Addr().String()}
	r2Dialer := tcp.NewDialer(nil)
	r2 := p2p.NewRelayServer(r2Cfg, r2Ln, r2Dialer, r2ID)
	go r2.Serve()

	// Wait briefly for R2 to gossip its join to R1
	time.Sleep(100 * time.Millisecond)

	// 3. Node B (Server) connects to Relay 2
	idB, _ := secure.GenerateIdentity()
	nodeB := p2p.NewNode(p2p.DefaultNodeConfig, idB, tcp.NewDialer(nil))
	if err := nodeB.ConnectRelay(context.Background(), r2Ln.Addr().String(), r2ID.Fingerprint()); err != nil {
		t.Fatalf("Node B ConnectRelay failed: %v", err)
	}

	go func() {
		conn, err := nodeB.Accept()
		if err != nil {
			t.Logf("Node B Accept error (expected on shutdown): %v", err)
			return
		}
		defer conn.Close()
		buf := make([]byte, 1024)
		n, err := conn.Read(buf)
		if err != nil {
			t.Errorf("Node B read error: %v", err)
			return
		}
		conn.Write(buf[:n]) // Echo back
	}()

	// 4. Node A (Client) connects to Relay 1
	idA, _ := secure.GenerateIdentity()
	nodeA := p2p.NewNode(p2p.DefaultNodeConfig, idA, tcp.NewDialer(nil))
	if err := nodeA.ConnectRelay(context.Background(), r1Ln.Addr().String(), r1ID.Fingerprint()); err != nil {
		t.Fatalf("Node A ConnectRelay failed: %v", err)
	}

	// Wait for Node B and Node A's fingerprints to be broadcasted (Epidemic spread across Mesh)
	time.Sleep(300 * time.Millisecond)

	// 5. Node A dials Node B (which forces R1 to do a 2-Hop proxy across to R2!)
	connA, err := nodeA.DialPeer(context.Background(), idB.Fingerprint())
	if err != nil {
		t.Fatalf("Node A DialPeer failed: %v", err)
	}
	defer connA.Close()

	// 6. Test Data Transfer over 2-Hop Nested E2EE Dumb Pipe
	msg := []byte("hello federation 2-hop")
	if _, err := connA.Write(msg); err != nil {
		t.Fatalf("Node A Write failed: %v", err)
	}

	buf := make([]byte, 1024)
	n, err := connA.Read(buf)
	if err != nil {
		t.Fatalf("Node A Read failed: %v", err)
	}

	if string(buf[:n]) != "hello federation 2-hop" {
		t.Fatalf("expected 'hello federation 2-hop', got %s", buf[:n])
	}
}

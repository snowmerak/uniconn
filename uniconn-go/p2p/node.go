package p2p

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"sync"

	"github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

// Node represents a local peer in the P2P network.
type Node struct {
	config   NodeConfig
	identity *secure.Identity
	dialer   uniconn.Dialer

	mu          sync.Mutex
	relayAddr   string
	relayFP     secure.Fingerprint
	controlConn *secure.SecureConn

	incomingCh chan net.Conn
}

// NewNode initializes a new P2P Node.
func NewNode(cfg NodeConfig, id *secure.Identity, dialer uniconn.Dialer) *Node {
	return &Node{
		config:     cfg,
		identity:   id,
		dialer:     dialer,
		incomingCh: make(chan net.Conn, 10),
	}
}

// ConnectRelay establishes the primary control connection to a Relay Server.
func (n *Node) ConnectRelay(ctx context.Context, relayAddr string, relayFP secure.Fingerprint) error {
	n.mu.Lock()
	defer n.mu.Unlock()

	conn, err := n.dialer.Dial(ctx, relayAddr)
	if err != nil {
		return err
	}

	sc, err := secure.HandshakeInitiator(conn, n.identity, relayFP)
	if err != nil {
		conn.Close()
		return err
	}

	n.relayAddr = relayAddr
	n.relayFP = relayFP
	n.controlConn = sc

	// Send Announce
	fp := n.identity.Fingerprint()
	announce := AnnouncePayload{
		Fingerprint: hex.EncodeToString(fp[:]),
	}
	env := Envelope{Type: MsgAnnounce, Payload: marshal(announce)}
	b, _ := json.Marshal(env)
	sc.Write(append(b, '\n'))

	// Start reading control messages
	go n.readControlLoop(sc)
	return nil
}

func (n *Node) readControlLoop(sc *secure.SecureConn) {
	dec := json.NewDecoder(sc)
	for {
		var env Envelope
		if err := dec.Decode(&env); err != nil {
			log.Println("[Node] Control conn closed:", err)
			return
		}

		switch env.Type {
		case MsgIncomingRelay:
			var req IncomingRelayPayload
			json.Unmarshal(env.Payload, &req)
			go n.acceptRelayProxy(req.SessionToken, req.RequesterFingerprint)
		}
	}
}

func (n *Node) acceptRelayProxy(token, requesterFP string) {
	// 1. Dial Relay
	conn, err := n.dialer.Dial(context.Background(), n.relayAddr)
	if err != nil {
		return
	}
	sc, err := secure.HandshakeInitiator(conn, n.identity, n.relayFP)
	if err != nil {
		conn.Close()
		return
	}

	// 2. Accept Token
	pl := AcceptRelayPayload{SessionToken: token}
	env := Envelope{Type: MsgAcceptRelay, Payload: marshal(pl)}
	b, _ := json.Marshal(env)
	sc.Write(append(b, '\n'))

	// 3. The Relay now links us to the Requester. We must wait for their E2EE handshake.
	targetFPBytes, _ := hex.DecodeString(requesterFP)
	var peerFP secure.Fingerprint
	copy(peerFP[:], targetFPBytes)

	// E2EE inside E2EE (Nested)
	finalConn, err := secure.HandshakeResponder(sc, n.identity, peerFP)
	if err != nil {
		log.Printf("[Node] Nested HandshakeResponder failed: %v", err)
		sc.Close()
		return
	}

	n.incomingCh <- finalConn
}

// DialPeer attempts to open a P2P connection to the given Fingerprint.
func (n *Node) DialPeer(ctx context.Context, peerFP secure.Fingerprint) (net.Conn, error) {
	targetHex := hex.EncodeToString(peerFP[:])

	// For v1, purely relay if AllowDirectConnection is false, or direct not implemented fully yet.
	// We'll just route via Relay for reliable NAT traversal.

	// 1. Dial Relay
	conn, err := n.dialer.Dial(ctx, n.relayAddr)
	if err != nil {
		return nil, err
	}

	sc, err := secure.HandshakeInitiator(conn, n.identity, n.relayFP)
	if err != nil {
		conn.Close()
		return nil, err
	}

	// 2. Request Relay Proxy
	req := RelayReqPayload{TargetFingerprint: targetHex}
	env := Envelope{Type: MsgRelayReq, Payload: marshal(req)}
	b, _ := json.Marshal(env)
	sc.Write(append(b, '\n'))

	// Wait for Ack
	dec := json.NewDecoder(sc)
	var ackEnv Envelope
	if err := dec.Decode(&ackEnv); err != nil {
		sc.Close()
		return nil, err
	}
	if ackEnv.Type != MsgRelayAck {
		sc.Close()
		return nil, fmt.Errorf("expected RELAY_ACK, got %s", ackEnv.Type)
	}
	var ack RelayAckPayload
	json.Unmarshal(ackEnv.Payload, &ack)
	if !ack.Success {
		sc.Close()
		return nil, fmt.Errorf("relay proxy failed: %s", ack.Reason)
	}

	// 3. E2EE nested inside Relay connection!
	finalConn, err := secure.HandshakeInitiator(sc, n.identity, peerFP)
	if err != nil {
		sc.Close()
		return nil, fmt.Errorf("nested e2ee handshake failed: %w", err)
	}

	return finalConn, nil
}

// Accept returns incoming connections from peers.
func (n *Node) Accept() (net.Conn, error) {
	conn, ok := <-n.incomingCh
	if !ok {
		return nil, net.ErrClosed
	}
	return conn, nil
}

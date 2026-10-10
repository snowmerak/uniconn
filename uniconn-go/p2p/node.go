package p2p

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"sync"

	"github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

type incomingPeer struct {
	conn net.Conn
	raw  net.Conn
}

type relaySession struct {
	ctx      context.Context
	cancel   context.CancelFunc
	addr     string
	fp       secure.Fingerprint
	control  *secure.SecureConn
	pending  map[net.Conn]struct{}
	incoming chan incomingPeer
	err      error // protected by Node.mu
}

// Node owns control and setup connections. Accepted connections belong to callers.
type Node struct {
	config    NodeConfig
	identity  *secure.Identity
	dialer    uniconn.Dialer
	mu        sync.Mutex
	connectMu sync.Mutex
	session   *relaySession
	closed    bool
}

func NewNode(cfg NodeConfig, id *secure.Identity, dialer uniconn.Dialer) *Node {
	return &Node{config: cfg, identity: id, dialer: dialer}
}

func (n *Node) stopSession(s *relaySession, reason error) {
	n.mu.Lock()
	if s.err != nil {
		n.mu.Unlock()
		return
	}
	s.err = reason
	s.cancel()
	conns := make([]net.Conn, 0, len(s.pending))
	for conn := range s.pending {
		conns = append(conns, conn)
	}
	s.pending = make(map[net.Conn]struct{})
	n.mu.Unlock()
	for _, conn := range conns {
		conn.Close()
	}
}

func (n *Node) sessionError(s *relaySession) error {
	n.mu.Lock()
	defer n.mu.Unlock()
	if s.err != nil {
		return s.err
	}
	return net.ErrClosed
}

func (n *Node) currentSession() (*relaySession, error) {
	n.mu.Lock()
	defer n.mu.Unlock()
	if n.closed {
		return nil, net.ErrClosed
	}
	if n.session == nil || n.session.control == nil {
		return nil, fmt.Errorf("must connect to relay before using peers")
	}
	if n.session.err != nil {
		return nil, n.session.err
	}
	return n.session, nil
}

func (n *Node) release(s *relaySession, conn net.Conn) {
	n.mu.Lock()
	delete(s.pending, conn)
	n.mu.Unlock()
}

func (n *Node) setup(parent context.Context, s *relaySession, fn func(net.Conn) error) (net.Conn, error) {
	ctx, cancel := context.WithTimeout(parent, setupTimeout(n.config.SetupTimeout))
	stopSession := context.AfterFunc(s.ctx, cancel)
	defer stopSession()
	defer cancel()
	if s.ctx.Err() != nil {
		return nil, n.sessionError(s)
	}
	conn, err := n.dialer.Dial(ctx, s.addr)
	if err != nil {
		return nil, err
	}
	n.mu.Lock()
	if s.err != nil {
		n.mu.Unlock()
		conn.Close()
		return nil, n.sessionError(s)
	}
	s.pending[conn] = struct{}{}
	n.mu.Unlock()
	finish := guardSetup(ctx, conn)
	err = fn(conn)
	if finishErr := finish(); finishErr != nil {
		err = finishErr
	}
	if err != nil {
		n.release(s, conn)
		conn.Close()
		return nil, err
	}
	return conn, nil
}

// ConnectRelay replaces the previous session after cancelling its pending work.
func (n *Node) ConnectRelay(ctx context.Context, addr string, fp secure.Fingerprint) error {
	n.connectMu.Lock()
	defer n.connectMu.Unlock()
	n.mu.Lock()
	if n.closed {
		n.mu.Unlock()
		return net.ErrClosed
	}
	old := n.session
	sessionCtx, cancel := context.WithCancel(context.Background())
	s := &relaySession{ctx: sessionCtx, cancel: cancel, addr: addr, fp: fp,
		pending: make(map[net.Conn]struct{}), incoming: make(chan incomingPeer, 10)}
	n.session = s
	n.mu.Unlock()
	if old != nil {
		n.stopSession(old, fmt.Errorf("relay session replaced"))
	}
	var sc *secure.SecureConn
	_, err := n.setup(ctx, s, func(raw net.Conn) error {
		var err error
		sc, err = secure.HandshakeInitiator(raw, n.identity, fp)
		if err != nil {
			return err
		}
		ownFP := n.identity.Fingerprint()
		return writeEnvelope(sc, MsgAnnounce, AnnouncePayload{Fingerprint: hex.EncodeToString(ownFP[:])})
	})
	if err != nil {
		n.stopSession(s, err)
		return err
	}
	n.mu.Lock()
	if s.err != nil {
		n.mu.Unlock()
		sc.Close()
		return n.sessionError(s)
	}
	s.control = sc
	n.mu.Unlock()
	go n.readControlLoop(s)
	return nil
}

func writeEnvelope(conn net.Conn, kind MsgType, payload interface{}) error {
	data, err := json.Marshal(Envelope{Type: kind, Payload: marshal(payload)})
	if err != nil {
		return err
	}
	_, err = conn.Write(append(data, '\n'))
	return err
}

// Read only through the newline: following bytes may belong to a handshake.
func readEnvelope(reader io.Reader) (Envelope, error) {
	var env Envelope
	line := make([]byte, 0, 256)
	var buf [1]byte
	for len(line) < 64*1024 {
		if _, err := io.ReadFull(reader, buf[:]); err != nil {
			return env, err
		}
		if buf[0] == '\n' {
			return env, json.Unmarshal(line, &env)
		}
		line = append(line, buf[0])
	}
	return env, fmt.Errorf("control message too large")
}

func (n *Node) readControlLoop(s *relaySession) {
	dec := json.NewDecoder(s.control)
	for {
		var env Envelope
		if err := dec.Decode(&env); err != nil {
			n.stopSession(s, fmt.Errorf("relay control connection lost: %w", err))
			return
		}
		if env.Type == MsgIncomingRelay {
			var req IncomingRelayPayload
			if json.Unmarshal(env.Payload, &req) == nil && validateFingerprint(req.RequesterFingerprint) == nil {
				go n.acceptRelayProxy(s, req)
			}
		}
	}
}

func (n *Node) acceptRelayProxy(s *relaySession, req IncomingRelayPayload) {
	var finalConn *secure.SecureConn
	raw, err := n.setup(context.Background(), s, func(raw net.Conn) error {
		sc, err := secure.HandshakeInitiator(raw, n.identity, s.fp)
		if err != nil {
			return err
		}
		if err := writeEnvelope(sc, MsgAcceptRelay, AcceptRelayPayload{SessionToken: req.SessionToken}); err != nil {
			return err
		}
		fpBytes, _ := hex.DecodeString(req.RequesterFingerprint)
		var fp secure.Fingerprint
		copy(fp[:], fpBytes)
		finalConn, err = secure.HandshakeResponder(sc, n.identity, fp)
		return err
	})
	if err != nil {
		log.Printf("[Node] accept relay proxy: %v", err)
		return
	}
	select {
	case <-s.ctx.Done():
		n.release(s, raw)
		finalConn.Close()
	case s.incoming <- incomingPeer{conn: finalConn, raw: raw}:
	}
}

// DialPeer bounds dialing, acknowledgement and the nested handshake by ctx.
func (n *Node) DialPeer(ctx context.Context, fp secure.Fingerprint) (net.Conn, error) {
	s, err := n.currentSession()
	if err != nil {
		return nil, err
	}
	var finalConn *secure.SecureConn
	raw, err := n.setup(ctx, s, func(raw net.Conn) error {
		sc, err := secure.HandshakeInitiator(raw, n.identity, s.fp)
		if err != nil {
			return err
		}
		if err := writeEnvelope(sc, MsgRelayReq, RelayReqPayload{TargetFingerprint: hex.EncodeToString(fp[:])}); err != nil {
			return err
		}
		ackEnv, err := readEnvelope(sc)
		if err != nil {
			return err
		}
		if ackEnv.Type != MsgRelayAck {
			return fmt.Errorf("expected RELAY_ACK, got %s", ackEnv.Type)
		}
		var ack RelayAckPayload
		if err := json.Unmarshal(ackEnv.Payload, &ack); err != nil {
			return err
		}
		if !ack.Success {
			return fmt.Errorf("relay proxy failed: %s", ack.Reason)
		}
		finalConn, err = secure.HandshakeInitiator(sc, n.identity, fp)
		return err
	})
	if err != nil {
		return nil, err
	}
	n.mu.Lock()
	err = s.err
	delete(s.pending, raw)
	n.mu.Unlock()
	if err != nil {
		finalConn.Close()
		return nil, err
	}
	return finalConn, nil
}

// Accept returns a peer or the current relay session's terminal error.
func (n *Node) Accept() (net.Conn, error) {
	s, err := n.currentSession()
	if err != nil {
		return nil, err
	}
	select {
	case <-s.ctx.Done():
		return nil, n.sessionError(s)
	case peer := <-s.incoming:
		n.mu.Lock()
		err := s.err
		delete(s.pending, peer.raw)
		n.mu.Unlock()
		if err != nil {
			peer.conn.Close()
			return nil, err
		}
		return peer.conn, nil
	}
}

// Close cancels the control session, setup operations and unaccepted peers.
// Connections already returned to callers remain caller-owned.
func (n *Node) Close() error {
	n.mu.Lock()
	n.closed = true
	s := n.session
	n.mu.Unlock()
	if s != nil {
		n.stopSession(s, net.ErrClosed)
	}
	return nil
}

package p2p

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"log"
	"net"
	"sync"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go"
	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

// activeSession is a pending RelayReq waiting for the target node to accept.
type activeSession struct {
	requesterConn net.Conn
	waitCh        chan net.Conn
}

type peerEntry struct {
	controlConn     *secure.SecureConn
	directAddresses []string
}

// globalPeerEntry stores the timestamped known relay location of a remote peer.
type globalPeerEntry struct {
	relayAddr string
	timestamp int64
}

// RelayServer is the centralized discovery and TURN-like data relay server.
type RelayServer struct {
	config   RelayConfig
	listener uniconn.Listener
	dialer   uniconn.Dialer
	identity *secure.Identity

	mu              sync.RWMutex
	connsCount      int
	activeNodes     map[string]*peerEntry
	pendingSessions map[string]*activeSession

	// Gossip Mesh state
	knownRelays   map[string]struct{}
	neighbors     map[string]*secure.SecureConn
	globalRouting map[string]*globalPeerEntry
	ctx           context.Context
	cancel        context.CancelFunc
	closeOnce     sync.Once
	gossipOnce    sync.Once
	connections   map[net.Conn]struct{}
}

// NewRelayServer initializes a new P2P RelayServer for the Federation mesh.
func NewRelayServer(cfg RelayConfig, ln uniconn.Listener, dialer uniconn.Dialer, id *secure.Identity) *RelayServer {
	ctx, cancel := context.WithCancel(context.Background())
	return &RelayServer{
		ctx: ctx, cancel: cancel, connections: make(map[net.Conn]struct{}),
		config:          cfg,
		listener:        ln,
		dialer:          dialer,
		identity:        id,
		activeNodes:     make(map[string]*peerEntry),
		pendingSessions: make(map[string]*activeSession),
		knownRelays:     make(map[string]struct{}),
		neighbors:       make(map[string]*secure.SecureConn),
		globalRouting:   make(map[string]*globalPeerEntry),
	}
}

// Serve starts the JSON control channel listener and the Gossip mesh loop for the Relay.
func (r *RelayServer) Serve() error {
	r.StartGossipLoop()
	fp := r.identity.Fingerprint()
	log.Printf("[Relay] Listening on %s as %x", r.listener.Addr().String(), fp[:8])
	for {
		conn, err := r.listener.Accept()
		if err != nil {
			return err
		}
		go r.handleIncoming(conn)
	}
}

func (r *RelayServer) handleIncoming(conn net.Conn) {
	r.mu.Lock()
	if r.ctx.Err() != nil || (r.config.MaxConnections > 0 && r.connsCount >= r.config.MaxConnections) {
		r.mu.Unlock()
		conn.Close()
		return
	}
	r.connsCount++
	tracked := &relayConn{Conn: conn, relay: r}
	r.connections[tracked] = struct{}{}
	conn = tracked
	r.mu.Unlock()
	ctx, cancel := context.WithTimeout(r.ctx, setupTimeout(r.config.SetupTimeout))
	defer cancel()
	finish := guardSetup(ctx, conn)

	// A public Relay accepts anonymous connections, thus zero/any Fingerprint.
	secConn, err := secure.HandshakeResponder(conn, r.identity, secure.AnyFingerprint)
	if err != nil {
		finish()
		log.Printf("[Relay] Handshake failed: %v\n", err)
		conn.Close()
		return
	}

	fp := secConn.PeerFingerprint()
	peerFP := hex.EncodeToString(fp[:])

	// We read the first message to know.
	reader := bufio.NewReaderSize(secConn, 64*1024)
	line, err := reader.ReadSlice('\n')
	if finishErr := finish(); finishErr != nil {
		err = finishErr
	}
	if err != nil {
		secConn.Close()
		return
	}

	var env Envelope
	if err := json.Unmarshal(line, &env); err != nil {
		log.Printf("[Relay] handleIncoming unmarshal failed: %v. Line: %q\n", err, line)
		secConn.Close()
		return
	}

	switch env.Type {
	case MsgAnnounce:
		var payload AnnouncePayload
		if err := json.Unmarshal(env.Payload, &payload); err == nil {
			r.mu.Lock()
			r.activeNodes[peerFP] = &peerEntry{
				controlConn:     secConn,
				directAddresses: payload.DirectAddresses,
			}

			// Update local routing table for Gossip
			ts := time.Now().UnixNano()
			r.globalRouting[peerFP] = &globalPeerEntry{
				relayAddr: r.listener.Addr().String(),
				timestamp: ts,
			}
			r.mu.Unlock()

			// Broadcast out to Mesh
			r.BroadcastGossipUpdate(peerFP, r.listener.Addr().String(), ts)
		}
		// A node's control connection normally stays open.
		// Wait for disconnect or further requests on this socket.
		r.controlLoop(secConn, peerFP, reader)
	case MsgRelayReq:
		r.handleRelayReq(secConn, peerFP, env.Payload)
	case MsgAcceptRelay:
		r.handleAcceptRelay(secConn, peerFP, env.Payload)
	case MsgGetRelays, MsgRelaysList, MsgGossipUpdate:
		// Incoming Relay-to-Relay Gossip/Control connection.

		// Ensure we record it as a neighbor for bi-directional broadcast
		r.mu.Lock()
		r.neighbors[secConn.RemoteAddr().String()] = secConn
		r.mu.Unlock()

		r.processGossipMessage(secConn.RemoteAddr().String(), env, secConn)
		// Hand off to dedicated neighbor connection handler
		r.handleNeighborConn(secConn.RemoteAddr().String(), secConn, reader)
	case MsgRelayInternalReq:
		// Serve as a dedicated physical link for 2-hop routing
		r.processGossipMessage(secConn.RemoteAddr().String(), env, secConn)
		// Do not enter handleNeighborConn, because secConn is now hijacked for io.Copy!
		// It will be closed automatically when io.Copy finishes.
	default:
		secConn.Close() // Unexpected initial msg
	}
}

func (r *RelayServer) controlLoop(conn *secure.SecureConn, fp string, reader *bufio.Reader) {
	defer func() {
		r.mu.Lock()
		if entry, ok := r.activeNodes[fp]; ok && entry.controlConn == conn {
			delete(r.activeNodes, fp)
			log.Printf("[Relay] Node disconnected: %s\n", fp[:8])
		}
		r.mu.Unlock()
		conn.Close()
	}()

	for {
		line, err := reader.ReadSlice('\n')
		if err != nil {
			return
		}
		var env Envelope
		if err := json.Unmarshal(line, &env); err != nil {
			return
		}
		switch env.Type {
		case MsgFindPeer:
			var req FindPeerPayload
			if err := json.Unmarshal(env.Payload, &req); err == nil {
				r.sendPeerInfo(conn, req.TargetFingerprint)
			}
		// Nodes can update Announce later if IPs change
		case MsgAnnounce:
			r.handleAnnounce(conn, fp, env.Payload)
		}
	}
}

// relayConn retains ownership when an ACCEPT_RELAY handler transfers its socket
// to a proxy, so shutdown and connection limits still cover that socket.
type relayConn struct {
	net.Conn
	relay *RelayServer
	once  sync.Once
	err   error
}

func (c *relayConn) Close() error {
	c.once.Do(func() {
		c.err = c.Conn.Close()
		c.relay.mu.Lock()
		delete(c.relay.connections, c)
		c.relay.connsCount--
		c.relay.mu.Unlock()
	})
	return c.err
}

// Close stops accepting, gossip maintenance and all relay-owned sockets.
func (r *RelayServer) Close() error {
	var err error
	r.closeOnce.Do(func() {
		r.cancel()
		err = r.listener.Close()
		r.mu.RLock()
		conns := make([]net.Conn, 0, len(r.connections)+len(r.neighbors))
		for conn := range r.connections {
			conns = append(conns, conn)
		}
		for _, conn := range r.neighbors {
			conns = append(conns, conn)
		}
		r.mu.RUnlock()
		for _, conn := range conns {
			conn.Close()
		}
	})
	return err
}

func (r *RelayServer) handleAnnounce(conn *secure.SecureConn, fp string, payload []byte) {
	var body AnnouncePayload
	if err := json.Unmarshal(payload, &body); err != nil {
		return
	}

	r.mu.Lock()
	r.activeNodes[fp] = &peerEntry{
		controlConn:     conn,
		directAddresses: body.DirectAddresses,
	}
	r.mu.Unlock()
	log.Printf("[Relay] Node announced: %s from %s (payload IPs: %v)\n", fp[:8], conn.RemoteAddr().String(), body.DirectAddresses)
}

func (r *RelayServer) sendPeerInfo(conn *secure.SecureConn, targetFP string) {
	r.mu.RLock()
	entry, ok := r.activeNodes[targetFP]
	r.mu.RUnlock()

	var payload []byte
	if ok {
		pl := FoundPeerPayload{
			TargetFingerprint: targetFP,
			DirectAddresses:   entry.directAddresses,
		}
		payload, _ = json.Marshal(pl)
	} else {
		payload, _ = json.Marshal(FoundPeerPayload{TargetFingerprint: targetFP})
	}

	env := Envelope{Type: MsgFoundPeer, Payload: payload}
	b, _ := json.Marshal(env)
	b = append(b, '\n')
	conn.Write(b)
}

func (r *RelayServer) handleRelayReq(conn *secure.SecureConn, requesterFP string, payload []byte) {
	var req RelayReqPayload
	if err := json.Unmarshal(payload, &req); err != nil {
		conn.Close()
		return
	}

	targetFP := req.TargetFingerprint
	if err := validateFingerprint(targetFP); err != nil {
		msg, _ := json.Marshal(Envelope{Type: MsgRelayAck, Payload: marshal(RelayAckPayload{
			TargetFingerprint: targetFP, Success: false, Reason: err.Error(),
		})})
		conn.Write(append(msg, '\n'))
		conn.Close()
		return
	}

	// Generate session token
	tk := make([]byte, 16)
	rand.Read(tk)
	token := hex.EncodeToString(tk)

	r.mu.RLock()
	activeEntry, isActive := r.activeNodes[targetFP]
	globalEntry, isGlobal := r.globalRouting[targetFP]

	log.Printf("[Relay] handleRelayReq Target: %s, isActive: %v, isGlobal: %v\n", targetFP[:8], isActive, isGlobal)

	if !isActive {
		if isGlobal && globalEntry.relayAddr != r.listener.Addr().String() {
			r.mu.RUnlock()
			r.handleRemoteRelayReq(conn, requesterFP, targetFP, globalEntry.relayAddr)
			return
		}

		r.mu.RUnlock()
		msg, _ := json.Marshal(Envelope{
			Type:    MsgRelayAck,
			Payload: marshal(RelayAckPayload{TargetFingerprint: targetFP, Success: false, Reason: "peer offline"}),
		})
		conn.Write(append(msg, '\n'))
		conn.Close()
		return
	}
	r.mu.RUnlock()
	entry := activeEntry

	sess := &activeSession{
		requesterConn: conn,
		waitCh:        make(chan net.Conn, 1),
	}
	r.mu.Lock()
	r.pendingSessions[token] = sess
	r.mu.Unlock()
	defer func() {
		r.mu.Lock()
		delete(r.pendingSessions, token)
		var late net.Conn
		select {
		case late = <-sess.waitCh:
		default:
		}
		r.mu.Unlock()
		if late != nil {
			late.Close()
		}
	}()

	// Notify target
	inMsg := IncomingRelayPayload{
		RequesterFingerprint: requesterFP,
		SessionToken:         token,
	}
	env := Envelope{Type: MsgIncomingRelay, Payload: marshal(inMsg)}
	b, _ := json.Marshal(env)
	log.Printf("[Relay] Sending MsgIncomingRelay to target %s\n", targetFP[:8])
	entry.controlConn.Write(append(b, '\n'))

	// Wait for target
	select {
	case targetConn := <-sess.waitCh:
		// Target has connected!
		// Tell requester it's ready.
		ack := Envelope{Type: MsgRelayAck, Payload: marshal(RelayAckPayload{TargetFingerprint: targetFP, Success: true})}
		ab, _ := json.Marshal(ack)
		conn.Write(append(ab, '\n'))

		// Tell target to go raw (no need here, target handles it on MsgAcceptRelay)

		// Dumb Pipe! Pump data both ways.
		proxyConnections(conn, targetConn)

	case <-time.After(10 * time.Second):
		// Timeout
		r.mu.Lock()
		delete(r.pendingSessions, token)
		r.mu.Unlock()
		conn.Close()
	case <-r.ctx.Done():
		conn.Close()
	}
}

func (r *RelayServer) handleAcceptRelay(conn *secure.SecureConn, fp string, payload []byte) {
	var req AcceptRelayPayload
	if err := json.Unmarshal(payload, &req); err != nil {
		conn.Close()
		return
	}

	r.mu.Lock()
	sess, ok := r.pendingSessions[req.SessionToken]
	if ok {
		delete(r.pendingSessions, req.SessionToken)
		// Publish while holding the session lock so timeout cleanup can drain
		// a simultaneous accept instead of orphaning its socket.
		sess.waitCh <- conn
	}
	r.mu.Unlock()

	if !ok {
		conn.Close()
		return
	}
	// connection transfers to the pipe in handleRelayReq...
}

func (r *RelayServer) handleRemoteRelayReq(requesterConn *secure.SecureConn, requesterFP, targetFP, remoteRelayAddr string) {
	// Open physical pipeline to remote Relay (2-Hop segment)
	ctx, cancel := context.WithTimeout(r.ctx, setupTimeout(r.config.SetupTimeout))
	defer cancel()
	conn, err := r.dialer.Dial(ctx, remoteRelayAddr)
	if err != nil {
		log.Printf("[Relay] handleRemoteRelayReq Dial failed: %v", err)
		msg, _ := json.Marshal(Envelope{Type: MsgRelayAck, Payload: marshal(RelayAckPayload{TargetFingerprint: targetFP, Success: false, Reason: "remote relay unreachable"})})
		requesterConn.Write(append(msg, '\n'))
		requesterConn.Close()
		return
	}
	log.Printf("[Relay] handleRemoteRelayReq Dial %s succeeded", remoteRelayAddr)
	finish := guardSetup(ctx, conn)
	finished := false
	defer func() {
		if !finished {
			finish()
		}
	}()

	secConn, err := secure.HandshakeInitiator(conn, r.identity, secure.AnyFingerprint)
	if err != nil {
		conn.Close()
		msg, _ := json.Marshal(Envelope{Type: MsgRelayAck, Payload: marshal(RelayAckPayload{TargetFingerprint: targetFP, Success: false, Reason: "remote relay handshake failed"})})
		requesterConn.Write(append(msg, '\n'))
		requesterConn.Close()
		return
	}

	req := Envelope{Type: MsgRelayInternalReq, Payload: marshal(RelayInternalReqPayload{
		TargetFingerprint: targetFP,
		SourceFingerprint: requesterFP,
	})}
	b, _ := json.Marshal(req)
	secConn.Write(append(b, '\n'))

	// Wait for MsgRelayAck from remote relay
	// Use 1-byte read to avoid consuming trailing tunnel data in bufio buffer
	line := make([]byte, 0, 256)
	buf := make([]byte, 1)
	for {
		n, err := secConn.Read(buf)
		if err != nil {
			log.Printf("[Relay] handleRemoteRelayReq secConn block error: %v", err)
			secConn.Close()
			requesterConn.Close()
			return
		}
		if n > 0 {
			if buf[0] == '\n' {
				break
			}
			line = append(line, buf[0])
		}
	}

	var env Envelope
	if err := json.Unmarshal(line, &env); err != nil {
		log.Printf("[Relay] handleRemoteRelayReq unmarshal failed: %v, line: %s\n", err, string(line))
		secConn.Close()
		requesterConn.Close()
		return
	}

	if env.Type == MsgRelayAck {
		if err := finish(); err != nil {
			conn.Close()
			requesterConn.Close()
			return
		}
		finished = true
		// Forward RELAY_ACK to original requester.
		rb, _ := json.Marshal(env)
		requesterConn.Write(append(rb, '\n'))

		// Pipe the connections!
		proxyConnections(requesterConn, secConn)
	}

	secConn.Close()
	requesterConn.Close()
}

func proxyConnections(a, b net.Conn) {
	var copies sync.WaitGroup
	copies.Add(2)
	pump := func(dst, src net.Conn) {
		defer copies.Done()
		io.Copy(dst, src)
		// IConn has no half-close API. Either direction ending terminates
		// the tunnel and interrupts the other direction's blocked read.
		a.Close()
		b.Close()
	}
	go pump(a, b)
	pump(b, a)
	copies.Wait()
}

func marshal(v interface{}) []byte {
	b, _ := json.Marshal(v)
	return b
}

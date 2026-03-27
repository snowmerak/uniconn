package p2p

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"log"
	"math/rand"
	"strings"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go/secure"
)

// StartGossipLoop kicks off the background mechanisms for peering and syncing.
func (r *RelayServer) StartGossipLoop() {
	r.mu.Lock()
	for _, seed := range r.config.SeedRelays {
		r.knownRelays[seed] = struct{}{}
	}
	r.mu.Unlock()

	go r.maintainNeighbors()
}

func (r *RelayServer) maintainNeighbors() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()

	// Initial bootstrap
	r.reconnectNeighbors()

	for range ticker.C {
		r.reconnectNeighbors()
	}
}

func (r *RelayServer) reconnectNeighbors() {
	r.mu.RLock()
	activeCount := len(r.neighbors)
	maxNeighbors := r.config.MaxNeighbors
	
	if maxNeighbors <= 0 || activeCount >= maxNeighbors {
		r.mu.RUnlock()
		return
	}

	var candidates []string
	for addr := range r.knownRelays {
		if _, ok := r.neighbors[addr]; !ok && addr != r.listener.Addr().String() {
			candidates = append(candidates, addr)
		}
	}
	r.mu.RUnlock()

	// Shuffle candidates for random selection
	rand.Shuffle(len(candidates), func(i, j int) {
		candidates[i], candidates[j] = candidates[j], candidates[i]
	})

	needed := maxNeighbors - activeCount
	for i := 0; i < len(candidates) && i < needed; i++ {
		addr := candidates[i]
		go r.connectToNeighbor(addr)
	}
}

func (r *RelayServer) connectToNeighbor(addr string) {
	conn, err := r.dialer.Dial(context.Background(), addr)
	if err != nil {
		log.Printf("[Gossip] Dial to %s failed: %v", addr, err)
		return
	}
	log.Printf("[Gossip] Dial to %s succeeded", addr)

	secConn, err := secure.HandshakeInitiator(conn, r.identity, secure.AnyFingerprint)
	if err != nil {
		log.Printf("[Gossip] Handshake to %s failed: %v", addr, err)
		conn.Close()
		return
	}
	log.Printf("[Gossip] Handshake to %s succeeded", addr)

	r.mu.Lock()
	r.neighbors[addr] = secConn
	r.mu.Unlock()

	// Request Relays List
	getRelaysMsg := Envelope{Type: MsgGetRelays, Payload: marshal(GetRelaysPayload{})}
	b, _ := json.Marshal(getRelaysMsg)
	secConn.Write(append(b, '\n'))

	// Handle incoming gossip/control on this neighbor connection
	reader := bufio.NewReader(secConn)
	go r.handleNeighborConn(addr, secConn, reader)
}

func (r *RelayServer) handleNeighborConn(addr string, secConn *secure.SecureConn, reader *bufio.Reader) {
	defer func() {
		secConn.Close()
		r.mu.Lock()
		delete(r.neighbors, addr)
		r.mu.Unlock()
	}()

	for {
		line, err := reader.ReadBytes('\n')
		if err != nil {
			if err != io.EOF && !strings.Contains(err.Error(), "closed network connection") {
				log.Printf("[Gossip] Read error from %s: %v", addr, err)
			}
			return
		}
		var env Envelope
		if err := json.Unmarshal(line, &env); err != nil {
			log.Printf("[Gossip] JSON unmarshal error from %s: %v. Line: %s", addr, err, line)
			return
		}
		
		r.processGossipMessage(addr, env, secConn)
	}
}

// BroadcastGossipUpdate spreads a node's whereabouts to all connected neighbors.
func (r *RelayServer) BroadcastGossipUpdate(fp string, addr string, ts int64) {
	payload := GossipUpdatePayload{
		Fingerprint:  fp,
		RelayAddress: addr,
		Timestamp:    ts,
	}
	msg := Envelope{Type: MsgGossipUpdate, Payload: marshal(payload)}
	b, _ := json.Marshal(msg)

	r.mu.RLock()
	defer r.mu.RUnlock()
	
	for _, neighbor := range r.neighbors {
		// Non-blocking best-effort broadcast to neighbors
		go func(conn *secure.SecureConn) {
			conn.Write(append(b, '\n'))
		}(neighbor)
	}
}

func (r *RelayServer) processGossipMessage(senderAddr string, env Envelope, secConn *secure.SecureConn) {
	switch env.Type {
	case MsgGetRelays:
		r.mu.RLock()
		var list []string
		for addr := range r.knownRelays {
			list = append(list, addr)
		}
		r.mu.RUnlock()
		
		resp := Envelope{
			Type:    MsgRelaysList,
			Payload: marshal(RelaysListPayload{RelayAddresses: list}),
		}
		b, _ := json.Marshal(resp)
		secConn.Write(append(b, '\n'))

	case MsgRelaysList:
		var payload RelaysListPayload
		if err := json.Unmarshal(env.Payload, &payload); err == nil {
			r.mu.Lock()
			for _, addr := range payload.RelayAddresses {
				r.knownRelays[addr] = struct{}{}
			}
			r.mu.Unlock()
		}

	case MsgGossipUpdate:
		var payload GossipUpdatePayload
		if err := json.Unmarshal(env.Payload, &payload); err == nil {
			r.mu.Lock()
			entry, exists := r.globalRouting[payload.Fingerprint]
			if !exists || entry.timestamp < payload.Timestamp {
				r.globalRouting[payload.Fingerprint] = &globalPeerEntry{
					relayAddr: payload.RelayAddress,
					timestamp: payload.Timestamp,
				}
				r.mu.Unlock()
				log.Printf("[Gossip] Learned %s at %s", payload.Fingerprint[:8], payload.RelayAddress)
				r.BroadcastGossipUpdate(payload.Fingerprint, payload.RelayAddress, payload.Timestamp)
			} else {
				r.mu.Unlock()
			}
		}

	case MsgRelayInternalReq:
		// Handling incoming 2-Hop proxy request from another relay
		var payload RelayInternalReqPayload
		if err := json.Unmarshal(env.Payload, &payload); err == nil {
			r.handleRelayReq(secConn, payload.SourceFingerprint, env.Payload)
		}
	}
}

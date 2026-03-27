package p2p

import (
	"github.com/snowmerak/uniconn/uniconn-go/multi"
)

// MsgType identifies the type of the control message.s between a Node and a Relay Server.
// All messages are sent over an already established SecureConn (E2EE), so
// intermediaries cannot read these control messages.
type MsgType string

const (
	// MsgAnnounce is sent by a Node to the Relay to register its presence,
	// direct addresses (if allowed), and supported transport protocols.
	MsgAnnounce MsgType = "ANNOUNCE"

	// MsgFindPeer is sent by a Node to query the Relay for a target peer's 
	// direct contact info. If found, Relay replies with MsgFoundPeer.
	MsgFindPeer MsgType = "FIND_PEER"

	// MsgFoundPeer is sent by the Relay containing the target peer's info.
	MsgFoundPeer MsgType = "FOUND_PEER"

	// MsgRelayReq is sent by a Node to ask the Relay to act as a dumb-pipe 
	// proxy to another peer.
	MsgRelayReq MsgType = "RELAY_REQ"

	// MsgIncomingRelay is sent by the Relay to the target peer's control
	// connection, requesting it to open a new connection for dumb pipe proxying.
	MsgIncomingRelay MsgType = "INCOMING_RELAY"

	// MsgAcceptRelay is sent by the target peer upon opening a new connection
	// to the Relay, to link with the requester's waiting RelayReq.
	// After this message, the TCP/Stream drops into Raw Byte forwarding.
	MsgAcceptRelay MsgType = "ACCEPT_RELAY"

	// MsgRelayAck is sent by Relay indicating the byte-level proxy is established.
	// IMPORTANT: Following this message, the TCP/Stream connection switches to 
	// Raw Byte forwarding.
	MsgRelayAck MsgType = "RELAY_ACK"

	// MsgGetRelays is sent by a Relay to another Relay to request known relay addresses.
	MsgGetRelays MsgType = "GET_RELAYS"

	// MsgRelaysList is the response to MsgGetRelays containing relay endpoints.
	MsgRelaysList MsgType = "RELAYS_LIST"

	// MsgGossipUpdate is sent between Relay neighbors to propagate fingerprint mappings.
	MsgGossipUpdate MsgType = "GOSSIP_UPDATE"

	// MsgRelayInternalReq is sent from Relay A to Relay B to initiate the 2nd hop of a proxy tunnel.
	MsgRelayInternalReq MsgType = "RELAY_INTERNAL_REQ"

	// MsgError is returned when an operation fails at the Relay.
	MsgError MsgType = "ERROR"
)

// Envelope wraps all protocol messages.
type Envelope struct {
	Type    MsgType `json:"type"`
	Payload []byte  `json:"payload,omitempty"` // JSON-encoded underlying payload Structure
}

// AnnouncePayload is the content for MsgAnnounce.
type AnnouncePayload struct {
	// Fingerprint is the sender Node's unique identity.
	Fingerprint string `json:"fingerprint"`
	
	// SupportedProtocols lists the uniconn multi.Protocol supported by the Node listener.
	SupportedProtocols []multi.Protocol `json:"supported_protocols,omitempty"`

	// DirectAddresses lists endpoints where the Node can be reached (Hole punching/Public IP).
	// Example: "192.168.1.100:19000", "public-ip:19000"
	DirectAddresses []string `json:"direct_addresses,omitempty"`
}

// FindPeerPayload is the content for MsgFindPeer.
type FindPeerPayload struct {
	TargetFingerprint string `json:"target_fingerprint"`
}

// FoundPeerPayload is the content for MsgFoundPeer.
type FoundPeerPayload struct {
	TargetFingerprint  string           `json:"target_fingerprint"`
	SupportedProtocols []multi.Protocol `json:"supported_protocols,omitempty"`
	DirectAddresses    []string         `json:"direct_addresses,omitempty"`
}

// RelayReqPayload is the content for MsgRelayReq.
type RelayReqPayload struct {
	TargetFingerprint string `json:"target_fingerprint"`
}

// IncomingRelayPayload is the content for MsgIncomingRelay.
type IncomingRelayPayload struct {
	RequesterFingerprint string `json:"requester_fingerprint"`
	SessionToken         string `json:"session_token"`
}

// AcceptRelayPayload is the content for MsgAcceptRelay.
type AcceptRelayPayload struct {
	SessionToken string `json:"session_token"`
}

// RelayAckPayload is the content for MsgRelayAck.
type RelayAckPayload struct {
	TargetFingerprint string `json:"target_fingerprint"`
	Success           bool   `json:"success"`
	Reason            string `json:"reason,omitempty"`
}

// GetRelaysPayload is the content for MsgGetRelays.
type GetRelaysPayload struct{}

// RelaysListPayload is the content for MsgRelaysList.
type RelaysListPayload struct {
	RelayAddresses []string `json:"relay_addresses"`
}

// GossipUpdatePayload is the content for MsgGossipUpdate.
type GossipUpdatePayload struct {
	Fingerprint  string `json:"fingerprint"`
	RelayAddress string `json:"relay_address"`
	Timestamp    int64  `json:"timestamp"`
}

// RelayInternalReqPayload is the content for MsgRelayInternalReq.
type RelayInternalReqPayload struct {
	TargetFingerprint string `json:"target_fingerprint"`
	SourceFingerprint string `json:"source_fingerprint"`
}

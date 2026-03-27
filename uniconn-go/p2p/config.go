package p2p

import "github.com/snowmerak/uniconn/uniconn-go/multi"

// NodeConfig defines the settings for a P2P node.
type NodeConfig struct {
	// AllowDirectConnection specifies whether the node is allowed to attempt
	// direct connections (Hole Punching) to other peers. If false, all
	// traffic will be routed through the Relay servers, preserving IP anonymity.
	AllowDirectConnection bool

	// RelayAddresses contains the list of known Relay servers to connect to
	// for discovery, signaling, and fallback TURN-like relaying.
	RelayAddresses []multi.TransportConfig
}

// DefaultNodeConfig provides basic defaults favoring hybrid connections.
var DefaultNodeConfig = NodeConfig{
	AllowDirectConnection: true,
	RelayAddresses:        nil, // Must be provided by the user
}

// RelayConfig defines the settings for a P2P Relay server.
type RelayConfig struct {
	// MaxConnections enforces the top-level FD limit for all inbound/outbound relay streams.
	MaxConnections int

	// MaxNeighbors limits the number of persistent Gossip peers the relay will connect to.
	MaxNeighbors int

	// SeedRelays provides a list of known relay endpoints for bootstrapping into the mesh.
	SeedRelays []string
}

// DefaultRelayConfig provides basic defaults for a scalable Relay node.
var DefaultRelayConfig = RelayConfig{
	MaxConnections: 10000,
	MaxNeighbors:   5,
	SeedRelays:     nil, // E.g., []string{"192.168.1.10:19000"}
}

package multi

import "time"

// Protocol identifies a network transport protocol.
type Protocol string

const (
	// ProtoWebTransport is HTTP/3-based WebTransport (browser native, UDP).
	ProtoWebTransport Protocol = "webtransport"
	// ProtoQUIC is QUIC (UDP, multiplexing, 0-RTT).
	ProtoQUIC Protocol = "quic"
	// ProtoWebSocket is WebSocket (web-compatible, bidirectional).
	ProtoWebSocket Protocol = "websocket"
	// ProtoKCP is KCP (low-latency UDP, ARQ-based reliable delivery).
	ProtoKCP Protocol = "kcp"
	// ProtoTCP is plain TCP (most compatible, always works).
	ProtoTCP Protocol = "tcp"
)

// DefaultPriority defines the default protocol preference order.
// Higher-performance / modern protocols are tried first.
var DefaultPriority = []Protocol{
	ProtoWebTransport,
	ProtoQUIC,
	ProtoWebSocket,
	ProtoKCP,
	ProtoTCP,
}

// DefaultDialTimeout is the default per-protocol connection timeout.
const DefaultDialTimeout = 5 * time.Second

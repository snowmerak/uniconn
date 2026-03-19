// Package uniconn provides a universal connection interface
// that abstracts various network protocols (TCP, WebSocket, QUIC,
// WebTransport, KCP) behind Go's standard net.Conn interface.
//
// Each protocol adapter implements the Listener and Dialer interfaces,
// returning net.Conn-compatible connections regardless of the underlying protocol.
package uniconn

import (
	"context"
	"net"
)

// Listener accepts incoming connections and returns them as net.Conn.
// Each protocol adapter implements this interface so that server code
// can work with any transport transparently.
type Listener interface {
	// Accept waits for and returns the next connection.
	// The returned net.Conn provides identical Read/Write/Close
	// behavior regardless of the underlying protocol.
	Accept() (net.Conn, error)

	// Close stops the listener from accepting new connections.
	Close() error

	// Addr returns the listener's network address.
	Addr() net.Addr
}

// Dialer creates outgoing connections.
// Each protocol adapter implements this interface so that client code
// can connect to any transport transparently.
type Dialer interface {
	// Dial establishes a connection to the given address.
	// The returned net.Conn provides identical Read/Write/Close
	// behavior regardless of the underlying protocol.
	Dial(ctx context.Context, address string) (net.Conn, error)
}

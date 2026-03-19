package kcp

import (
	"net"

	kcpgo "github.com/xtaci/kcp-go/v5"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// ListenConfig holds configuration for a KCP listener.
type ListenConfig struct {
	// DataShards is the number of data shards for FEC (Forward Error Correction).
	// Set to 0 to disable FEC.
	DataShards int
	// ParityShards is the number of parity shards for FEC.
	ParityShards int
	// Block optionally specifies a block cipher for encryption.
	// nil means no encryption.
	Block kcpgo.BlockCrypt
}

// listener wraps kcp.Listener to implement uniconn.Listener.
type listener struct {
	ln *kcpgo.Listener
}

// Listen creates a KCP listener on the given address.
// The address format is "host:port".
func Listen(address string, config *ListenConfig) (uniconn.Listener, error) {
	if config == nil {
		config = &ListenConfig{}
	}

	ln, err := kcpgo.ListenWithOptions(
		address,
		config.Block,
		config.DataShards,
		config.ParityShards,
	)
	if err != nil {
		return nil, err
	}

	return &listener{ln: ln}, nil
}

// Accept waits for and returns the next KCP connection.
// kcp.UDPSession already implements net.Conn.
func (l *listener) Accept() (net.Conn, error) {
	return l.ln.AcceptKCP()
}

// Close stops the KCP listener.
func (l *listener) Close() error {
	return l.ln.Close()
}

// Addr returns the listener's network address.
func (l *listener) Addr() net.Addr {
	return l.ln.Addr()
}

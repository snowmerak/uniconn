package kcp

import (
	"context"
	"net"

	kcpgo "github.com/xtaci/kcp-go/v5"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// DialConfig holds configuration for KCP dialing.
type DialConfig struct {
	// DataShards is the number of data shards for FEC.
	DataShards int
	// ParityShards is the number of parity shards for FEC.
	ParityShards int
	// Block optionally specifies a block cipher for encryption.
	Block kcpgo.BlockCrypt
}

// dialer implements uniconn.Dialer for KCP connections.
type dialer struct {
	config *DialConfig
}

// NewDialer creates a new KCP dialer.
func NewDialer(config *DialConfig) uniconn.Dialer {
	if config == nil {
		config = &DialConfig{}
	}
	return &dialer{config: config}
}

// Dial establishes a KCP connection to the given address.
// kcp.UDPSession already implements net.Conn.
// The context is respected via a goroutine that cancels the connection.
func (d *dialer) Dial(ctx context.Context, address string) (net.Conn, error) {
	type result struct {
		conn net.Conn
		err  error
	}

	ch := make(chan result, 1)
	go func() {
		conn, err := kcpgo.DialWithOptions(
			address,
			d.config.Block,
			d.config.DataShards,
			d.config.ParityShards,
		)
		ch <- result{conn: conn, err: err}
	}()

	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case r := <-ch:
		return r.conn, r.err
	}
}

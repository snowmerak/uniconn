package tcp

import (
	"context"
	"net"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// DialConfig holds configuration for TCP dialing.
type DialConfig struct {
	// KeepAlive enables TCP keep-alive on the connection.
	KeepAlive bool
	// KeepAlivePeriod sets the keep-alive period. Zero means default.
	KeepAlivePeriod int // seconds
	// LocalAddr optionally specifies the local address to bind to.
	LocalAddr string
}

// dialer implements uniconn.Dialer for TCP connections.
type dialer struct {
	config *DialConfig
}

// NewDialer creates a new TCP dialer with the given configuration.
func NewDialer(config *DialConfig) uniconn.Dialer {
	if config == nil {
		config = &DialConfig{}
	}
	return &dialer{config: config}
}

// Dial establishes a TCP connection to the given address.
func (d *dialer) Dial(ctx context.Context, address string) (net.Conn, error) {
	raddr, err := net.ResolveTCPAddr("tcp", address)
	if err != nil {
		return nil, err
	}

	var laddr *net.TCPAddr
	if d.config.LocalAddr != "" {
		laddr, err = net.ResolveTCPAddr("tcp", d.config.LocalAddr)
		if err != nil {
			return nil, err
		}
	}

	// Use a net.Dialer for context support
	nd := &net.Dialer{
		LocalAddr: laddr,
	}

	conn, err := nd.DialContext(ctx, "tcp", raddr.String())
	if err != nil {
		return nil, err
	}

	tcpConn := conn.(*net.TCPConn)

	if d.config.KeepAlive {
		_ = tcpConn.SetKeepAlive(true)
		if d.config.KeepAlivePeriod > 0 {
			_ = tcpConn.SetKeepAlivePeriod(
				time.Duration(d.config.KeepAlivePeriod) * time.Second,
			)
		}
	}

	return tcpConn, nil
}

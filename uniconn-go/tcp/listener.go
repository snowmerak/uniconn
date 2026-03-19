package tcp

import (
	"net"
	"time"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// ListenConfig holds configuration for a TCP listener.
type ListenConfig struct {
	// KeepAlive enables TCP keep-alive on accepted connections.
	KeepAlive bool
	// KeepAlivePeriod sets the keep-alive period. Zero means default.
	KeepAlivePeriod int // seconds
}

// listener wraps net.TCPListener to implement uniconn.Listener.
type listener struct {
	ln     *net.TCPListener
	config *ListenConfig
}

// Listen creates a TCP listener on the given address.
// The address format is "host:port" as accepted by net.ResolveTCPAddr.
func Listen(address string, config *ListenConfig) (uniconn.Listener, error) {
	if config == nil {
		config = &ListenConfig{}
	}

	addr, err := net.ResolveTCPAddr("tcp", address)
	if err != nil {
		return nil, err
	}

	ln, err := net.ListenTCP("tcp", addr)
	if err != nil {
		return nil, err
	}

	return &listener{
		ln:     ln,
		config: config,
	}, nil
}

// Accept waits for and returns the next TCP connection.
func (l *listener) Accept() (net.Conn, error) {
	conn, err := l.ln.AcceptTCP()
	if err != nil {
		return nil, err
	}

	if l.config.KeepAlive {
		_ = conn.SetKeepAlive(true)
		if l.config.KeepAlivePeriod > 0 {
			_ = conn.SetKeepAlivePeriod(
				time.Duration(l.config.KeepAlivePeriod) * time.Second,
			)
		}
	}

	return conn, nil
}

// Close stops the listener.
func (l *listener) Close() error {
	return l.ln.Close()
}

// Addr returns the listener's network address.
func (l *listener) Addr() net.Addr {
	return l.ln.Addr()
}

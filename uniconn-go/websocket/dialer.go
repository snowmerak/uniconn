package websocket

import (
	"context"
	"crypto/tls"
	"net"
	"net/http"

	ws "github.com/gorilla/websocket"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// DialConfig holds configuration for WebSocket dialing.
type DialConfig struct {
	// Headers specifies additional HTTP headers for the handshake.
	Headers http.Header

	// TLSConfig optionally specifies TLS configuration for wss://.
	TLSConfig *tls.Config

	// ReadBufferSize specifies the read buffer size.
	ReadBufferSize int

	// WriteBufferSize specifies the write buffer size.
	WriteBufferSize int
}

// dialer implements uniconn.Dialer for WebSocket connections.
type dialer struct {
	config *DialConfig
}

// NewDialer creates a new WebSocket dialer with the given configuration.
func NewDialer(config *DialConfig) uniconn.Dialer {
	if config == nil {
		config = &DialConfig{}
	}
	return &dialer{config: config}
}

// Dial establishes a WebSocket connection to the given URL.
// The address should be a WebSocket URL (ws:// or wss://).
func (d *dialer) Dial(ctx context.Context, address string) (net.Conn, error) {
	wsDialer := &ws.Dialer{
		TLSClientConfig: d.config.TLSConfig,
		ReadBufferSize:  d.config.ReadBufferSize,
		WriteBufferSize: d.config.WriteBufferSize,
	}

	c, _, err := wsDialer.DialContext(ctx, address, d.config.Headers)
	if err != nil {
		return nil, err
	}

	return WrapConn(c), nil
}

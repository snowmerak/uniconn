package webtransport

import (
	"context"
	"crypto/tls"
	"net"
	"net/http"

	qc "github.com/quic-go/quic-go"
	wt "github.com/quic-go/webtransport-go"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// DialConfig holds configuration for WebTransport dialing.
type DialConfig struct {
	// TLSConfig optionally specifies TLS configuration.
	TLSConfig *tls.Config

	// QUICConfig optionally specifies QUIC-specific settings.
	QUICConfig *qc.Config

	// Headers optionally specifies HTTP headers for the CONNECT request.
	Headers http.Header
}

// dialer implements uniconn.Dialer for WebTransport.
type dialer struct {
	config  *DialConfig
	wtDial  *wt.Dialer
}

// NewDialer creates a new WebTransport dialer.
func NewDialer(config *DialConfig) uniconn.Dialer {
	if config == nil {
		config = &DialConfig{}
	}
	d := &dialer{
		config: config,
		wtDial: &wt.Dialer{
			TLSClientConfig: config.TLSConfig,
			QUICConfig:      config.QUICConfig,
		},
	}
	return d
}

// Dial establishes a WebTransport connection to the given URL.
// The address should be an https:// URL.
func (d *dialer) Dial(ctx context.Context, address string) (net.Conn, error) {
	_, session, err := d.wtDial.Dial(ctx, address, d.config.Headers)
	if err != nil {
		return nil, err
	}

	stream, err := session.OpenStreamSync(ctx)
	if err != nil {
		session.CloseWithError(1, "failed to open stream")
		return nil, err
	}

	return WrapConn(session, stream), nil
}

// Close closes the underlying WebTransport dialer (HTTP/3 transport).
func (d *dialer) Close() error {
	return d.wtDial.Close()
}

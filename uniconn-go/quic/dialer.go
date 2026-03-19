package quic

import (
	"context"
	"crypto/tls"
	"net"

	qc "github.com/quic-go/quic-go"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// DialConfig holds configuration for QUIC dialing.
type DialConfig struct {
	// TLSConfig is required for QUIC.
	TLSConfig *tls.Config

	// QUICConfig optionally specifies QUIC-specific settings.
	QUICConfig *qc.Config
}

// dialer implements uniconn.Dialer for QUIC connections.
type dialer struct {
	config *DialConfig
}

// NewDialer creates a new QUIC dialer.
func NewDialer(config *DialConfig) uniconn.Dialer {
	if config == nil {
		config = &DialConfig{}
	}
	return &dialer{config: config}
}

// Dial establishes a QUIC connection and opens a single bidirectional stream.
func (d *dialer) Dial(ctx context.Context, address string) (net.Conn, error) {
	tlsConf := d.config.TLSConfig
	if tlsConf == nil {
		return nil, &net.OpError{
			Op:  "dial",
			Net: "quic",
			Err: &net.AddrError{Err: "TLS configuration is required for QUIC"},
		}
	}
	// Ensure ALPN is set
	hasALPN := false
	for _, p := range tlsConf.NextProtos {
		if p == "uniconn" {
			hasALPN = true
			break
		}
	}
	if !hasALPN {
		tlsConf.NextProtos = append(tlsConf.NextProtos, "uniconn")
	}

	session, err := qc.DialAddr(ctx, address, tlsConf, d.config.QUICConfig)
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

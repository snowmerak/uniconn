package quic

import (
	"context"
	"crypto/tls"
	"net"

	qc "github.com/quic-go/quic-go"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// ListenConfig holds configuration for a QUIC listener.
type ListenConfig struct {
	// TLSConfig is required for QUIC. It must have at least one certificate.
	TLSConfig *tls.Config

	// QUICConfig optionally specifies QUIC-specific settings.
	QUICConfig *qc.Config
}

// listener implements uniconn.Listener for QUIC.
type listener struct {
	ql     *qc.Listener
	config *ListenConfig
}

// Listen creates a QUIC listener on the given address.
// TLSConfig is required.
func Listen(address string, config *ListenConfig) (uniconn.Listener, error) {
	if config == nil {
		config = &ListenConfig{}
	}

	tlsConf := config.TLSConfig
	if tlsConf == nil {
		return nil, &net.OpError{
			Op:  "listen",
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

	ql, err := qc.ListenAddr(address, tlsConf, config.QUICConfig)
	if err != nil {
		return nil, err
	}

	return &listener{ql: ql, config: config}, nil
}

// Accept waits for a new QUIC session and opens a single bidirectional stream.
func (l *listener) Accept() (net.Conn, error) {
	session, err := l.ql.Accept(context.Background())
	if err != nil {
		return nil, err
	}

	stream, err := session.AcceptStream(context.Background())
	if err != nil {
		session.CloseWithError(1, "failed to accept stream")
		return nil, err
	}

	return WrapConn(session, stream), nil
}

// Close stops the QUIC listener.
func (l *listener) Close() error {
	return l.ql.Close()
}

// Addr returns the listener's network address.
func (l *listener) Addr() net.Addr {
	return l.ql.Addr()
}

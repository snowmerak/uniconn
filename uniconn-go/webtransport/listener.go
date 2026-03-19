package webtransport

import (
	"crypto/tls"
	"fmt"
	"net"
	"net/http"
	"sync"

	"github.com/quic-go/quic-go/http3"
	wt "github.com/quic-go/webtransport-go"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// ListenConfig holds configuration for a WebTransport listener.
type ListenConfig struct {
	// TLSConfig is required for WebTransport (HTTP/3).
	TLSConfig *tls.Config

	// CertFile is the path to the TLS certificate file.
	// Used by ListenAndServeTLS when no PacketConn is provided.
	CertFile string

	// KeyFile is the path to the TLS key file.
	// Used by ListenAndServeTLS when no PacketConn is provided.
	KeyFile string

	// Path is the HTTP path for WebTransport upgrades.
	// Defaults to "/" if empty.
	Path string
}

// listener implements uniconn.Listener for WebTransport.
type listener struct {
	server    *wt.Server
	pconn     net.PacketConn // owned when we bind manually
	connCh    chan net.Conn
	errCh     chan error
	closeOnce sync.Once
	done      chan struct{}
	addr      net.Addr
}

// Listen creates a WebTransport listener on the given address.
// TLSConfig is required.
func Listen(address string, config *ListenConfig) (uniconn.Listener, error) {
	if config == nil {
		config = &ListenConfig{}
	}
	if config.Path == "" {
		config.Path = "/"
	}

	if config.TLSConfig == nil {
		return nil, &net.OpError{
			Op:  "listen",
			Net: "webtransport",
			Err: &net.AddrError{Err: "TLS configuration is required for WebTransport"},
		}
	}

	l := &listener{
		connCh: make(chan net.Conn, 64),
		errCh:  make(chan error, 1),
		done:   make(chan struct{}),
	}

	// Manually bind a UDP socket so we know the actual port (supports :0).
	pconn, err := net.ListenPacket("udp", address)
	if err != nil {
		return nil, fmt.Errorf("webtransport: listen udp: %w", err)
	}
	l.pconn = pconn
	l.addr = pconn.LocalAddr()

	// Ensure h3 ALPN is present for HTTP/3 negotiation
	tlsCfg := config.TLSConfig.Clone()
	hasH3 := false
	for _, p := range tlsCfg.NextProtos {
		if p == "h3" {
			hasH3 = true
			break
		}
	}
	if !hasH3 {
		tlsCfg.NextProtos = append(tlsCfg.NextProtos, "h3")
	}

	h3Server := &http3.Server{
		Addr:      l.addr.String(),
		TLSConfig: tlsCfg,
	}

	// Configure H3 server for WebTransport: sets ENABLE_WEBTRANSPORT
	// in SETTINGS, enables datagrams, and injects ConnContext.
	wt.ConfigureHTTP3Server(h3Server)

	wtServer := &wt.Server{
		H3:          h3Server,
		CheckOrigin: func(r *http.Request) bool { return true },
	}

	mux := http.NewServeMux()
	mux.HandleFunc(config.Path, func(w http.ResponseWriter, r *http.Request) {
		session, err := wtServer.Upgrade(w, r)
		if err != nil {
			return
		}

		stream, err := session.AcceptStream(r.Context())
		if err != nil {
			session.CloseWithError(1, "failed to accept stream")
			return
		}

		select {
		case l.connCh <- WrapConn(session, stream):
		case <-l.done:
			session.CloseWithError(0, "listener closed")
		}
	})

	h3Server.Handler = mux
	l.server = wtServer

	go func() {
		if err := wtServer.Serve(pconn); err != nil {
			select {
			case l.errCh <- fmt.Errorf("webtransport listener: %w", err):
			default:
			}
		}
	}()

	return l, nil
}

// Accept waits for the next WebTransport session.
func (l *listener) Accept() (net.Conn, error) {
	select {
	case conn := <-l.connCh:
		return conn, nil
	case err := <-l.errCh:
		return nil, err
	case <-l.done:
		return nil, net.ErrClosed
	}
}

// Close shuts down the WebTransport server.
func (l *listener) Close() error {
	var err error
	l.closeOnce.Do(func() {
		close(l.done)
		err = l.server.Close()
		if l.pconn != nil {
			l.pconn.Close()
		}
	})
	return err
}

// Addr returns the listener's address.
func (l *listener) Addr() net.Addr {
	return l.addr
}

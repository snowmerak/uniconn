package multi

import (
	"fmt"
	"net"
	"net/http"
	"sync"

	uniconn "github.com/snowmerak/uniconn/uniconn-go"
)

// TransportConfig defines a single protocol listener and its advertised address.
type TransportConfig struct {
	// Protocol identifies the transport (e.g. ProtoTCP, ProtoWebSocket).
	Protocol Protocol
	// Address is the address advertised in the negotiate response.
	// This should be the externally-reachable address that clients use.
	Address string
	// Listener is an already-started uniconn.Listener for this protocol.
	Listener uniconn.Listener
}

// acceptResult carries a connection and the protocol it arrived on.
type acceptResult struct {
	conn     net.Conn
	protocol Protocol
	err      error
}

// MultiListener accepts connections from multiple protocol listeners
// and exposes a /negotiate HTTP endpoint for clients.
type MultiListener struct {
	transports    []TransportConfig
	negotiateSrv  *http.Server
	negotiateAddr net.Addr // actual negotiate listener address

	connCh    chan acceptResult
	closeOnce sync.Once
	done      chan struct{}
}

// NewMultiListener creates a multi-protocol listener.
//
// negotiateAddr is the bind address for the negotiate HTTP server
// (e.g. ":19000"). Each TransportConfig should contain an already-started
// Listener (created via tcp.Listen, websocket.Listen, etc.).
func NewMultiListener(negotiateAddr string, transports ...TransportConfig) (*MultiListener, error) {
	if len(transports) == 0 {
		return nil, fmt.Errorf("multi: at least one transport is required")
	}

	// Build negotiate entries from transport configs.
	entries := make([]ProtocolEntry, len(transports))
	for i, t := range transports {
		entries[i] = ProtocolEntry{Name: t.Protocol, Address: t.Address}
	}

	ml := &MultiListener{
		transports: transports,
		connCh:     make(chan acceptResult, 64),
		done:       make(chan struct{}),
	}

	// Start accept goroutines for each transport.
	for _, t := range transports {
		go ml.acceptLoop(t)
	}

	// Start negotiate HTTP server.
	ln, err := net.Listen("tcp", negotiateAddr)
	if err != nil {
		ml.Close()
		return nil, fmt.Errorf("multi: negotiate listen: %w", err)
	}
	ml.negotiateAddr = ln.Addr()

	mux := http.NewServeMux()
	mux.HandleFunc("/negotiate", NegotiateHandler(entries))

	ml.negotiateSrv = &http.Server{Handler: mux}
	go func() {
		if err := ml.negotiateSrv.Serve(ln); err != nil && err != http.ErrServerClosed {
			select {
			case ml.connCh <- acceptResult{err: fmt.Errorf("negotiate server: %w", err)}:
			default:
			}
		}
	}()

	return ml, nil
}

// NegotiateAddr returns the actual address the negotiate HTTP server is listening on.
func (ml *MultiListener) NegotiateAddr() net.Addr {
	return ml.negotiateAddr
}

func (ml *MultiListener) acceptLoop(t TransportConfig) {
	for {
		conn, err := t.Listener.Accept()
		select {
		case <-ml.done:
			if conn != nil {
				conn.Close()
			}
			return
		default:
		}

		if err != nil {
			select {
			case <-ml.done:
				return
			case ml.connCh <- acceptResult{err: fmt.Errorf("[%s] accept: %w", t.Protocol, err)}:
				return
			}
		}

		select {
		case <-ml.done:
			conn.Close()
			return
		case ml.connCh <- acceptResult{conn: conn, protocol: t.Protocol}:
		}
	}
}

// Accept returns the next connection from any protocol.
// It implements the uniconn.Listener interface.
func (ml *MultiListener) Accept() (net.Conn, error) {
	conn, _, err := ml.AcceptWith()
	return conn, err
}

// AcceptWith returns the next connection along with the protocol it came from.
func (ml *MultiListener) AcceptWith() (net.Conn, Protocol, error) {
	select {
	case <-ml.done:
		return nil, "", net.ErrClosed
	case r := <-ml.connCh:
		return r.conn, r.protocol, r.err
	}
}

// Close shuts down the negotiate server and all underlying listeners.
func (ml *MultiListener) Close() error {
	var firstErr error
	ml.closeOnce.Do(func() {
		close(ml.done)

		if ml.negotiateSrv != nil {
			if err := ml.negotiateSrv.Close(); err != nil && firstErr == nil {
				firstErr = err
			}
		}

		for _, t := range ml.transports {
			if err := t.Listener.Close(); err != nil && firstErr == nil {
				firstErr = err
			}
		}
	})
	return firstErr
}

// Addr returns the negotiate server's address.
func (ml *MultiListener) Addr() net.Addr {
	return ml.negotiateAddr
}

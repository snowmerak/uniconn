package websocket

import (
	"crypto/tls"
	"fmt"
	"net"
	"net/http"
	"sync"

	ws "github.com/gorilla/websocket"

	"github.com/snowmerak/uniconn/uniconn-go"
)

// ListenConfig holds configuration for a WebSocket listener.
type ListenConfig struct {
	// Path is the HTTP path to handle WebSocket upgrades on.
	// Defaults to "/" if empty.
	Path string

	// TLSConfig optionally specifies TLS configuration for wss://.
	TLSConfig *tls.Config

	// ReadBufferSize specifies the read buffer size for the upgrader.
	ReadBufferSize int

	// WriteBufferSize specifies the write buffer size for the upgrader.
	WriteBufferSize int

	// CheckOrigin is a function to validate the request Origin header.
	// If nil, all origins are allowed.
	CheckOrigin func(r *http.Request) bool
}

// listener implements uniconn.Listener for WebSocket connections.
type listener struct {
	httpServer *http.Server
	connCh     chan net.Conn
	errCh      chan error
	closeOnce  sync.Once
	done       chan struct{}
	addr       net.Addr
}

// Listen creates a WebSocket listener on the given address.
// The address format is "host:port".
func Listen(address string, config *ListenConfig) (uniconn.Listener, error) {
	if config == nil {
		config = &ListenConfig{}
	}
	if config.Path == "" {
		config.Path = "/"
	}

	ln, err := net.Listen("tcp", address)
	if err != nil {
		return nil, err
	}

	upgrader := ws.Upgrader{
		ReadBufferSize:  config.ReadBufferSize,
		WriteBufferSize: config.WriteBufferSize,
		CheckOrigin:     config.CheckOrigin,
	}
	if upgrader.CheckOrigin == nil {
		upgrader.CheckOrigin = func(r *http.Request) bool { return true }
	}

	l := &listener{
		connCh: make(chan net.Conn, 64),
		errCh:  make(chan error, 1),
		done:   make(chan struct{}),
		addr:   ln.Addr(),
	}

	mux := http.NewServeMux()
	mux.HandleFunc(config.Path, func(w http.ResponseWriter, r *http.Request) {
		c, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		select {
		case l.connCh <- WrapConn(c):
		case <-l.done:
			c.Close()
		}
	})

	l.httpServer = &http.Server{
		Handler: mux,
	}

	if config.TLSConfig != nil {
		ln = tls.NewListener(ln, config.TLSConfig)
	}

	go func() {
		if err := l.httpServer.Serve(ln); err != nil && err != http.ErrServerClosed {
			select {
			case l.errCh <- fmt.Errorf("websocket listener: %w", err):
			default:
			}
		}
	}()

	return l, nil
}

// Accept returns the next WebSocket connection.
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

// Close shuts down the listener.
func (l *listener) Close() error {
	var err error
	l.closeOnce.Do(func() {
		close(l.done)
		err = l.httpServer.Close()
	})
	return err
}

// Addr returns the listener's network address.
func (l *listener) Addr() net.Addr {
	return l.addr
}

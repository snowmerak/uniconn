package webtransport

import (
	"net"
	"time"

	wt "github.com/quic-go/webtransport-go"
)

// addr implements net.Addr for WebTransport connections.
type addr struct {
	network string
	str     string
}

func (a *addr) Network() string { return a.network }
func (a *addr) String() string  { return a.str }

// Conn wraps a *webtransport.Session + *webtransport.Stream to implement net.Conn.
// Following the "one connection = one session = one bidirectional stream" model.
type Conn struct {
	session *wt.Session
	stream  *wt.Stream
}

// WrapConn creates a net.Conn from a WebTransport session and stream.
func WrapConn(session *wt.Session, stream *wt.Stream) net.Conn {
	return &Conn{session: session, stream: stream}
}

func (c *Conn) Read(b []byte) (int, error) {
	return c.stream.Read(b)
}

func (c *Conn) Write(b []byte) (int, error) {
	return c.stream.Write(b)
}

// Close closes the stream and the underlying WebTransport session.
func (c *Conn) Close() error {
	c.stream.CancelRead(0)
	c.stream.CancelWrite(0)
	return c.session.CloseWithError(0, "closed")
}

func (c *Conn) LocalAddr() net.Addr {
	return &addr{
		network: "webtransport",
		str:     c.session.LocalAddr().String(),
	}
}

func (c *Conn) RemoteAddr() net.Addr {
	return &addr{
		network: "webtransport",
		str:     c.session.RemoteAddr().String(),
	}
}

func (c *Conn) SetDeadline(t time.Time) error {
	return c.stream.SetDeadline(t)
}

func (c *Conn) SetReadDeadline(t time.Time) error {
	return c.stream.SetReadDeadline(t)
}

func (c *Conn) SetWriteDeadline(t time.Time) error {
	return c.stream.SetWriteDeadline(t)
}

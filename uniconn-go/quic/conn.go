package quic

import (
	"net"
	"time"

	qc "github.com/quic-go/quic-go"
)

// addr implements net.Addr for QUIC connections.
type addr struct {
	network string
	str     string
}

func (a *addr) Network() string { return a.network }
func (a *addr) String() string  { return a.str }

// Conn wraps a *quic.Conn + *quic.Stream to implement net.Conn.
// Following the "one connection = one session = one bidirectional stream" model,
// each Conn holds exactly one bidirectional QUIC stream.
type Conn struct {
	session *qc.Conn
	stream  *qc.Stream
}

// WrapConn creates a net.Conn from a QUIC connection and its stream.
func WrapConn(session *qc.Conn, stream *qc.Stream) net.Conn {
	return &Conn{session: session, stream: stream}
}

func (c *Conn) Read(b []byte) (int, error) {
	return c.stream.Read(b)
}

func (c *Conn) Write(b []byte) (int, error) {
	return c.stream.Write(b)
}

// Close closes the stream and the underlying QUIC session.
func (c *Conn) Close() error {
	c.stream.CancelRead(0)
	c.stream.CancelWrite(0)
	return c.session.CloseWithError(0, "closed")
}

func (c *Conn) LocalAddr() net.Addr {
	return &addr{
		network: "quic",
		str:     c.session.LocalAddr().String(),
	}
}

func (c *Conn) RemoteAddr() net.Addr {
	return &addr{
		network: "quic",
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

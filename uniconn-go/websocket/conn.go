package websocket

import (
	"io"
	"net"
	"sync"
	"time"

	ws "github.com/gorilla/websocket"
)

// Conn wraps a gorilla/websocket.Conn to implement net.Conn.
// It converts the message-oriented WebSocket protocol into
// a stream-oriented interface compatible with net.Conn.
type Conn struct {
	conn   *ws.Conn
	reader io.Reader
	rmu    sync.Mutex
	wmu    sync.Mutex
}

// WrapConn wraps a gorilla/websocket.Conn into a net.Conn.
func WrapConn(c *ws.Conn) net.Conn {
	return &Conn{conn: c}
}

// Read reads data from the WebSocket connection.
// It transparently handles WebSocket message boundaries,
// consuming messages one at a time.
func (c *Conn) Read(b []byte) (int, error) {
	c.rmu.Lock()
	defer c.rmu.Unlock()

	for {
		if c.reader != nil {
			n, err := c.reader.Read(b)
			if err == io.EOF {
				c.reader = nil
				if n > 0 {
					return n, nil
				}
				continue
			}
			return n, err
		}

		_, reader, err := c.conn.NextReader()
		if err != nil {
			return 0, err
		}
		c.reader = reader
	}
}

// Write writes data as a binary WebSocket message.
func (c *Conn) Write(b []byte) (int, error) {
	c.wmu.Lock()
	defer c.wmu.Unlock()

	err := c.conn.WriteMessage(ws.BinaryMessage, b)
	if err != nil {
		return 0, err
	}
	return len(b), nil
}

// Close sends a close message and closes the underlying connection.
func (c *Conn) Close() error {
	// Send close message (best-effort)
	_ = c.conn.WriteMessage(
		ws.CloseMessage,
		ws.FormatCloseMessage(ws.CloseNormalClosure, ""),
	)
	return c.conn.Close()
}

// LocalAddr returns the local network address.
func (c *Conn) LocalAddr() net.Addr {
	return c.conn.LocalAddr()
}

// RemoteAddr returns the remote network address.
func (c *Conn) RemoteAddr() net.Addr {
	return c.conn.RemoteAddr()
}

// SetDeadline sets both read and write deadlines.
func (c *Conn) SetDeadline(t time.Time) error {
	if err := c.conn.SetReadDeadline(t); err != nil {
		return err
	}
	return c.conn.SetWriteDeadline(t)
}

// SetReadDeadline sets the read deadline.
func (c *Conn) SetReadDeadline(t time.Time) error {
	return c.conn.SetReadDeadline(t)
}

// SetWriteDeadline sets the write deadline.
func (c *Conn) SetWriteDeadline(t time.Time) error {
	return c.conn.SetWriteDeadline(t)
}

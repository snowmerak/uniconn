package secure

import (
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	"golang.org/x/crypto/chacha20poly1305"
)

// SecureConn wraps a net.Conn (or io.ReadWriter) with XChaCha20-Poly1305
// encryption. It implements net.Conn so it can be used transparently
// anywhere a net.Conn is expected.
type SecureConn struct {
	inner io.ReadWriter

	// Encryption state.
	sendKey      [32]byte
	recvKey      [32]byte
	sendNoncePfx [NoncePrefixSize]byte
	recvNoncePfx [NoncePrefixSize]byte

	sendCounter uint64
	sendMu      sync.Mutex

	// Receive buffering: DATA messages may carry more plaintext than
	// the caller's Read buffer, so we buffer excess bytes.
	recvBuf []byte
	recvMu  sync.Mutex

	// For net.Conn interface: delegate to inner if it's a net.Conn.
	netConn net.Conn
}

func newSecureConn(rw io.ReadWriter, keys *sessionKeys, isInitiator bool) *SecureConn {
	sc := &SecureConn{inner: rw}

	if isInitiator {
		sc.sendKey = keys.InitiatorKey
		sc.recvKey = keys.ResponderKey
		sc.sendNoncePfx = keys.InitiatorNoncePfx
		sc.recvNoncePfx = keys.ResponderNoncePfx
	} else {
		sc.sendKey = keys.ResponderKey
		sc.recvKey = keys.InitiatorKey
		sc.sendNoncePfx = keys.ResponderNoncePfx
		sc.recvNoncePfx = keys.InitiatorNoncePfx
	}

	if nc, ok := rw.(net.Conn); ok {
		sc.netConn = nc
	}

	return sc
}

// Write encrypts plaintext and sends it as a DATA message.
func (sc *SecureConn) Write(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}

	sc.sendMu.Lock()
	counter := sc.sendCounter
	sc.sendCounter++
	sc.sendMu.Unlock()

	ts := uint32(time.Now().Unix())

	// Build nonce: [12B prefix][4B timestamp][8B counter].
	var nonce [NonceSize]byte
	copy(nonce[:NoncePrefixSize], sc.sendNoncePfx[:])
	binary.BigEndian.PutUint32(nonce[NoncePrefixSize:NoncePrefixSize+TimestampSize], ts)
	binary.BigEndian.PutUint64(nonce[NoncePrefixSize+TimestampSize:], counter)

	aead, err := chacha20poly1305.NewX(sc.sendKey[:])
	if err != nil {
		return 0, fmt.Errorf("xchacha20: %w", err)
	}

	ciphertext := aead.Seal(nil, nonce[:], p, nil)
	frame := marshalData(ts, counter, ciphertext)

	if _, err := sc.inner.Write(frame); err != nil {
		return 0, err
	}
	return len(p), nil
}

// Read returns decrypted plaintext from the next DATA message.
func (sc *SecureConn) Read(p []byte) (int, error) {
	sc.recvMu.Lock()
	defer sc.recvMu.Unlock()

	// Return buffered data first.
	if len(sc.recvBuf) > 0 {
		n := copy(p, sc.recvBuf)
		sc.recvBuf = sc.recvBuf[n:]
		return n, nil
	}

	// Read frame length.
	var frameLenBuf [4]byte
	if _, err := io.ReadFull(sc.inner.(io.Reader), frameLenBuf[:]); err != nil {
		return 0, err
	}
	frameLen := binary.BigEndian.Uint32(frameLenBuf[:])
	if frameLen > MaxMessageSize {
		return 0, fmt.Errorf("frame too large: %d", frameLen)
	}

	body := make([]byte, frameLen)
	if _, err := io.ReadFull(sc.inner.(io.Reader), body); err != nil {
		return 0, err
	}

	if len(body) < 1 {
		return 0, fmt.Errorf("empty frame")
	}

	switch body[0] {
	case MsgData:
		return sc.handleData(body, p)
	case MsgError:
		reason := ""
		if len(body) >= 3 {
			rLen := int(binary.BigEndian.Uint16(body[1:3]))
			if 3+rLen <= len(body) {
				reason = string(body[3 : 3+rLen])
			}
		}
		return 0, fmt.Errorf("peer error: %s", reason)
	default:
		return 0, fmt.Errorf("unexpected message type: 0x%02x", body[0])
	}
}

func (sc *SecureConn) handleData(body, p []byte) (int, error) {
	if len(body) < dataHeaderSize {
		return 0, fmt.Errorf("DATA message too short")
	}

	ts := binary.BigEndian.Uint32(body[1:5])
	counter := binary.BigEndian.Uint64(body[5:13])
	ciphertext := body[13:]

	// Reconstruct nonce.
	var nonce [NonceSize]byte
	copy(nonce[:NoncePrefixSize], sc.recvNoncePfx[:])
	binary.BigEndian.PutUint32(nonce[NoncePrefixSize:NoncePrefixSize+TimestampSize], ts)
	binary.BigEndian.PutUint64(nonce[NoncePrefixSize+TimestampSize:], counter)

	aead, err := chacha20poly1305.NewX(sc.recvKey[:])
	if err != nil {
		return 0, fmt.Errorf("xchacha20: %w", err)
	}

	plaintext, err := aead.Open(nil, nonce[:], ciphertext, nil)
	if err != nil {
		return 0, fmt.Errorf("decrypt: %w", err)
	}

	n := copy(p, plaintext)
	if n < len(plaintext) {
		sc.recvBuf = append(sc.recvBuf, plaintext[n:]...)
	}
	return n, nil
}

// Close closes the underlying connection.
func (sc *SecureConn) Close() error {
	// Send error message to notify peer (best-effort).
	errMsg := marshalError("closed")
	sc.inner.Write(errMsg) //nolint: errcheck

	if sc.netConn != nil {
		return sc.netConn.Close()
	}
	if closer, ok := sc.inner.(io.Closer); ok {
		return closer.Close()
	}
	return nil
}

// — net.Conn interface delegation ——————————————————————————————

func (sc *SecureConn) LocalAddr() net.Addr {
	if sc.netConn != nil {
		return sc.netConn.LocalAddr()
	}
	return &net.TCPAddr{}
}

func (sc *SecureConn) RemoteAddr() net.Addr {
	if sc.netConn != nil {
		return sc.netConn.RemoteAddr()
	}
	return &net.TCPAddr{}
}

func (sc *SecureConn) SetDeadline(t time.Time) error {
	if sc.netConn != nil {
		return sc.netConn.SetDeadline(t)
	}
	return nil
}

func (sc *SecureConn) SetReadDeadline(t time.Time) error {
	if sc.netConn != nil {
		return sc.netConn.SetReadDeadline(t)
	}
	return nil
}

func (sc *SecureConn) SetWriteDeadline(t time.Time) error {
	if sc.netConn != nil {
		return sc.netConn.SetWriteDeadline(t)
	}
	return nil
}

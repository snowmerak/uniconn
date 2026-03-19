package secure

import (
	"encoding/binary"
	"fmt"
	"io"

	"github.com/cloudflare/circl/sign/mldsa/mldsa87"
)

// helloMsg represents a HELLO or HELLO_REPLY message.
type helloMsg struct {
	Type      byte
	PublicKey []byte // ML-DSA-87 public key (raw)
	Payload   []byte // ML-KEM-1024 ek (HELLO) or ct (HELLO_REPLY)
	Signature []byte // ML-DSA-87 signature over Payload
}

// marshal serializes a hello message with framing.
//
// Wire format:
//
//	[4B frame_len][1B type][2B pubkey_len][pubkey][2B payload_len][payload][2B sig_len][sig]
func (m *helloMsg) marshal() []byte {
	bodyLen := 1 + 2 + len(m.PublicKey) + 2 + len(m.Payload) + 2 + len(m.Signature)
	buf := make([]byte, 4+bodyLen)

	binary.BigEndian.PutUint32(buf[0:4], uint32(bodyLen))
	off := 4
	buf[off] = m.Type
	off++

	binary.BigEndian.PutUint16(buf[off:off+2], uint16(len(m.PublicKey)))
	off += 2
	copy(buf[off:], m.PublicKey)
	off += len(m.PublicKey)

	binary.BigEndian.PutUint16(buf[off:off+2], uint16(len(m.Payload)))
	off += 2
	copy(buf[off:], m.Payload)
	off += len(m.Payload)

	binary.BigEndian.PutUint16(buf[off:off+2], uint16(len(m.Signature)))
	off += 2
	copy(buf[off:], m.Signature)

	return buf
}

// unmarshalHello reads a framed hello message from a reader.
func unmarshalHello(r io.Reader) (*helloMsg, error) {
	// Read frame length.
	var frameLenBuf [4]byte
	if _, err := io.ReadFull(r, frameLenBuf[:]); err != nil {
		return nil, fmt.Errorf("read frame length: %w", err)
	}
	frameLen := binary.BigEndian.Uint32(frameLenBuf[:])
	if frameLen > MaxMessageSize {
		return nil, fmt.Errorf("frame too large: %d", frameLen)
	}

	body := make([]byte, frameLen)
	if _, err := io.ReadFull(r, body); err != nil {
		return nil, fmt.Errorf("read frame body: %w", err)
	}

	if len(body) < 1 {
		return nil, fmt.Errorf("empty message body")
	}

	msg := &helloMsg{Type: body[0]}
	off := 1

	// Public key.
	if off+2 > len(body) {
		return nil, fmt.Errorf("truncated pubkey length")
	}
	pkLen := int(binary.BigEndian.Uint16(body[off : off+2]))
	off += 2
	if off+pkLen > len(body) {
		return nil, fmt.Errorf("truncated pubkey data")
	}
	msg.PublicKey = body[off : off+pkLen]
	off += pkLen

	// Payload (ek or ct).
	if off+2 > len(body) {
		return nil, fmt.Errorf("truncated payload length")
	}
	plLen := int(binary.BigEndian.Uint16(body[off : off+2]))
	off += 2
	if off+plLen > len(body) {
		return nil, fmt.Errorf("truncated payload data")
	}
	msg.Payload = body[off : off+plLen]
	off += plLen

	// Signature.
	if off+2 > len(body) {
		return nil, fmt.Errorf("truncated signature length")
	}
	sigLen := int(binary.BigEndian.Uint16(body[off : off+2]))
	off += 2
	if off+sigLen > len(body) {
		return nil, fmt.Errorf("truncated signature data")
	}
	msg.Signature = body[off : off+sigLen]

	return msg, nil
}

// dataHeader is the fixed part of a DATA message (before ciphertext).
// Wire: [4B frame_len][1B type=0x03][4B timestamp][8B counter][ciphertext...]
const dataHeaderSize = 1 + TimestampSize + CounterSize // 13 bytes

func marshalData(timestamp uint32, counter uint64, ciphertext []byte) []byte {
	bodyLen := dataHeaderSize + len(ciphertext)
	buf := make([]byte, 4+bodyLen)

	binary.BigEndian.PutUint32(buf[0:4], uint32(bodyLen))
	buf[4] = MsgData
	binary.BigEndian.PutUint32(buf[5:9], timestamp)
	binary.BigEndian.PutUint64(buf[9:17], counter)
	copy(buf[17:], ciphertext)

	return buf
}

func marshalError(reason string) []byte {
	reasonBytes := []byte(reason)
	bodyLen := 1 + 2 + len(reasonBytes)
	buf := make([]byte, 4+bodyLen)
	binary.BigEndian.PutUint32(buf[0:4], uint32(bodyLen))
	buf[4] = MsgError
	binary.BigEndian.PutUint16(buf[5:7], uint16(len(reasonBytes)))
	copy(buf[7:], reasonBytes)
	return buf
}

// parseMDSA87PublicKey deserializes an ML-DSA-87 public key.
func parseMDSA87PublicKey(raw []byte) (*mldsa87.PublicKey, error) {
	pub := new(mldsa87.PublicKey)
	if err := pub.UnmarshalBinary(raw); err != nil {
		return nil, fmt.Errorf("invalid mldsa87 public key: %w", err)
	}
	return pub, nil
}

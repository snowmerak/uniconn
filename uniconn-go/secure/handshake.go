package secure

import (
	"crypto/mlkem"
	"fmt"
	"io"

	"lukechampine.com/blake3"
)

// sessionKeys holds the derived encryption keys and nonce prefixes.
type sessionKeys struct {
	InitiatorKey      [32]byte
	ResponderKey      [32]byte
	InitiatorNoncePfx [NoncePrefixSize]byte
	ResponderNoncePfx [NoncePrefixSize]byte
}

// deriveKeys derives session keys from the ML-KEM shared secret using BLAKE3.
func deriveKeys(sharedSecret []byte) *sessionKeys {
	h := blake3.New(KDFOutputSize, nil)
	h.Write([]byte(KDFContext))
	h.Write(sharedSecret)
	out := h.Sum(nil)

	sk := &sessionKeys{}
	copy(sk.InitiatorKey[:], out[0:32])
	copy(sk.ResponderKey[:], out[32:64])
	copy(sk.InitiatorNoncePfx[:], out[64:76])
	copy(sk.ResponderNoncePfx[:], out[76:88])
	return sk
}

// HandshakeInitiator performs the initiator side of the USCP handshake.
//
//  1. Generate ephemeral ML-KEM-1024 key pair
//  2. Sign the encapsulation key with our ML-DSA-87 identity
//  3. Send HELLO
//  4. Receive HELLO_REPLY
//  5. Verify peer fingerprint and signature
//  6. Decapsulate shared secret
//  7. Derive session keys
func HandshakeInitiator(rw io.ReadWriter, id *Identity, peerFP Fingerprint) (*SecureConn, error) {
	// 1. Ephemeral ML-KEM-1024.
	dk, err := mlkem.GenerateKey1024()
	if err != nil {
		return nil, fmt.Errorf("mlkem keygen: %w", err)
	}
	ek := dk.EncapsulationKey().Bytes()

	// 2. Sign ek.
	sig, err := id.Sign(ek)
	if err != nil {
		return nil, fmt.Errorf("sign ek: %w", err)
	}

	// 3. Send HELLO.
	pubBytes, _ := id.PublicKey.MarshalBinary()
	hello := &helloMsg{
		Type:      MsgHello,
		PublicKey: pubBytes,
		Payload:   ek,
		Signature: sig,
	}
	if _, err := rw.Write(hello.marshal()); err != nil {
		return nil, fmt.Errorf("send hello: %w", err)
	}

	// 4. Receive HELLO_REPLY.
	reply, err := unmarshalHello(rw.(io.Reader))
	if err != nil {
		return nil, fmt.Errorf("recv hello_reply: %w", err)
	}
	if reply.Type != MsgHelloReply {
		return nil, fmt.Errorf("expected HELLO_REPLY (0x%02x), got 0x%02x", MsgHelloReply, reply.Type)
	}

	// 5. Verify peer.
	peerPub, err := parseMDSA87PublicKey(reply.PublicKey)
	if err != nil {
		return nil, err
	}
	gotFP := computeFingerprintBytes(reply.PublicKey)
	if gotFP != peerFP {
		return nil, fmt.Errorf("fingerprint mismatch")
	}
	if !Verify(peerPub, reply.Payload, reply.Signature) {
		return nil, fmt.Errorf("signature verification failed")
	}

	// 6. Decapsulate.
	ss, err := dk.Decapsulate(reply.Payload)
	if err != nil {
		return nil, fmt.Errorf("mlkem decaps: %w", err)
	}

	// 7. Derive keys.
	keys := deriveKeys(ss)

	return newSecureConn(rw, keys, true), nil
}

// HandshakeResponder performs the responder side of the USCP handshake.
//
//  1. Receive HELLO
//  2. Verify peer fingerprint and signature
//  3. Encapsulate shared secret with peer's ek
//  4. Sign the ciphertext with our ML-DSA-87 identity
//  5. Send HELLO_REPLY
//  6. Derive session keys
func HandshakeResponder(rw io.ReadWriter, id *Identity, peerFP Fingerprint) (*SecureConn, error) {
	// 1. Receive HELLO.
	hello, err := unmarshalHello(rw.(io.Reader))
	if err != nil {
		return nil, fmt.Errorf("recv hello: %w", err)
	}
	if hello.Type != MsgHello {
		return nil, fmt.Errorf("expected HELLO (0x%02x), got 0x%02x", MsgHello, hello.Type)
	}

	// 2. Verify peer.
	peerPub, err := parseMDSA87PublicKey(hello.PublicKey)
	if err != nil {
		return nil, err
	}
	gotFP := computeFingerprintBytes(hello.PublicKey)
	if gotFP != peerFP {
		return nil, fmt.Errorf("fingerprint mismatch")
	}
	if !Verify(peerPub, hello.Payload, hello.Signature) {
		return nil, fmt.Errorf("signature verification failed")
	}

	// 3. Encapsulate.
	peerEK, err := mlkem.NewEncapsulationKey1024(hello.Payload)
	if err != nil {
		return nil, fmt.Errorf("parse mlkem ek: %w", err)
	}
	ss, ct := peerEK.Encapsulate()

	// 4. Sign ct.
	sig, err := id.Sign(ct)
	if err != nil {
		return nil, fmt.Errorf("sign ct: %w", err)
	}

	// 5. Send HELLO_REPLY.
	pubBytes, _ := id.PublicKey.MarshalBinary()
	reply := &helloMsg{
		Type:      MsgHelloReply,
		PublicKey: pubBytes,
		Payload:   ct,
		Signature: sig,
	}
	if _, err := rw.Write(reply.marshal()); err != nil {
		return nil, fmt.Errorf("send hello_reply: %w", err)
	}

	// 6. Derive keys.
	keys := deriveKeys(ss)

	return newSecureConn(rw, keys, false), nil
}

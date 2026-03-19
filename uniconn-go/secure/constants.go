package secure

// Protocol constants for USCP v1.
const (
	// Message types.
	MsgHello      = 0x01
	MsgHelloReply = 0x02
	MsgData       = 0x03
	MsgError      = 0xFF

	// Sizes.
	FingerprintSize = 64
	KDFOutputSize   = 88
	NonceSize       = 24
	NoncePrefixSize = 12
	TimestampSize   = 4
	CounterSize     = 8
	TagSize         = 16
	MaxMessageSize  = 16_777_216

	// KDF context.
	KDFContext = "uniconn-e2ee-v1"
)

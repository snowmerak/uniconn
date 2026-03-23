package multi

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"time"

	uniconn "github.com/snowmerak/uniconn/uniconn-go"
)

// DialerConfig configures a MultiDialer.
type DialerConfig struct {
	// NegotiateURL is the full URL of the negotiate endpoint
	// (e.g. "http://server:19000/negotiate").
	NegotiateURL string

	// Priority overrides the default protocol preference order.
	// If nil, DefaultPriority is used.
	Priority []Protocol

	// Dialers maps each Protocol to its pre-configured uniconn.Dialer.
	// Only protocols with a registered dialer will be attempted.
	Dialers map[Protocol]uniconn.Dialer

	// DialTimeout is the per-protocol connection attempt timeout.
	// Defaults to DefaultDialTimeout if zero.
	DialTimeout time.Duration

	// HTTPClient is used for the negotiate request.
	// If nil, http.DefaultClient is used.
	HTTPClient *http.Client
}

// MultiDialer negotiates available protocols with the server and
// connects using the highest-priority protocol.
type MultiDialer struct {
	config DialerConfig
}

// NewMultiDialer creates a new multi-protocol dialer.
func NewMultiDialer(config DialerConfig) *MultiDialer {
	if config.Priority == nil {
		config.Priority = DefaultPriority
	}
	if config.DialTimeout == 0 {
		config.DialTimeout = DefaultDialTimeout
	}
	if config.HTTPClient == nil {
		config.HTTPClient = http.DefaultClient
	}
	return &MultiDialer{config: config}
}

// Dial negotiates with the server and connects via the best available protocol.
//
// It fetches the negotiate endpoint, intersects the server's protocols with
// the client's registered dialers, and attempts to connect in priority order.
// Returns the connection, the protocol used, and any error.
func (md *MultiDialer) Dial(ctx context.Context) (net.Conn, Protocol, error) {
	// 1. Fetch negotiate response.
	serverProtos, err := md.negotiate(ctx)
	if err != nil {
		return nil, "", fmt.Errorf("negotiate: %w", err)
	}

	// Build a map of server protocol → address.
	serverMap := make(map[Protocol]string, len(serverProtos))
	for _, p := range serverProtos {
		serverMap[p.Name] = p.Address
	}

	// 2. Try protocols in priority order.
	var lastErr error
	for _, proto := range md.config.Priority {
		address, serverHas := serverMap[proto]
		if !serverHas {
			continue
		}

		d, clientHas := md.config.Dialers[proto]
		if !clientHas {
			continue
		}

		// Attempt connection with timeout.
		dialCtx, cancel := context.WithTimeout(ctx, md.config.DialTimeout)
		conn, err := d.Dial(dialCtx, address)
		cancel()

		if err != nil {
			lastErr = fmt.Errorf("[%s] %w", proto, err)
			continue
		}

		return conn, proto, nil
	}

	if lastErr != nil {
		return nil, "", fmt.Errorf("all protocols failed, last: %w", lastErr)
	}
	return nil, "", fmt.Errorf("no compatible protocol found")
}

// negotiate fetches the negotiate endpoint and parses the response.
func (md *MultiDialer) negotiate(ctx context.Context) ([]ProtocolEntry, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, md.config.NegotiateURL, nil)
	if err != nil {
		return nil, err
	}

	resp, err := md.config.HTTPClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected status: %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var neg NegotiateResponse
	if err := json.Unmarshal(body, &neg); err != nil {
		return nil, fmt.Errorf("parse negotiate response: %w", err)
	}

	return neg.Protocols, nil
}

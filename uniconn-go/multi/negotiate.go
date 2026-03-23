package multi

import (
	"encoding/json"
	"net/http"
)

// ProtocolEntry describes a single available protocol and its address.
type ProtocolEntry struct {
	// Name is the protocol identifier (e.g. "tcp", "websocket").
	Name Protocol `json:"name"`
	// Address is the protocol-specific address (e.g. "host:8080", "ws://host:8080/ws").
	Address string `json:"address"`
}

// NegotiateResponse is the JSON response returned by the negotiate endpoint.
type NegotiateResponse struct {
	// Protocols lists all available protocols on this server.
	Protocols []ProtocolEntry `json:"protocols"`
	// Fingerprint is the optional ML-DSA identity fingerprint of the server.
	Fingerprint string `json:"fingerprint,omitempty"`
}

// NegotiateHandler returns an http.HandlerFunc that serves the negotiate
// response as JSON. The handler responds with 200 OK and Content-Type
// application/json.
func NegotiateHandler(entries []ProtocolEntry, fingerprint string) http.HandlerFunc {
	resp := NegotiateResponse{Protocols: entries, Fingerprint: fingerprint}
	body, _ := json.Marshal(resp)

	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write(body)
	}
}

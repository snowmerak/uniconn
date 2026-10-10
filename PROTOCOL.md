# Uniconn Protocol Specification

The **Uniconn** protocol establishes cross-runtime End-to-End Encrypted (E2EE) data tunnels using dynamic proxy relays. It relies on multi-layer handshakes to securely bridge Node endpoints regardless of NAT configuration.

## 1. Topologies

1.  **Node**: A logical client (Initiator or Responder). Each Node constructs an ML-DSA-87 identity fingerprint (2592-byte `publicKeyRaw` hashing to a 64-byte Fingerprint, formatted as a 128-char hex string).
2.  **Relay (Router)**: Go-based servers that expose multiple inbound listening endpoints (TCP, WS, KCP, HTTP). Relays interconnect forming a loosely coupled Mesh Federation that routes proxy connections payload-agnostically.

## 2. Multi-Transport Negotiation (`/negotiate`)

Heterogeneous runtimes might only natively support a subset of protocols (e.g., Web Browser -> WebSockets only; Go -> TCP/KCP; Node.js -> TCP). Uniconn handles this transparently using an HTTP Negotiation scheme.

### Sequence:
1.  **Initiator/Node HTTP request**: `GET http://<relay-address>:<negotiate_port>/negotiate`
2.  **Relay Response** (JSON Object): Lists live `multi.ProtocolEntry`.

```json
{
  "protocols": [
    {"name": "tcp", "address": "127.0.0.1:10011"},
    {"name": "kcp", "address": "127.0.0.1:10012"},
    {"name": "websocket", "address": "ws://127.0.0.1:10002"}
  ]
}
```

3.  The caller's `MultiDialer` iterates matching known protocol priorities (e.g., WebTransport > QUIC > WebSocket > KCP > TCP) against the server offerings and completes the physical socket dial.

## 3. End-to-End Encryption Frame (E2EE Handshake)

After physical connections (TCP, WS, etc.) succeed, the E2EE Handshake occurs immediately to exchange temporary cryptographic streams before any JSON logic is injected. Uniconn employs ML-DSA signatures.

1.  **Client (Initiator)** `secure.HandshakeInitiator`:
    *   Generates an ephemeral ML-KEM-1024 key pair.
    *   Signs the encapsulation key with the long-lived ML-DSA-87 identity.
    *   Authenticates with ML-DSA-87 Identity PrivateKey (`sign`).
    *   Transmits `HELLO`.
2.  **Server/Peer (Responder)** `secure.HandshakeResponder`:
    *   Receives `HELLO`, validates the ML-DSA signature against `publicKeyRaw`.
    *   Encapsulates a shared secret and replies with signed `HELLO_REPLY` ciphertext.
3.  **Encrypted Tunnel Bound**: The connection upgrades to a `SecureConn` implementing the standard I/O stream interface. All subsequent payloads are XChaCha20-Poly1305 encrypted. Each direction starts its DATA counter at zero. A receiver accepts only its next expected counter, advancing it after successful AEAD verification. Senders serialize frame writes to preserve order. Replayed or reordered DATA frames are rejected; the wire format is unchanged.

The Go public relay accepts connections using `secure.AnyFingerprint`, but verifies the presented identity signature. Go callers may explicitly use that wildcard; Python and TypeScript callers must supply the exact relay fingerprint. The nested peer handshake always authenticates the requested peer identity.

## 4. Control Frame Format (JSON Envelopes)

Upon E2EE binding, Uniconn multiplexes control traffic utilizing Newline-delimited JSON (`\n` framing). All nodes natively parse arbitrary structs into the `Envelope` interface:

```json
{
  "type": "MESSAGE_TYPE_STRING",
  "payload": { ... } // arbitrary runtime-dependent object context
}
```

*In Go, `payload` is designated as `json.RawMessage` allowing late binding.*

## 5. Gossip & Routing Metadata

Public Relays act as directories mapping `TargetFingerprint -> RelayPhysicalEndpoint`.

*   **`ANNOUNCE`**: Sent by a Node upon connection. Instructs its connected Relay to associate `controlConn` with its `Fingerprint`.
*   **`GOSSIP_UPDATE`**: Triggered when a Relay receives an `ANNOUNCE`. The Relay broadcasts an asynchronous JSON Envelope:
    `{"type": "GOSSIP_UPDATE", "payload": {"fingerprint": "xyz...", "relay_address": "R1:Port", "timestamp": 123...}}`
*   All peering Relays update their `globalRouting[Fingerprint]` cache based on timestamps.

## 6. Two-Hop Dumb Pipe Tunneling Flow

When Node A dictates traffic for Node B.

1.  **Node A** forms the P2P intent by writing `RELAY_REQ` targeting Node B’s Fingerprint to its upstream Relay (R_A).
2.  **Relay A**:
    *   Reads `RELAY_REQ`. Checks its `activeNodes` cache.
    *   If Node B is connected to Relay A, skip to Step 5.
    *   Otherwise, consults `globalRouting` table for Node B. It finds Node B is connected to Relay B.
3.  **Relay A -> Relay B (Inter-Relay Hop)**:
    *   Relay A dials Relay B (using physical negotiation TCP/KCP).
    *   Relay A issues an internal envelope: `RELAY_INTERNAL_REQ` carrying `SourceFingerprint=Node A` and `TargetFingerprint=Node B`.
4.  **Relay B -> Node B**:
    *   Relay B correlates `TargetFingerprint` to Node B's active control socket.
    *   Relay B issues `INCOMING_RELAY` specifying the unique `SessionToken` identifying Relay A's connection waiting-tube.
5.  **Node B -> Relay B Validation**:
    *   Node B provisions a *brand new connection socket* back to Relay B.
    *   Node B executes the secure handshake and sends `ACCEPT_RELAY` quoting the `SessionToken`.
6.  **Splicing**:
    *   Relay B splices (via `io.Copy`) the new connection from Node B back down the waiting `RELAY_INTERNAL_REQ` tunnel from Relay A.
    *   Relay A routes the response payload back to Node A with a `RELAY_ACK`.
7.  **Data Pump**: All relays relinquish the envelope parsers. The connection becomes a direct byte pipe strictly shuttling opaque `SecureConn` streams. Node A and Node B can now conduct a *secondary layered P2P E2EE Handshake* exclusively over the relay proxy.

## 7. Connection Lifecycle

Connection setup includes transport dialing, relay acknowledgement and outer/nested handshakes. The default setup timeout is ten seconds (`SetupTimeout` in Go, `setup_timeout` in Python and `setupTimeoutMs` in TypeScript). Go context cancellation and TypeScript `DialOptions.signal` also interrupt setup.

`SecureConn.Close/close` closes the underlying connection directly, without waiting to write an error frame. Peer EOF or a transport error signals closure; callers must not require a final `MSG_ERROR` notification. Closing a MultiListener wakes pending accepts and closes queued connections it still owns.

Node shutdown, relay disconnection or replacement cancels pending setup and fails all pending accepts in that session. Connections already returned by `DialPeer/dial_peer/dialPeer` or `Accept/accept` belong to callers and are not closed by Node shutdown. Applications close those connections separately. A disconnected Node may explicitly reconnect; a closed Node cannot reconnect.

Node control envelopes and incoming Go relay control envelopes are limited to 64 KiB. Fingerprint strings must contain exactly 128 hexadecimal characters before routing or gossip state is modified.

# Uniconn Protocol Specification

The **Uniconn** protocol establishes cross-runtime End-to-End Encrypted (E2EE) data tunnels using dynamic proxy relays. It relies on multi-layer handshakes to securely bridge Node endpoints regardless of NAT configuration.

## 1. Topologies

1.  **Node**: A logical client (Initiator or Responder). Each Node constructs an ML-DSA-87 identity fingerprint (2592-byte `publicKeyRaw` hashing to a 64-byte Fingerprint, formatted as a 128-char hex string).
2.  **Relay (Router)**: Go-based servers that expose multiple inbound listening endpoints (TCP, WS, KCP, HTTP). Relays interconnect forming a loosely coupled Mesh Federation that routes proxy connections payload-agnostically.

## 2. Multi-Transport Negotiation (`/negotiate`)

Heterogeneous runtimes might only natively support a subset of protocols (e.g., Web Browser -> WebSockets only; Go -> TCP/KCP; Node.js -> TCP). Uniconn handles this transparently using an HTTP Negotiation scheme.

### Sequence:
1.  **Initiator/Node HTTP request**: `GET http://<relay-address>:<negotiate_port>/negotiate`
2.  **Relay Response** (JSON Array): Lists live `multi.ProtocolEntry`. 

```json
[
  {"protocol": "tcp", "address": "127.0.0.1:10011"},
  {"protocol": "kcp", "address": "127.0.0.1:10012"},
  {"protocol": "websocket", "address": "127.0.0.1:10002"}
]
```

3.  The caller's `MultiDialer` iterates matching known protocol priorities (e.g., TCP > WS > KCP) against the server offerings and completes the physical socket dial.

## 3. End-to-End Encryption Frame (E2EE Handshake)

After physical connections (TCP, WS, etc.) succeed, the E2EE Handshake occurs immediately to exchange temporary cryptographic streams before any JSON logic is injected. Uniconn employs ML-DSA signatures.

1.  **Client (Initiator)** `secure.HandshakeInitiator`:
    *   Generates Ephemeral KeyPair / Nonces.
    *   Initiate Diffie-Hellman / Key Encapsulation (Kyber).
    *   Authenticates with ML-DSA-87 Identity PrivateKey (`sign`).
    *   Transmits `ClientHello`.
2.  **Server/Peer (Responder)** `secure.HandshakeResponder`:
    *   Receives `ClientHello`, validates ML-DSA signature against `publicKeyRaw`.
    *   Replies with `ServerHello` authenticating back.
3.  **Encrypted Tunnel Bound**: The connection upgrades to a `SecureConn` implementing the standard I/O stream interface. All subsequent payloads are ChaCha20-Poly1305 encrypted.

*(Note: During `Relay <-> Node` connections, since the Relay operates purely in a pass-through manner for P2P routing, it utilizes an `<AnyFingerprint>` bypass configuration because it does not strictly need to authenticate public anonymous Nodes joining the mesh, unless specifically constrained).*

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

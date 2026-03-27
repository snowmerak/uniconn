# Uniconn

**Uniconn** is a unified, multi-protocol, cross-language Peer-to-Peer (P2P) networking and tunneling library. It provides **Quantum-Safe End-to-End Encryption (E2EE)** using ML-DSA-87 signatures and dynamic transport negotiation across heterogeneous runtimes.

Uniconn is built for the modern web and decentralized services, enabling seamless connectivity between backend servers (Go), web browsers/Node.js (TypeScript), and data science/automation environments (Python) utilizing a Federated Relay Mesh.

## Features

- **Quantum-Safe Identity**: Uses ML-DSA-87 (FIPS 204) for cryptographic fingerprints and E2EE Handshakes. No CA required.
- **Dynamic Protocol Negotiation**: Transparently falls back across TCP, WebSockets, and KCP relying on an HTTP `/negotiate` endpoint.
- **Relay Federation & Gossip**: Nodes connect to any participating public Relay. Relays synchronize Peer locations globally through a seamless Gossip Protocol.
- **2-Hop E2EE Tunneling**: Connections across different Relay zones are automatically proxy-linked, maintaining end-to-end encryption without the intermediaries being able to read payload data.
- **Multi-Runtime Clients**: Native implementations for **Go** (High-Performance/Relay Server), **Python 3** (asyncio), and **TypeScript** (Node.js & Browser via WebSockets).

---

## Quick Start

### 1. Launch a Relay Server (Go)

The Relay acts as the backbone of the communication. It tracks connected Nodes and facilitates transparent byte-proxying for P2P connection attempts.

```bash
cd uniconn-go
# Run the Relay listening on TCP(10011), KCP(10012), and Negotiator HTTP(19002)
go run ../uniconn-tests/tools/relay.go -tcp=127.0.0.1:10011 -kcp=127.0.0.1:10012 -neg=127.0.0.1:19002
```

*(Note: To form a Federation Mesh, launch another Relay and pass the seed flag `-seeds=127.0.0.1:19002`)*

### 2. Connect a Responder Node (Python)

A Responder waits for incoming P2P streams.

```python
import asyncio
from uniconn.secure.identity import Identity
from uniconn.p2p.node import Node, DefaultNodeConfig
from uniconn.tcp.dialer import TcpDialer

async def main():
    identity = Identity.generate()
    node = Node(DefaultNodeConfig, identity, TcpDialer())

    print(f"My Fingerprint: {identity.fingerprint().hex()}")

    # Connect to the Relay
    await node.connect_relay("127.0.0.1:10011", b"")

    print("Waiting for peer connection...")
    conn = await node.accept()
    
    # Secure P2P Byte Tunnel is established!
    await conn.write(b"Hello from Python!")

asyncio.run(main())
```

### 3. Connect an Initiator Node (TypeScript/Node.js)

An Initiator dials the Responder using its ML-DSA Fingerprint. Uniconn's backend mesh handles locating the Responder, allocating the optimal transport, and tunneling the traffic.

```typescript
import { Node, DefaultNodeConfig } from '@uniconn/core/p2p';
import { NodeIdentity, nodeVerify } from '@uniconn/node/secure/identity';
import { TcpDialer } from '@uniconn/node/tcp/dialer';

async function main() {
  const id = NodeIdentity.generate();
  const node = new Node(DefaultNodeConfig, id, nodeVerify, new TcpDialer());

  // Connect to Relay
  await node.connectRelay("127.0.0.1:10011", Buffer.alloc(64));

  // The 128-char hex fingerprint of the Python Responder
  const targetFp = Buffer.from("target-fingerprint-hex...", "hex");
  
  // Dial transparently
  const conn = await node.dialPeer(targetFp);

  const buf = new Uint8Array(1024);
  const n = await conn.read(buf);
  console.log("Received:", new TextDecoder().decode(buf.subarray(0, n))); 
  // Outputs: "Hello from Python!"
}

main();
```

---

## Directory Structure

*   `uniconn-go/`: Core Relay Router logic and High-Performance Go Client.
*   `uniconn-js/`: Core logic and interfaces for Browser/Node.js platforms.
    *   `core/`: Handshakes, Identity primitives, and Envelope parsing.
    *   `node/`: TCP/WS bindings using Node.js native API.
    *   `browser/`: WebCrypto API integration and Browser WebSocket support.
*   `uniconn-py/`: Complete Python `asyncio` client with `cryptography` integration.
*   `uniconn-tests/`: Cross-Language integration meshes and protocol verification logic.
*   `PROTOCOL.md`: Specific low-level architecture, JSON envelope schema, and routing flow.

## License

MIT

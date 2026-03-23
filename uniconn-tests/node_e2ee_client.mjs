/**
 * Node.js E2EE TCP client for Go secure crosstest server.
 *
 * Usage:  node node_e2ee_client.mjs <host> <port> <serverFingerprintHex>
 *
 * Outputs JSON lines:
 *   1: { "fingerprint": "<hex>" }
 *   2: { "echo": "<text>", "match": true/false }
 */

import * as net from "node:net";
import * as path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Direct dist imports via file:// URLs
const nodeDist = path.join(__dirname, "..", "uniconn-js", "node", "dist");
const coreDist = path.join(__dirname, "..", "uniconn-js", "core", "dist");

const { TcpConn } = await import(pathToFileURL(path.join(nodeDist, "tcp", "conn.js")).href);
const { NodeIdentity, nodeVerify } = await import(pathToFileURL(path.join(nodeDist, "secure", "identity.js")).href);
const { handshakeInitiator } = await import(pathToFileURL(path.join(coreDist, "secure", "handshake.js")).href);

const host = process.argv[2] || "127.0.0.1";
const port = parseInt(process.argv[3], 10);
const serverFPHex = process.argv[4];

if (!port || !serverFPHex) {
  console.error("Usage: node node_e2ee_client.mjs <host> <port> <serverFingerprintHex>");
  process.exit(1);
}

const serverFP = new Uint8Array(Buffer.from(serverFPHex, "hex"));

// Generate identity.
const identity = NodeIdentity.generate();
const fp = identity.fingerprint();

// Output our fingerprint for the test harness.
console.log(JSON.stringify({ fingerprint: Buffer.from(fp).toString("hex") }));

// Connect to Go server.
const socket = net.createConnection(port, host);
await new Promise((resolve, reject) => {
  socket.once("connect", resolve);
  socket.once("error", reject);
});

const conn = new TcpConn(socket);

// Perform USCP handshake (initiator).
const secureConn = await handshakeInitiator(conn, identity, serverFP, nodeVerify);

// E2EE echo test.
const testData = new TextEncoder().encode("hello, E2EE from Node!");
await secureConn.write(testData);

const buf = new Uint8Array(1024);
const n = await secureConn.read(buf);
const received = buf.subarray(0, n);

const match = Buffer.from(received).equals(Buffer.from(testData));
console.log(JSON.stringify({ echo: Buffer.from(received).toString("utf-8"), match }));

await secureConn.close();
process.exit(match ? 0 : 1);

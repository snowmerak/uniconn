/**
 * Node.js echo client for cross-language integration tests.
 *
 * Usage: echo <hex-data> | node node_client.mjs <protocol> <address>
 * Protocols: tcp, ws
 *
 * Reads hex-encoded data from stdin, connects, sends data,
 * reads echo, prints result as hex to stdout, exits.
 */
import * as net from "node:net";
import { TcpConn } from "../uniconn-js/node/dist/tcp/conn.js";
import { WsDialer } from "../uniconn-js/node/dist/websocket/dialer.js";

const [protocol, address] = process.argv.slice(2);
if (!protocol || !address) {
  console.error("Usage: echo <hex-data> | node node_client.mjs <tcp|ws> <address>");
  process.exit(1);
}

// Read hex data from stdin.
const chunks = [];
for await (const chunk of process.stdin) {
  chunks.push(chunk);
}
const hexData = Buffer.concat(chunks).toString("utf8").trim();
const data = Buffer.from(hexData, "hex");

async function main() {
  if (protocol === "tcp") {
    const [host, portStr] = address.split(":");
    const port = parseInt(portStr);
    const sock = net.createConnection(port, host);
    await new Promise((resolve) => sock.once("connect", resolve));
    const conn = new TcpConn(sock);

    await conn.write(data);

    const buf = new Uint8Array(data.length + 1024);
    const received = [];
    while (received.length < data.length) {
      const n = await conn.read(buf);
      if (n === 0) break;
      received.push(...buf.subarray(0, n));
    }

    await conn.close();
    process.stdout.write(Buffer.from(received).toString("hex"));

  } else if (protocol === "ws") {
    const dialer = new WsDialer();
    const conn = await dialer.dial(address);

    await conn.write(data);

    const buf = new Uint8Array(data.length + 1024);
    const received = [];
    while (received.length < data.length) {
      const n = await conn.read(buf);
      if (n === 0) break;
      received.push(...buf.subarray(0, n));
    }

    await conn.close();
    process.stdout.write(Buffer.from(received).toString("hex"));

  } else {
    console.error(`Unknown protocol: ${protocol}`);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

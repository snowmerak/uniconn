/**
 * Node.js echo server for cross-language integration tests.
 *
 * Usage: node node_server.mjs <protocol> [port]
 * Protocols: tcp, ws
 *
 * Prints "READY:<port>" when listening.
 */
import * as net from "node:net";
import { createRequire } from "node:module";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

// Use createRequire to load ws from uniconn-js/node_modules
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsRequire = createRequire(path.join(__dirname, "..", "uniconn-js", "node_modules", "x.js"));
const { WebSocketServer } = jsRequire("ws");

const [protocol, portArg] = process.argv.slice(2);
const port = parseInt(portArg || "0");

if (protocol === "tcp") {
  const server = net.createServer((conn) => {
    conn.pipe(conn); // echo
  });
  server.listen(port, "127.0.0.1", () => {
    const addr = server.address();
    console.log(`READY:${addr.port}`);
  });

} else if (protocol === "ws") {
  const wss = new WebSocketServer({ port, host: "127.0.0.1" });
  wss.on("listening", () => {
    const addr = wss.address();
    console.log(`READY:${addr.port}`);
  });
  wss.on("connection", (ws) => {
    ws.on("message", (data) => {
      ws.send(data); // echo
    });
  });

} else {
  console.error(`Unknown protocol: ${protocol}`);
  process.exit(1);
}

/**
 * Cross-platform E2EE integration test: Node.js client ↔ Go server.
 *
 * 1. Spawns the Go echo server as a child process.
 * 2. Reads the server info (port, fingerprint, pubkey) from stdout.
 * 3. Generates Node identity, sends own fingerprint to Go server via stdin.
 * 4. Connects via TCP, does USCP handshake.
 * 5. Sends test data, reads echo, verifies match.
 */
import { describe, test } from "node:test";
import * as assert from "node:assert/strict";
import { spawn } from "node:child_process";
import * as net from "node:net";
import * as readline from "node:readline";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import { TcpConn } from "../tcp/conn.js";
import { handshakeInitiator, computeFingerprint } from "../secure/index.js";
import { NodeIdentity, nodeVerify } from "../secure/identity.node.js";

interface ServerInfo {
  port: number;
  wsPort: number;
  fingerprint: string;
  publicKey: string;
}

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

/** Resolve the uniconn-go directory relative to this file. */
function goDir(): string {
  const thisDir = path.dirname(fileURLToPath(import.meta.url));
  // dist/test/ → project root → ../uniconn-go
  return path.resolve(thisDir, "..", "..", "..", "uniconn-go");
}

describe("USCP E2EE Cross-Platform (Node ↔ Go)", () => {
  test("handshake + echo via Go server", async () => {
    // 1. Spawn Go echo server.
    const cwd = goDir();
    console.log("  Go dir:", cwd);
    const goProc = spawn("go", ["run", "./secure/crosstest/server"], {
      cwd,
      stdio: ["pipe", "pipe", "pipe"],
    });

    // Capture stderr for debugging.
    goProc.stderr!.on("data", (chunk: Buffer) => {
      process.stderr.write(`  [go] ${chunk}`);
    });

    // 2. Read server info from stdout.
    const rl = readline.createInterface({ input: goProc.stdout! });
    const serverInfo: ServerInfo = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error("timeout waiting for Go server")), 30000);
      rl.once("line", (line) => {
        clearTimeout(timeout);
        try { resolve(JSON.parse(line)); }
        catch (e) { reject(new Error(`invalid server info: ${line}`)); }
      });
      goProc.on("error", reject);
    });
    rl.close();

    console.log("  Go server info:", serverInfo);

    // 3. Generate Node identity and send fingerprint to Go.
    const nodeId = NodeIdentity.generate();
    const nodeFP = nodeId.fingerprint();
    goProc.stdin!.write(bytesToHex(nodeFP) + "\n");

    // Parse Go server fingerprint.
    const goFP = hexToBytes(serverInfo.fingerprint);

    // 4. TCP connect + USCP handshake.
    const sock = net.createConnection(serverInfo.port, "127.0.0.1");
    await new Promise<void>((resolve) => sock.once("connect", resolve));
    const conn = new TcpConn(sock);
    const sc = await handshakeInitiator(conn, nodeId, goFP, nodeVerify);
    console.log("  Node handshake OK with Go server");

    // 5. Send test data and verify echo.
    const testData = new TextEncoder().encode("cross-platform E2EE works!");
    await sc.write(testData);

    const buf = new Uint8Array(1024);
    const n = await sc.read(buf);
    assert.deepStrictEqual(buf.subarray(0, n), testData);
    console.log("  Echo verified:", new TextDecoder().decode(buf.subarray(0, n)));

    // 6. Test larger payload (16KB).
    const bigData = new Uint8Array(16384);
    for (let i = 0; i < bigData.length; i++) bigData[i] = i % 256;
    await sc.write(bigData);

    const received: number[] = [];
    const readBuf = new Uint8Array(4096);
    while (received.length < bigData.length) {
      const rn = await sc.read(readBuf);
      received.push(...readBuf.subarray(0, rn));
    }
    assert.deepStrictEqual(new Uint8Array(received), bigData);
    console.log("  16KB echo verified");

    // Cleanup.
    await sc.close();
    goProc.kill();
  });
});

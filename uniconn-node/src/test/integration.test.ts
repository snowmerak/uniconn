/**
 * Cross-platform integration test: Node.js client ↔ Go echo server.
 *
 * Spawns the Go echo server, runs TCP and WebSocket echo tests,
 * then kills the server process.
 *
 * Usage: node --test dist/test/integration.test.js
 */
import { describe, it, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn, execSync, type ChildProcess } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

import { TcpDialer } from "../tcp/index.js";
import { WsDialer } from "../websocket/index.js";
import { KcpDialer } from "../kcp/index.js";
import type { IConn } from "../conn.js";

let goServer: ChildProcess;

function startGoServer(): Promise<ChildProcess> {
  return new Promise((resolve, reject) => {
    const proc = spawn(
      "go",
      ["run", "./cmd/echoserver"],
      {
        cwd: process.env.UNICONN_GO_DIR || "../uniconn-go",
        stdio: ["ignore", "pipe", "pipe"],
        detached: false,
      },
    );

    let started = false;
    const timeout = setTimeout(() => {
      if (!started) {
        killProc(proc);
        reject(new Error("Go echo server did not start within 30s"));
      }
    }, 30000);

    proc.stdout!.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      process.stdout.write(`[go] ${text}`);
      if (text.includes("READY") && !started) {
        started = true;
        clearTimeout(timeout);
        resolve(proc);
      }
    });

    proc.stderr!.on("data", (chunk: Buffer) => {
      process.stderr.write(`[go] ${chunk.toString()}`);
    });

    proc.on("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    proc.on("exit", (code) => {
      if (!started) {
        clearTimeout(timeout);
        reject(new Error(`Go server exited (code ${code}) before ready`));
      }
    });
  });
}

/** Forcefully kill a process tree on Windows. */
function killProc(proc: ChildProcess) {
  try {
    if (proc.pid) {
      execSync(`taskkill /pid ${proc.pid} /t /f`, { stdio: "ignore" });
    }
  } catch {
    proc.kill("SIGKILL");
  }
}

/** Echo test: write → read → compare. */
async function testEcho(conn: IConn, testData: Uint8Array): Promise<void> {
  conn.setReadDeadline(5000);

  const written = await conn.write(testData);
  assert.equal(written, testData.length, "write all bytes");

  const recvBuf = new Uint8Array(testData.length + 1024);
  let totalRead = 0;

  while (totalRead < testData.length) {
    try {
      const n = await conn.read(recvBuf.subarray(totalRead));
      if (n === 0) break;
      totalRead += n;
    } catch (err: any) {
      if (err.name === "TimeoutError") break;
      throw err;
    }
  }

  assert.equal(totalRead, testData.length, `got ${totalRead}/${testData.length} bytes`);
  assert.deepEqual(recvBuf.subarray(0, totalRead), testData, "data matches");
}

describe("Go ↔ Node.js Integration", () => {
  before(async () => {
    goServer = await startGoServer();
    await sleep(300);
  });

  after(async () => {
    if (goServer) {
      killProc(goServer);
      await sleep(500);
    }
  });

  // ── TCP ──────────────────────────────────────────────
  describe("TCP", () => {
    it("short text echo", { timeout: 10000 }, async () => {
      const conn = await new TcpDialer().dial("127.0.0.1:19001", { timeout: 3000 });
      try {
        await testEcho(conn, new TextEncoder().encode("hello uniconn TCP!"));
      } finally { await conn.close(); }
    });

    it("binary 256B echo", { timeout: 10000 }, async () => {
      const conn = await new TcpDialer().dial("127.0.0.1:19001", { timeout: 3000 });
      try {
        const d = new Uint8Array(256);
        for (let i = 0; i < 256; i++) d[i] = i;
        await testEcho(conn, d);
      } finally { await conn.close(); }
    });

    it("large 64KB echo", { timeout: 15000 }, async () => {
      const conn = await new TcpDialer().dial("127.0.0.1:19001", { timeout: 3000 });
      try {
        const d = new Uint8Array(65536);
        for (let i = 0; i < d.length; i++) d[i] = i % 256;
        await testEcho(conn, d);
      } finally { await conn.close(); }
    });
  });

  // ── WebSocket ────────────────────────────────────────
  describe("WebSocket", () => {
    it("short text echo", { timeout: 10000 }, async () => {
      const conn = await new WsDialer().dial("ws://127.0.0.1:19002/echo", { timeout: 3000 });
      try {
        await testEcho(conn, new TextEncoder().encode("hello uniconn WS!"));
      } finally { await conn.close(); }
    });

    it("binary 256B echo", { timeout: 10000 }, async () => {
      const conn = await new WsDialer().dial("ws://127.0.0.1:19002/echo", { timeout: 3000 });
      try {
        const d = new Uint8Array(256);
        for (let i = 0; i < 256; i++) d[i] = i;
        await testEcho(conn, d);
      } finally { await conn.close(); }
    });

    it("large 64KB echo", { timeout: 15000 }, async () => {
      const conn = await new WsDialer().dial("ws://127.0.0.1:19002/echo", { timeout: 3000 });
      try {
        const d = new Uint8Array(65536);
        for (let i = 0; i < d.length; i++) d[i] = i % 256;
        await testEcho(conn, d);
      } finally { await conn.close(); }
    });
  });

  // ── KCP ──────────────────────────────────────────────
  describe("KCP", () => {
    it("short text echo", { timeout: 10000 }, async () => {
      const conn = await new KcpDialer().dial("127.0.0.1:19005");
      try {
        await testEcho(conn, new TextEncoder().encode("hello uniconn KCP!"));
      } finally { await conn.close(); }
    });

    it("binary 256B echo", { timeout: 10000 }, async () => {
      const conn = await new KcpDialer().dial("127.0.0.1:19005");
      try {
        const d = new Uint8Array(256);
        for (let i = 0; i < 256; i++) d[i] = i;
        await testEcho(conn, d);
      } finally { await conn.close(); }
    });
  });
});


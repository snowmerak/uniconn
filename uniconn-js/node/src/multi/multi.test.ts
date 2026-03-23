/**
 * Tests for multi-protocol negotiate, MultiDialer, and MultiListener.
 */

import { describe, it } from "node:test";
import * as assert from "node:assert/strict";
import * as http from "node:http";

import {
  MultiDialer,
  MultiListener,
  type ProtocolEntry,
  type NegotiateResponse,
  type TransportConfig,
  type Protocol,
} from "@uniconn/core/multi";
import type { IConn, IListener, IDialer, Addr, DialOptions } from "@uniconn/core/conn";

// ─── Mock implementations ───────────────────────────────────

class MockConn implements IConn {
  private data: Uint8Array[] = [];
  closed = false;

  async write(d: Uint8Array): Promise<number> {
    this.data.push(d.slice());
    return d.length;
  }
  async read(buffer: Uint8Array): Promise<number> {
    const d = this.data.shift();
    if (!d) return 0;
    buffer.set(d);
    return d.length;
  }
  async close() { this.closed = true; }
  localAddr(): Addr { return { network: "mock", address: "local" }; }
  remoteAddr(): Addr { return { network: "mock", address: "remote" }; }
  setDeadline() {}
  setReadDeadline() {}
  setWriteDeadline() {}
}

class MockListener implements IListener {
  private queue: IConn[] = [];
  private waiters: Array<(conn: IConn) => void> = [];
  private closed = false;

  push(conn: IConn) {
    const w = this.waiters.shift();
    if (w) { w(conn); } else { this.queue.push(conn); }
  }

  async accept(): Promise<IConn> {
    if (this.closed) throw new Error("closed");
    const q = this.queue.shift();
    if (q) return q;
    return new Promise<IConn>((r) => this.waiters.push(r));
  }
  async close() { this.closed = true; }
  addr(): Addr { return { network: "mock", address: "mock:0" }; }
}

class MockDialer implements IDialer {
  shouldFail: boolean;
  constructor(shouldFail = false) { this.shouldFail = shouldFail; }
  async dial(_addr: string, _opts?: DialOptions): Promise<IConn> {
    if (this.shouldFail) throw new Error("mock dial failure");
    return new MockConn();
  }
}

// ─── Tests ──────────────────────────────────────────────────

describe("NegotiateResponse", () => {
  it("serializes correctly", () => {
    const entries: ProtocolEntry[] = [
      { name: "tcp", address: "server:8001" },
      { name: "websocket", address: "ws://server:8002/ws" },
    ];
    const resp: NegotiateResponse = { protocols: entries };
    const json = JSON.stringify(resp);
    const parsed = JSON.parse(json) as NegotiateResponse;
    assert.equal(parsed.protocols.length, 2);
    assert.equal(parsed.protocols[0].name, "tcp");
  });
});

describe("MultiListener", () => {
  it("fans-in from multiple transports", async () => {
    const ln1 = new MockListener();
    const ln2 = new MockListener();

    const ml = new MultiListener([
      { protocol: "tcp" as Protocol, address: "host:1", listener: ln1 },
      { protocol: "websocket" as Protocol, address: "ws://host:2/ws", listener: ln2 },
    ]);

    // Push connections into both listeners.
    const conn1 = new MockConn();
    const conn2 = new MockConn();
    ln1.push(conn1);
    ln2.push(conn2);

    // Accept should get both.
    const r1 = await ml.acceptWith();
    const r2 = await ml.acceptWith();

    const protos = new Set([r1.protocol, r2.protocol]);
    assert.ok(protos.has("tcp"));
    assert.ok(protos.has("websocket"));

    await ml.close();
  });

  it("generates negotiate response", () => {
    const ml = new MultiListener([
      { protocol: "tcp" as Protocol, address: "host:1", listener: new MockListener() },
    ]);
    const neg = ml.getNegotiateResponse();
    assert.equal(neg.protocols.length, 1);
    assert.equal(neg.protocols[0].name, "tcp");
    ml.close();
  });
});

describe("MultiDialer", () => {
  it("selects best available protocol via negotiate", async () => {
    // Set up a mock negotiate HTTP server.
    const negResponse: NegotiateResponse = {
      protocols: [
        { name: "websocket", address: "ws://127.0.0.1:9999/ws" },
        { name: "tcp", address: "127.0.0.1:9998" },
      ],
    };

    const server = http.createServer((_req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(negResponse));
    });

    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as any).port;

    try {
      // Client only has TCP dialer → should select TCP.
      const md = new MultiDialer({
        negotiateURL: `http://127.0.0.1:${port}/negotiate`,
        dialers: { tcp: new MockDialer() },
        dialTimeout: 2000,
      });

      const { protocol } = await md.dial();
      assert.equal(protocol, "tcp");
    } finally {
      server.close();
    }
  });

  it("falls back when first protocol fails", async () => {
    const negResponse: NegotiateResponse = {
      protocols: [
        { name: "websocket", address: "ws://127.0.0.1:9999/ws" },
        { name: "tcp", address: "127.0.0.1:9998" },
      ],
    };

    const server = http.createServer((_req, res) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(negResponse));
    });

    await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
    const port = (server.address() as any).port;

    try {
      // WS dialer fails, TCP succeeds → should fall back to TCP.
      const md = new MultiDialer({
        negotiateURL: `http://127.0.0.1:${port}/negotiate`,
        dialers: {
          websocket: new MockDialer(true), // fails
          tcp: new MockDialer(false),      // succeeds
        },
        dialTimeout: 1000,
      });

      const { protocol } = await md.dial();
      assert.equal(protocol, "tcp");
    } finally {
      server.close();
    }
  });
});
